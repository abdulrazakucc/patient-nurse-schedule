"""
Prediction engine for VLBW infant outcomes.

Because the source data is aggregated (empirical medians / quartiles per bin rather
than patient-level rows), predictions are produced by:

  1. Locating the birth-weight bin and gestational-age (GA) bin for the input.
  2. Linearly interpolating the median / IQR between neighbouring bin mid-points so
     that a 720 g infant is not treated identically to a 799 g infant.
  3. Blending the weight-based and GA-based length-of-stay estimates.
  4. Deriving disposition probabilities (Home / Transfer / Died) and survival from
     the empirical N counts in the survival dataset.

Every number returned is traceable back to the underlying dataset, and each result
carries an explicit confidence signal based on the sample size (N) behind it.
"""
from __future__ import annotations

from typing import Optional

from .data_loader import (
    DATASET,
    GA_BINS,
    WEIGHT_BINS,
    Bin,
    Stat,
)

# Disposition rows inside the survival dataset.
DISP_HOME = "Initial Length of Stay (By Disposition) - Home"
DISP_TRANSFER = "Initial Length of Stay (By Disposition) - Transfer"
DISP_DIED = "Initial Length of Stay (By Disposition) - Died"
DISP_ALL = "Initial Length of Stay (By Disposition) - All"
TOTAL_LOS = "Total Length Of Stay"
PREDICTED_LOS = "Predicted Length of Stay"


def _find_bin(value: float, bins: list[Bin], inclusive_high: bool = True) -> int:
    """Return index of the bin containing value (clamped to the ends).

    Weight bins are inclusive of their upper bound (e.g. 800 g -> 701-800 g);
    gestational-age bins are half-open (e.g. 25.0 -> "25 Weeks", not "24 Weeks").
    """
    for i, b in enumerate(bins):
        if (value <= b.high) if inclusive_high else (value < b.high):
            return i
    return len(bins) - 1


def _interp_stat(
    value: float,
    bins: list[Bin],
    per_bin: dict[str, Stat],
    attr: str,
) -> Optional[float]:
    """Linearly interpolate a Stat attribute across neighbouring bin mid-points."""
    points: list[tuple[float, float]] = []
    for b in bins:
        stat = per_bin.get(b.label)
        if stat is None:
            continue
        v = getattr(stat, attr)
        if v is not None:
            points.append((b.midpoint, v))
    if not points:
        return None
    points.sort()
    # Clamp outside the range.
    if value <= points[0][0]:
        return points[0][1]
    if value >= points[-1][0]:
        return points[-1][1]
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x0 <= value <= x1:
            if x1 == x0:
                return y0
            frac = (value - x0) / (x1 - x0)
            return y0 + frac * (y1 - y0)
    return points[-1][1]


def _los_estimate(bins, per_bin, value):
    return {
        "median": _interp_stat(value, bins, per_bin, "median"),
        "q1": _interp_stat(value, bins, per_bin, "q1"),
        "q3": _interp_stat(value, bins, per_bin, "q3"),
    }


def _round(v: Optional[float], nd: int = 1) -> Optional[float]:
    return round(v, nd) if v is not None else None


def _confidence(n: Optional[int]) -> str:
    if n is None:
        return "unknown"
    if n >= 50:
        return "high"
    if n >= 20:
        return "moderate"
    if n >= 5:
        return "low"
    return "very low"


def predict(weight_g: float, ga_weeks: float) -> dict:
    """Produce a full outcome prediction for a single infant."""
    w_idx = _find_bin(weight_g, WEIGHT_BINS, inclusive_high=True)
    g_idx = _find_bin(ga_weeks, GA_BINS, inclusive_high=False)
    weight_bin = WEIGHT_BINS[w_idx]
    ga_bin = GA_BINS[g_idx]

    # ---- Length of stay ---------------------------------------------------
    los_w = _los_estimate(WEIGHT_BINS, DATASET.los_by_weight.get(TOTAL_LOS, {}), weight_g)
    los_g = _los_estimate(GA_BINS, DATASET.los_by_ga.get(TOTAL_LOS, {}), ga_weeks)

    def blend(a, b):
        vals = [v for v in (a, b) if v is not None]
        return sum(vals) / len(vals) if vals else None

    los_blended = {
        "median": _round(blend(los_w["median"], los_g["median"])),
        "q1": _round(blend(los_w["q1"], los_g["q1"])),
        "q3": _round(blend(los_w["q3"], los_g["q3"])),
    }

    # ---- Disposition probabilities (from empirical N counts by weight) ----
    surv = DATASET.survival_by_weight
    def _n(row):
        stat = surv.get(row, {}).get(weight_bin.label)
        return (stat.n if stat and stat.n else 0)

    n_home = _n(DISP_HOME)
    n_transfer = _n(DISP_TRANSFER)
    n_died = _n(DISP_DIED)
    n_all = _n(DISP_ALL) or (n_home + n_transfer + n_died)

    if n_all > 0:
        p_home = n_home / n_all
        p_transfer = n_transfer / n_all
        p_died = n_died / n_all
    else:
        p_home = p_transfer = p_died = None

    survival_prob = (1 - p_died) if p_died is not None else None

    # Per-disposition LOS (from survival dataset, weight-interpolated).
    disp_los = {
        "home": _los_estimate(WEIGHT_BINS, surv.get(DISP_HOME, {}), weight_g),
        "transfer": _los_estimate(WEIGHT_BINS, surv.get(DISP_TRANSFER, {}), weight_g),
        "died": _los_estimate(WEIGHT_BINS, surv.get(DISP_DIED, {}), weight_g),
    }
    for d in disp_los.values():
        for k in d:
            d[k] = _round(d[k])

    return {
        "input": {"weight_g": weight_g, "ga_weeks": ga_weeks},
        "weight_bin": weight_bin.label,
        "ga_bin": ga_bin.label,
        "length_of_stay": {
            "blended": los_blended,
            "by_weight": {k: _round(v) for k, v in los_w.items()},
            "by_ga": {k: _round(v) for k, v in los_g.items()},
            "unit": "days",
        },
        "disposition": {
            "home": _round(p_home * 100, 1) if p_home is not None else None,
            "transfer": _round(p_transfer * 100, 1) if p_transfer is not None else None,
            "died": _round(p_died * 100, 1) if p_died is not None else None,
            "unit": "percent",
        },
        "survival_probability": _round(survival_prob * 100, 1) if survival_prob is not None else None,
        "disposition_los": disp_los,
        "sample_size": n_all,
        "confidence": _confidence(n_all),
    }
