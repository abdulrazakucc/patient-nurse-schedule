"""Patient-journey runtime: features and predictions with numpy only.

Vendored, unchanged apart from this paragraph, from the acuity-models project
(src/acuity_ml/runtime.py), which trains the models. Every model bundle carries
check cases computed there; app.journey runs them when it loads a bundle and
refuses one this copy does not reproduce, and tests/test_journey_parity.py
holds the browser engine (frontend/journey-engine.js) to this file.

This module is the single definition of how a board entry becomes model features
and how a trained bundle turns features into a prediction. Training uses it to
build every feature (so training and serving cannot drift apart), the export
checks the bundle against it, and the NeoStay server ships a copy of it. It
depends on numpy and the standard library only.

A *bundle* is a JSON document holding the input tables, the fitted encoders and
model parameters, and check cases with their expected outputs.

Input of one prediction
-----------------------
``record``: the baby's current board entry (one shift)::

    ga_weeks, bw_g                birth facts (decimal weeks, grams)
    dol, weight_g                 day of life, today's weight (grams)
    shifts_in_unit                12-hour shifts since admission (0 on the admission shift)
    shift, day_of_week            "AM"/"PM" and the day name of the current shift
    acuity_ratio                  "1:3-4", "1:3", "1:2-3", "1:2" or "1:1"
    resp_status                   respiratory label of the board ("RA", "CPAP", "≤4L HFNC", ...)
    resp_flow_lpm, resp_peep      numbers when recorded
    feeds                         feeding label of the board ("OG/NG-full", "PO ad lib", ...)
    iv_lines                      list of line types ("PIV", "PICC", "UVC", "UAC", "PAL", "DEEP_PIV")
    iv_fluids, iv_saline_lock     true/false
    spells                        spells code ("intervention", "self_resolved", ...; default "not_recorded")
    nas_band, procedure           codes, or null
    care_area                     "icu", "intermediate", "unlisted" or "unused"
    has_education_need            true/false

``history``: earlier board entries of the same stay, each with ``shifts_ago``
(1 = 12 hours earlier ... 14) and the per-shift fields above. Missing shifts are
left out; any field may be null.
"""

from __future__ import annotations

import math

import numpy as np

BUNDLE_FORMAT = "neostay-journey/1"
DAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
SHIFTS = ("AM", "PM")
NAN = math.nan

STATIC_FIELDS = ("ga_weeks", "bw_g")
SHIFT_FIELDS = ("acuity_ratio", "dol", "weight_g", "resp_status", "resp_flow_lpm", "resp_peep", "feeds", "iv_lines",
                "iv_fluids", "iv_saline_lock", "spells", "nas_band", "procedure", "care_area", "has_education_need")
RECORD_FIELDS = STATIC_FIELDS + SHIFT_FIELDS + ("shifts_in_unit", "shift", "day_of_week")


class InputError(ValueError):
    """The request does not match the bundle's input schema."""


# ---------------------------------------------------------------------------
# Input checks
# ---------------------------------------------------------------------------
def _number(value, name: str) -> float:
    if value is None:
        return NAN
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InputError(f"{name} must be a number or null")
    value = float(value)
    if math.isinf(value):
        raise InputError(f"{name} must be finite")
    return value


def _in_range(value: float, name: str, ranges: dict) -> float:
    if not math.isnan(value) and name in ranges:
        lo, hi = ranges[name]
        if not lo <= value <= hi:
            raise InputError(f"{name}={value:g} is outside the valid range {lo:g}-{hi:g}")
    return value


def _flag(value, name: str) -> bool:
    if value is None:
        return False
    if not isinstance(value, bool):
        raise InputError(f"{name} must be true, false or null")
    return value


def _choice(value, name: str, allowed) -> str | None:
    if value is None:
        return None
    try:
        ok = value in allowed
    except TypeError:  # an unhashable value such as a list
        ok = False
    if not ok:
        raise InputError(f"{name}={value!r} is not one of {sorted(allowed)}")
    return value


