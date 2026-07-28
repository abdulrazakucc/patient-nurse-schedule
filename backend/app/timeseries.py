"""
Time series analysis over the generated datasets.

Reads the synthetic CSVs in ``generated_data/`` and exposes aggregations for the
staffing-timeline page: representative infant journeys, a busy sample week of unit
staffing, and summary profiles (average nurse demand by hour of day, care-phase mix).

Files are loaded once (lazily) and cached in memory.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parents[2] / "generated_data"


@lru_cache(maxsize=1)
def _infants() -> pd.DataFrame:
    df = pd.read_csv(DATA_DIR / "infants.csv")
    df["admission_datetime"] = pd.to_datetime(df["admission_datetime"])
    df["discharge_datetime"] = pd.to_datetime(df["discharge_datetime"])
    return df


@lru_cache(maxsize=1)
def _infant_hourly() -> pd.DataFrame:
    df = pd.read_csv(DATA_DIR / "infant_hourly_acuity.csv")
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df


@lru_cache(maxsize=1)
def _unit_hourly() -> pd.DataFrame:
    df = pd.read_csv(DATA_DIR / "unit_hourly_staffing.csv")
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df


def available() -> bool:
    return (DATA_DIR / "infants.csv").exists()


def representative_infants(limit: int = 30) -> list[dict]:
    """A varied selection of infants: for each band, those closest to that band's
    typical (median) length of stay, so the journeys shown are realistic rather
    than extreme outliers."""
    df = _infants().copy()
    picks = []
    for band, grp in df.groupby("birth_weight_band"):
        med = grp["length_of_stay_days"].median()
        grp = grp.assign(_d=(grp["length_of_stay_days"] - med).abs()).sort_values("_d")
        picks.append(grp.head(3))
    out = pd.concat(picks).sort_values("length_of_stay_days", ascending=False).head(limit)
    cols = [
        "infant_id", "birth_weight_g", "gestational_age_weeks", "birth_weight_band",
        "length_of_stay_days", "disposition", "admission_condition", "respiratory_support",
        "required_nurse_level",
    ]
    return out[cols].to_dict("records")


def infant_series(infant_id: str) -> dict:
    inf = _infants()
    row = inf[inf["infant_id"] == infant_id]
    if row.empty:
        return {}
    meta = row.iloc[0]
    ts = _infant_hourly()
    series = ts[ts["infant_id"] == infant_id].sort_values("hour_of_stay")
    return {
        "infant": {
            "infant_id": infant_id,
            "birth_weight_g": int(meta["birth_weight_g"]),
            "gestational_age_weeks": int(meta["gestational_age_weeks"]),
            "birth_weight_band": meta["birth_weight_band"],
            "length_of_stay_days": float(meta["length_of_stay_days"]),
            "disposition": meta["disposition"],
            "admission_condition": meta["admission_condition"],
            "respiratory_support": meta["respiratory_support"],
            "required_nurse_level": int(meta.get("required_nurse_level", 1)),
        },
        "points": [
            {
                "hour_of_stay": int(r.hour_of_stay),
                "day_of_stay": float(r.day_of_stay),
                "care_phase": r.care_phase,
                "nurses_required": float(r.nurses_required),
            }
            for r in series.itertuples()
        ],
    }


def busiest_week() -> dict:
    """Return the 7-day window with the highest average census, hour by hour."""
    df = _unit_hourly()
    daily = df.set_index("timestamp")["census"].resample("D").mean()
    if daily.empty:
        return {"start": None, "points": []}
    # Rolling 7-day sum to find the busiest week.
    roll = daily.rolling(7).mean()
    end = roll.idxmax()
    start = end - pd.Timedelta(days=6)
    window = df[(df["timestamp"] >= start) & (df["timestamp"] < end + pd.Timedelta(days=1))]
    window = window.sort_values("timestamp")
    return {
        "start": str(start.date()),
        "end": str(end.date()),
        "points": [
            {
                "timestamp": r.timestamp.strftime("%Y-%m-%d %H:%M"),
                "census": int(r.census),
                "nurse_demand": float(r.nurse_demand),
                "nurses_on_duty": int(r.nurses_on_duty),
                "shift": r.shift,
            }
            for r in window.itertuples()
        ],
    }


def summary() -> dict:
    inf = _infants()
    unit = _unit_hourly()
    hourly_prof = (
        unit.groupby("hour")["nurse_demand"].mean().round(2).reindex(range(24)).fillna(0)
    )
    phase_mix = _infant_hourly()["care_phase"].value_counts(normalize=True).mul(100).round(1)
    return {
        "total_infants": int(len(inf)),
        "total_nurses": int(pd.read_csv(DATA_DIR / "nurses.csv").shape[0]),
        "avg_census": round(float(unit["census"].mean()), 2),
        "peak_census": int(unit["census"].max()),
        "avg_nurses_on_duty": round(float(unit["nurses_on_duty"].mean()), 2),
        "hourly_demand_profile": [
            {"hour": h, "avg_nurse_demand": float(hourly_prof.loc[h])} for h in range(24)
        ],
        "care_phase_mix": {k: float(v) for k, v in phase_mix.items()},
        "disposition_mix": {
            k: int(v) for k, v in inf["disposition"].value_counts().items()
        },
    }
