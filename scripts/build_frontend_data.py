#!/usr/bin/env python3
"""
Build the static data bundles consumed by the browser-side engine.

The web app runs 100% client-side (so it can be hosted on GitHub Pages with no
server and no patient data ever leaving the device). This script converts the
source datasets into two small JavaScript files:

  frontend/data/neostay-data.js        aggregated LOS / survival statistics + bins
  frontend/data/neostay-timeseries.js  precomputed hourly timeline payloads

Run it whenever the CSVs in losdata/ or generated_data/ change:

    python3 scripts/build_frontend_data.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.data_loader import DATASET, GA_BINS, WEIGHT_BINS  # noqa: E402

OUT_DIR = ROOT / "frontend" / "data"
OUT_DIR.mkdir(parents=True, exist_ok=True)

PHASES = ["intensive", "intermediate", "convalescent"]


def _bins(bins):
    return [
        {"label": b.label, "low": b.low, "high": b.high, "midpoint": b.midpoint}
        for b in bins
    ]


def _metrics(table):
    return {
        metric: {label: stat.as_dict() for label, stat in per_bin.items()}
        for metric, per_bin in table.items()
    }


def build_dataset() -> None:
    payload = {
        "center": DATASET.center,
        "period": DATASET.period,
        # Single center today; more centers (names TBD) will be added here later.
        "centers": [DATASET.center],
        "weight_bins": _bins(WEIGHT_BINS),
        "ga_bins": _bins(GA_BINS),
        "survival_by_weight": _metrics(DATASET.survival_by_weight),
        "los_by_weight": _metrics(DATASET.los_by_weight),
        "los_by_ga": _metrics(DATASET.los_by_ga),
    }
    out = OUT_DIR / "neostay-data.js"
    out.write_text(
        "window.NEOSTAY_DATA = " + json.dumps(payload, separators=(",", ":")) + ";\n"
    )
    print(f"wrote {out.relative_to(ROOT)} ({out.stat().st_size / 1024:.1f} KB)")


def build_timeseries() -> None:
    if not (ROOT / "generated_data" / "infants.csv").exists():
        print("generated_data/ not found - skipping timeline bundle")
        return

    try:
        from app import timeseries  # noqa: E402  (needs pandas)
    except ImportError:
        print("pandas not installed - skipping timeline bundle (existing bundle kept)")
        return

    infants = timeseries.representative_infants()
    series = {}
    for inf in infants:
        data = timeseries.infant_series(inf["infant_id"])
        pts = data["points"]
        # Downsample long stays so the bundle stays lightweight on mobile:
        # hourly resolution up to 14 days, then every 3 hours.
        step_pts = [p for p in pts if p["hour_of_stay"] <= 336 or p["hour_of_stay"] % 3 == 0]
        series[inf["infant_id"]] = {
            "infant": data["infant"],
            "pts": [
                [
                    p["hour_of_stay"],
                    PHASES.index(p["care_phase"]) if p["care_phase"] in PHASES else -1,
                    round(p["nurses_required"], 3),
                ]
                for p in step_pts
            ],
        }

    payload = {
        "summary": timeseries.summary(),
        "infants": infants,
        "series": series,
        "week": timeseries.busiest_week(),
        "phases": PHASES,
    }
    out = OUT_DIR / "neostay-timeseries.js"
    out.write_text(
        "window.NEOSTAY_TS = " + json.dumps(payload, separators=(",", ":")) + ";\n"
    )
    print(f"wrote {out.relative_to(ROOT)} ({out.stat().st_size / 1024:.1f} KB)")


if __name__ == "__main__":
    build_dataset()
    build_timeseries()