def _whole(value) -> int | None:
    """A whole number (JSON may carry 3 as 3.0), else None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


# ---------------------------------------------------------------------------
# Features
# ---------------------------------------------------------------------------
def shift_features(entry: dict, tables: dict) -> dict:
    """Features of one board entry (one shift), from the bundle's input tables."""
    unknown = set(entry) - set(SHIFT_FIELDS) - {"shifts_ago"} - set(RECORD_FIELDS)
    if unknown:
        raise InputError(f"unknown fields: {sorted(unknown)}")
    ranges = tables["valid_ranges"]
    f = {}
    ratio = _choice(entry.get("acuity_ratio"), "acuity_ratio", tables["acuity_level"])
    f["acuity_level"] = float(tables["acuity_level"][ratio]) if ratio else NAN
    f["dol"] = _in_range(_number(entry.get("dol"), "dol"), "dol", ranges)
    f["weight_g"] = _in_range(_number(entry.get("weight_g"), "weight_g"), "weight_g", ranges)

    resp = _choice(entry.get("resp_status"), "resp_status", tables["resp_status"])
    row = tables["resp_status"][resp] if resp else {"mode": None, "tier": None, "ino": False}
    f["resp_mode"] = row["mode"]
    f["resp_tier"] = NAN if row["tier"] is None else float(row["tier"])
    f["resp_ino"] = bool(row["ino"])
    f["resp_flow_lpm"] = _number(entry.get("resp_flow_lpm"), "resp_flow_lpm")
    f["resp_peep"] = _number(entry.get("resp_peep"), "resp_peep")

    feeds = _choice(entry.get("feeds"), "feeds", tables["feeds"])
    row = tables["feeds"][feeds] if feeds else tables["feeds_missing"]
    f["feeds"] = feeds
    f.update(row)

    lines = entry.get("iv_lines") or []
    if not isinstance(lines, list):
        raise InputError("iv_lines must be a list")
    iv = tables["iv"]
    for token in lines:
        _choice(token, "iv_lines", iv["tokens"])
    for token in iv["tokens"]:
        f[f"iv_{token.lower()}"] = token in lines
    f["iv_fluids"] = _flag(entry.get("iv_fluids"), "iv_fluids")
    f["iv_saline_lock"] = _flag(entry.get("iv_saline_lock"), "iv_saline_lock")
    f["iv_central"] = any(t in lines for t in iv["central"])
    f["iv_arterial"] = any(t in lines for t in iv["arterial"])
    f["iv_line_count"] = float(len(set(lines)))

    spells = _choice(entry.get("spells") or "not_recorded", "spells", tables["spells"])
    f["spells"] = spells
    f.update(tables["spells"][spells])
    f["nas_band"] = _choice(entry.get("nas_band"), "nas_band", tables["nas_band"])
    f["nas_scoring"] = f["nas_band"] is not None
    f["procedure"] = _choice(entry.get("procedure"), "procedure", tables["procedure"])
    f["care_area"] = _choice(entry.get("care_area"), "care_area", tables["care_area"])
    f["has_education_need"] = _flag(entry.get("has_education_need"), "has_education_need")
    return f


def _window(values: list[float]) -> list[float]:
    return [v for v in values if not math.isnan(v)]


