"""FastAPI application: prediction + analytics API and static frontend hosting."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .data_loader import DATASET, GA_BINS, WEIGHT_BINS
from .nursing import estimate_staffing, schedule_unit
from .predictor import TOTAL_LOS, predict
from . import timeseries

app = FastAPI(
    title="NeoStay – Infant NICU Outcome & Staffing Intelligence",
    description=(
        "Analytics and predictive service for Very Low Birth Weight (VLBW) infant "
        "length-of-stay, disposition, survival and nurse-staffing planning."
    ),
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------
class PredictionRequest(BaseModel):
    weight_g: float = Field(..., ge=200, le=2500, description="Birth weight in grams")
    ga_weeks: float = Field(..., ge=20, le=42, description="Gestational age in weeks")
    center: str = Field("Center 267", description="Center identifier")
    condition: str = Field("stable", description="Admission condition: stable|guarded|serious|critical")
    resp_support: str = Field("room_air", description="room_air|nasal_cannula|cpap|ventilator")
    notes: str = Field("", description="Free-text expert admission notes")


class CensusInfant(BaseModel):
    weight_g: float = Field(..., ge=200, le=2500)
    ga_weeks: float = Field(..., ge=20, le=42)
    condition: str = Field("stable")
    resp_support: str = Field("room_air")


class ScheduleRequest(BaseModel):
    infants: list[CensusInfant] = Field(default_factory=list)
    shifts_per_day: int = Field(2, ge=1, le=4)


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------
@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "center": DATASET.center, "period": DATASET.period}


@app.get("/api/meta")
def meta() -> dict:
    """Bins and available centers for populating the UI."""
    return {
        "center": DATASET.center,
        "period": DATASET.period,
        "centers": ["Center 267", "Center 1"],
        "weight_bins": [
            {"label": b.label, "low": b.low, "high": b.high, "midpoint": b.midpoint}
            for b in WEIGHT_BINS
        ],
        "ga_bins": [
            {"label": b.label, "low": b.low, "high": b.high, "midpoint": b.midpoint}
            for b in GA_BINS
        ],
    }


@app.get("/api/analytics")
def analytics() -> dict:
    """Aggregated distributions for dashboard charts."""

    def series(bins, per_bin):
        out = []
        for b in bins:
            stat = per_bin.get(b.label)
            if stat:
                out.append(
                    {
                        "label": b.label,
                        "n": stat.n,
                        "median": stat.median,
                        "q1": stat.q1,
                        "q3": stat.q3,
                    }
                )
        return out

    surv = DATASET.survival_by_weight
    return {
        "los_by_weight": series(WEIGHT_BINS, DATASET.los_by_weight.get(TOTAL_LOS, {})),
        "los_by_ga": series(GA_BINS, DATASET.los_by_ga.get(TOTAL_LOS, {})),
        "disposition_by_weight": {
            "home": series(WEIGHT_BINS, surv.get("Initial Length of Stay (By Disposition) - Home", {})),
            "transfer": series(WEIGHT_BINS, surv.get("Initial Length of Stay (By Disposition) - Transfer", {})),
            "died": series(WEIGHT_BINS, surv.get("Initial Length of Stay (By Disposition) - Died", {})),
            "all": series(WEIGHT_BINS, surv.get("Initial Length of Stay (By Disposition) - All", {})),
        },
    }


@app.post("/api/predict")
def api_predict(req: PredictionRequest) -> dict:
    try:
        result = predict(req.weight_g, req.ga_weeks)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    los_median = result["length_of_stay"]["blended"]["median"] or 0
    staffing = estimate_staffing(
        req.weight_g, req.ga_weeks, los_median, req.condition, req.resp_support
    )
    result["staffing"] = staffing
    result["center"] = req.center
    result["condition"] = req.condition
    result["resp_support"] = req.resp_support
    return result


@app.post("/api/schedule")
def api_schedule(req: ScheduleRequest) -> dict:
    infants = [i.model_dump() for i in req.infants]
    return schedule_unit(infants, req.shifts_per_day)


# ---------------------------------------------------------------------------
# Time series analysis (over the generated datasets)
# ---------------------------------------------------------------------------
@app.get("/api/ts/available")
def ts_available() -> dict:
    return {"available": timeseries.available()}


@app.get("/api/ts/summary")
def ts_summary() -> dict:
    if not timeseries.available():
        raise HTTPException(status_code=404, detail="Generated data not found. Run datagen/generate.py")
    return timeseries.summary()


@app.get("/api/ts/infants")
def ts_infants() -> dict:
    if not timeseries.available():
        raise HTTPException(status_code=404, detail="Generated data not found.")
    return {"infants": timeseries.representative_infants()}


@app.get("/api/ts/infant/{infant_id}")
def ts_infant(infant_id: str) -> dict:
    data = timeseries.infant_series(infant_id)
    if not data:
        raise HTTPException(status_code=404, detail="Infant not found")
    return data


@app.get("/api/ts/unit-week")
def ts_unit_week() -> dict:
    if not timeseries.available():
        raise HTTPException(status_code=404, detail="Generated data not found.")
    return timeseries.busiest_week()


# ---------------------------------------------------------------------------
# Static frontend (mounted last so /api/* keeps priority)
# ---------------------------------------------------------------------------
FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
