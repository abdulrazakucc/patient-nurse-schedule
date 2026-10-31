"""
Patient-journey models: how much longer a baby already in the unit is likely to
stay, and its nurse:patient ratio over the coming shifts.

The models are trained in the acuity-models project on the unit's own acuity
boards, and arrive as one JSON bundle. A server uses them once the bundle is
copied to ``NEOSTAY_MODEL_FILE`` (default ``<instance>/models/neostay-journey.json``).
The instance folder is server-private and git-ignored, so a model fitted to
hospital data is never committed with the code.

A bundle is read when first needed and again whenever the file changes. Before
it is used, its check cases are run through ``journey_runtime``; a bundle whose
results this server does not reproduce is refused, and the journey routes answer
503 until a good one is installed.
"""
from __future__ import annotations

import json
import threading

from . import config
from . import journey_runtime as runtime

InputError = runtime.InputError

# Metadata a page may show about the model; parameters and check cases stay out.
CARD_FIELDS = ("format", "version", "created", "settings", "training_data", "selection", "performance",
               "privacy_audit", "feature_sets", "intended_use", "inputs")


class ModelUnavailable(RuntimeError):
    """No usable journey model is installed."""


_lock = threading.Lock()
_state: dict = {"key": None, "bundle": None, "error": None}


def current() -> dict:
    """The installed bundle, checked. Raises ModelUnavailable."""
    path = config.MODEL_FILE
    try:
        stat = path.stat()
    except OSError:
        raise ModelUnavailable("No journey model is installed on this server.") from None
    key = (str(path), stat.st_mtime_ns, stat.st_size)
    with _lock:
        if _state["key"] != key:
            try:
                bundle = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(bundle, dict) or bundle.get("format") != runtime.BUNDLE_FORMAT:
                    raise ValueError(f"not a {runtime.BUNDLE_FORMAT} bundle")
                runtime.self_check(bundle)
            except Exception as exc:  # noqa: BLE001 - any defect makes the bundle unusable
                _state.update(key=key, bundle=None, error=f"The installed journey model was refused: {exc}")
            else:
                _state.update(key=key, bundle=bundle, error=None)
        if _state["bundle"] is None:
            raise ModelUnavailable(_state["error"])
        return _state["bundle"]


def card() -> dict:
    bundle = current()
    out = {k: bundle[k] for k in CARD_FIELDS if k in bundle}
    out["model_types"] = {k: v["type"] for k, v in bundle["models"].items()}
    return out


def predict(record: dict, history: list[dict]) -> dict:
    return runtime.predict(current(), record, history)


def unit(babies: list[dict]) -> dict:
    """Expected census and nurses over the coming shifts, from the babies in the unit now.

    Babies admitted later are not included: the sums cover today's babies only.
    """
    bundle = current()
    results = [runtime.predict(bundle, b["record"], b.get("history") or []) for b in babies]
    ratios = bundle["inputs"]["acuity_ratios"]
    horizon = bundle["models"]["acuity"]["horizon"]
    shifts = []
    for i in range(horizon):
        shifts.append({
            "shifts_ahead": i + 1,
            "hours_ahead": (i + 1) * bundle["settings"]["shift_hours"],
            "expected_census": sum(r["acuity_journey"][i]["p_in_unit"] for r in results),
            "expected_by_ratio": {k: sum(r["acuity_journey"][i]["ratio"][k] for r in results) for k in ratios},
            "expected_nurses": {
                "min": sum(r["acuity_journey"][i]["expected_nurses"]["min"] for r in results),
                "max": sum(r["acuity_journey"][i]["expected_nurses"]["max"] for r in results),
            },
        })
    stay_curve = [sum(r["remaining_stay"]["survival"][h] for r in results)
                  for h in range(len(results[0]["remaining_stay"]["survival"]))] if results else []
    return {
        "model_version": bundle["version"],
        "babies": len(results),
        "shifts": shifts,
        "expected_census_by_shift": stay_curve,
        "note": "Babies already in the unit only; admissions still to come are not included.",
    }