def compute_features(record: dict, history: list[dict], tables: dict, history_shifts: int) -> dict:
    """All features of a landmark: the current entry, birth facts and the recent history."""
    ranges = tables["valid_ranges"]
    f = shift_features(record, tables)
    f["ga_weeks"] = _in_range(_number(record.get("ga_weeks"), "ga_weeks"), "ga_weeks", ranges)
    f["bw_g"] = _in_range(_number(record.get("bw_g"), "bw_g"), "bw_g", ranges)
    f["cga_weeks"] = f["ga_weeks"] + f["dol"] / 7  # NaN when either is unknown

    stay = _whole(record.get("shifts_in_unit"))
    if stay is None or stay < 0:
        raise InputError("shifts_in_unit must be a whole number >= 0")
    f["shifts_in_unit"] = float(min(stay, history_shifts))
    f["shift"] = _choice(record.get("shift"), "shift", SHIFTS)
    f["day_of_week"] = _choice(record.get("day_of_week"), "day_of_week", DAY_NAMES)
    if f["shift"] is None or f["day_of_week"] is None:
        raise InputError("shift and day_of_week are required")

    past = {}
    for entry in history or []:
        k = _whole(entry.get("shifts_ago"))
        if k is None or not 1 <= k <= history_shifts:
            raise InputError(f"shifts_ago must be a whole number from 1 to {history_shifts}")
        if k in past:
            raise InputError(f"two history entries for shifts_ago={k}")
        if k > stay:
            raise InputError(f"history entry shifts_ago={k} is before admission (shifts_in_unit={stay})")
        past[k] = shift_features(entry, tables)

    def lag(col, k):
        return past[k][col] if k in past else NAN

    level, tier = f["acuity_level"], f["resp_tier"]
    f["acuity_level_lag1"], f["acuity_level_lag2"] = lag("acuity_level", 1), lag("acuity_level", 2)
    f["acuity_change_lag1"] = level - f["acuity_level_lag1"]
    levels = _window([level] + [p["acuity_level"] for p in past.values()])
    f["acuity_level_max_window"] = max(levels) if levels else NAN
    f["acuity_level_min_window"] = min(levels) if levels else NAN
    f["acuity_level_mean_window"] = sum(levels) / len(levels) if levels else NAN
    run = NAN
    if not math.isnan(level):
        run, k = 1, 1
        while k in past and past[k]["acuity_level"] == level:
            run, k = run + 1, k + 1
    f["shifts_at_current_acuity"] = float(run)
    f["resp_tier_lag1"], f["resp_tier_lag2"] = lag("resp_tier", 1), lag("resp_tier", 2)
    tiers = _window([tier] + [p["resp_tier"] for p in past.values()])
    f["resp_tier_max_window"] = max(tiers) if tiers else NAN
    weighed = [k for k in sorted(past) if not math.isnan(past[k]["weight_g"])]
    f["weight_change_g_per_day"] = NAN
    if weighed and not math.isnan(f["weight_g"]):
        k = weighed[-1]  # the earliest weight in the window
        f["weight_change_g_per_day"] = (f["weight_g"] - past[k]["weight_g"]) / (k / 2)  # 2 shifts a day
    return f


def period_calendar(shift: str, day_of_week: str, h: int) -> tuple[str, str]:
    """Shift and day of the shift h-1 after the current one: the 12 hours in which a
    baby who is gone by the board h shifts ahead leaves."""
    index = 2 * DAY_NAMES.index(day_of_week) + SHIFTS.index(shift) + h - 1
    return SHIFTS[index % 2], DAY_NAMES[(index // 2) % 7]


# ---------------------------------------------------------------------------
# Encoding
# ---------------------------------------------------------------------------
def encode(features: dict, encoder: dict, kind: str) -> np.ndarray:
    """Feature vector for a "linear" model (imputed, standardised, missing
    indicators) or a "tree" model (raw numbers with NaN)."""
    out = []
    for col in encoder["numeric"]:
        v = features[col["name"]]
        v = NAN if v is None else float(v)
        if kind == "tree":
            out.append(v)
            continue
        missing = math.isnan(v)
        out.append(((col["fill"] if missing else v) - col["mean"]) / col["scale"])
        if col["indicator"]:
            out.append(1.0 if missing else 0.0)
    for name in encoder["boolean"]:
        out.append(1.0 if features[name] else 0.0)
    for col in encoder["categorical"]:
        value = features[col["name"]]
        out.extend(1.0 if value == level else 0.0 for level in col["levels"])
    return np.asarray(out, dtype=float)


def encoded_names(encoder: dict, kind: str) -> list[str]:
    names = []
    for col in encoder["numeric"]:
        names.append(col["name"])
        if kind == "linear" and col["indicator"]:
            names.append(col["name"] + "__missing")
    names += list(encoder["boolean"])
    for col in encoder["categorical"]:
        names += [f"{col['name']}={level}" for level in col["levels"]]
    return names


def period_block(spec: dict, x: np.ndarray, h: int, shift: str, day: str) -> np.ndarray:
    """Columns that depend on the horizon h (appended to the landmark vector)."""
    out = []
    if spec.get("time_basis"):
        u = math.log(h) / math.log(spec["time_basis"]["horizon"])
        basis = [u ** (j + 1) for j in range(spec["time_basis"]["degree"])]
        out += basis
        out += list(x[spec["time_basis"]["interact"]] * u) if spec["time_basis"]["interact"] else []
    if spec.get("raw_h"):
        out.append(float(h))
    if spec.get("calendar"):
        p_shift, p_day = period_calendar(shift, day, h)
        out += [1.0 if p_shift == s else 0.0 for s in SHIFTS]
        out += [1.0 if p_day == d else 0.0 for d in DAY_NAMES]
    return np.asarray(out, dtype=float)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
def _sigmoid(z):
    return 1.0 / (1.0 + np.exp(-z))


def _softmax(z: np.ndarray) -> np.ndarray:
    z = z - z.max(axis=-1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(axis=-1, keepdims=True)


def tree_values(trees: list[dict], X: np.ndarray) -> np.ndarray:
    """Sum of the leaf values of a list of trees, for each row of X.

    Each tree holds parallel node arrays, as in scikit-learn's histogram gradient
    boosting: a missing value follows ``missing_left``; otherwise x <= threshold
    goes left.
    """
    X = np.atleast_2d(X)
    total = np.zeros(len(X))
    for tree in trees:
        feature, threshold = tree["feature"], tree["threshold"]
        left, right, missing_left = tree["left"], tree["right"], tree["missing_left"]
        leaf, value = tree["leaf"], tree["value"]
        for r in range(len(X)):
            node = 0
            while not leaf[node]:
                v = X[r, feature[node]]
                go_left = missing_left[node] if v != v else v <= threshold[node]
                node = left[node] if go_left else right[node]
            total[r] += value[node]
    return total


def survival_curve(model: dict, features: dict) -> np.ndarray:
    """P(baby still in the unit at the board h shifts ahead), h = 1..horizon."""
    H = model["horizon"]
    kind = model["type"]
    if kind == "km":
        return np.asarray(model["survival"], dtype=float)
    if kind == "km_by_level":
        level = features["acuity_level"]
        return np.asarray(model["overall"] if math.isnan(level) else model["by_level"][int(level)], dtype=float)
    x = encode(features, model["encoder"], "tree" if kind == "gbm_hazard" else "linear")
    if kind == "cox":
        risk = math.exp(float(np.dot(model["coef"], x)) + model["offset"])
        return np.asarray(model["baseline_survival"], dtype=float) ** risk
    rows = np.stack([np.concatenate([x, period_block(model["period"], x, h, features["shift"], features["day_of_week"])])
                     for h in range(1, H + 1)])
    if kind == "logistic_hazard":
        hazard = _sigmoid(rows @ np.asarray(model["coef"]) + model["intercept"])
    elif kind == "gbm_hazard":
        hazard = _sigmoid(model["baseline"] + tree_values(model["trees"], rows))
    else:
        raise InputError(f"unknown survival model type {kind!r}")
    return np.cumprod(1.0 - hazard)


def acuity_probabilities(model: dict, features: dict) -> np.ndarray:
    """P(nurse ratio level k at the board h shifts ahead | still in the unit), shape (H, levels)."""
    H, n_levels = model["horizon"], model["n_levels"]
    kind = model["type"]
    out = np.zeros((H, n_levels))
    if kind == "transition":
        level = features["acuity_level"]
        for h in range(1, H + 1):
            table = model["table"][h - 1]
            out[h - 1] = table["marginal"] if math.isnan(level) else table["by_level"][int(level)]
        return out
    x = encode(features, model["encoder"], "tree" if kind == "gbm_multiclass" else "linear")
    if kind == "multinomial_per_h":
        for h in range(1, H + 1):
            m = model["by_h"][h - 1]
            p = _softmax(np.asarray(m["coef"]) @ x + np.asarray(m["intercept"]))
            out[h - 1, m["classes"]] = p
        return out
    if kind == "gbm_multiclass":
        rows = np.stack([np.concatenate([x, [float(h)]]) for h in range(1, H + 1)])
        raw = np.stack([model["baseline"][k] + tree_values(model["trees"][k], rows) for k in range(len(model["classes"]))],
                       axis=1)
        out[:, model["classes"]] = _softmax(raw)
        return out
    raise InputError(f"unknown acuity model type {kind!r}")


# ---------------------------------------------------------------------------
# The prediction
# ---------------------------------------------------------------------------
def _quantile_shift(survival: np.ndarray, q: float) -> int | None:
    """Smallest h at which P(gone by the board h shifts ahead) >= q, or None."""
    hit = np.nonzero(1.0 - survival >= q - 1e-12)[0]
    return int(hit[0]) + 1 if len(hit) else None


def predict(bundle: dict, record: dict, history: list[dict] | None = None) -> dict:
    """The journey of one baby: remaining stay and nurse ratio over the coming shifts."""
    if bundle.get("format") != BUNDLE_FORMAT:
        raise InputError(f"bundle format must be {BUNDLE_FORMAT}")
    unknown = set(record) - set(RECORD_FIELDS)
    if unknown:
        raise InputError(f"unknown fields: {sorted(unknown)}")
    tables = bundle["inputs"]
    features = compute_features(record, history or [], tables, bundle["settings"]["history_shifts"])
    surv_model, acu_model = bundle["models"]["remaining_stay"], bundle["models"]["acuity"]
    survival = survival_curve(surv_model, features)
    acuity = acuity_probabilities(acu_model, features)
    ratios = tables["acuity_ratios"]
    hours = bundle["settings"]["shift_hours"]

    def days(h):
        # Remaining stay counts the shifts the baby is still on the board after now,
        # so leaving before the next board (h = 1) is 0 days.
        return None if h is None else (h - 1) * hours / 24

    median = _quantile_shift(survival, 0.5)
    stay = {
        "survival": [float(s) for s in survival],
        "p_gone_by_day": {str(d): float(1 - survival[int(d * 24 / hours) - 1])
                          for d in bundle["settings"]["report_days"] if d * 24 / hours <= len(survival)},
        "median_days": days(median),
        "quartile_days": [days(_quantile_shift(survival, 0.25)), days(_quantile_shift(survival, 0.75))],
        "beyond_horizon": median is None,
        "horizon_days": len(survival) * hours / 24,
    }
    fte_min, fte_max = np.asarray(tables["nurse_fte_min"]), np.asarray(tables["nurse_fte_max"])
    journey = []
    for h in range(1, len(acuity) + 1):
        present = float(survival[h - 1])
        p = acuity[h - 1]
        journey.append({
            "shifts_ahead": h,
            "hours_ahead": h * hours,
            "p_in_unit": present,
            "ratio_if_in_unit": {r: float(v) for r, v in zip(ratios, p)},
            "ratio": {r: float(present * v) for r, v in zip(ratios, p)},
            "expected_nurses": {"min": float(present * p @ fte_min), "max": float(present * p @ fte_max)},
        })
    return {"model_version": bundle["version"], "remaining_stay": stay, "acuity_journey": journey}


def self_check(bundle: dict, tol: float = 1e-9) -> int:
    """Run the bundle's check cases; raise if any output differs. Returns the number of cases."""
    for i, case in enumerate(bundle.get("checks", [])):
        got = predict(bundle, case["record"], case.get("history"))
        want = case["expected"]
        a = np.asarray(got["remaining_stay"]["survival"] + [v for j in got["acuity_journey"] for v in j["ratio"].values()])
        b = np.asarray(want["remaining_stay"]["survival"] + [v for j in want["acuity_journey"] for v in j["ratio"].values()])
        if a.shape != b.shape or not np.allclose(a, b, rtol=0, atol=tol):
            raise ValueError(f"bundle check case {i} does not reproduce its expected output")
    return len(bundle.get("checks", []))
