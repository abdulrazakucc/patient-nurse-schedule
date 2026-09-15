"""
NeoStay server: the web application, its data and the JSON API behind sign-in.

One process serves everything on one port:

* ``/``            the web pages. They hold no data: each page asks who is signed
                   in, shows the sign-in screen if nobody is, and only then loads
                   the data and the engine.
* ``/data/...``    the data bundles the pages compute from -- signed-in users only.
* ``/api/...``     the JSON API -- signed-in users only, apart from ``/api/health``
                   and the sign-in routes.
* ``/docs``        interactive API documentation, only with ``NEOSTAY_EXPOSE_DOCS``.

Run it from ``backend/``::

    uvicorn app.main:app --port 8000
"""
from __future__ import annotations

import hmac
from urllib.parse import urlsplit

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import auth, config, timeseries
from .acuity_tool import TOOL as ACUITY_TOOL
from .data_loader import DATASET, GA_BINS, WEIGHT_BINS
from .nursing import NURSE_LEVELS, build_roster, estimate_staffing, schedule_unit
from .predictor import TOTAL_LOS, predict

__version__ = "2.0.0"

# The same policy the pages declare in their own meta tag, plus the protections
# only a response header can give.
PAGE_POLICY = (
    "default-src 'self'; script-src 'self'; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; "
    "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
)


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------
class PredictionRequest(BaseModel):
    weight_g: float = Field(..., ge=200, le=2500, description="Birth weight in grams")
    ga_weeks: float = Field(..., ge=20, le=42, description="Gestational age in weeks")
    center: str = Field("Center 1", description="Center identifier")
    condition: str = Field("stable", description="Admission condition: stable|guarded|serious|critical")
    resp_support: str = Field("room_air", description="room_air|nasal_cannula|cpap|ventilator")
    notes: str = Field("", description="Free-text expert admission notes")


class CensusInfant(BaseModel):
    weight_g: float = Field(..., ge=200, le=2500)
    ga_weeks: float = Field(..., ge=20, le=42)
    condition: str = Field("stable")
    resp_support: str = Field("room_air")
    findings: list[str] = Field(
        default_factory=list,
        description="Finding ids from the acuity tool (GET /api/acuity-tool). When "
        "present they set the ratio and minimum nurse level instead of the model.",
    )


class ScheduleRequest(BaseModel):
    infants: list[CensusInfant] = Field(default_factory=list)
    shifts_per_day: int = Field(2, ge=1, le=4)
    available_nurses: dict[int, int] | None = Field(
        None,
        description=(
            "Nurses in hand across the whole day, keyed by competency level "
            "(1-4), e.g. {\"1\": 4, \"2\": 6, \"3\": 6, \"4\": 4}. When supplied, "
            "the response includes a 24-hour roster and any uncovered infants."
        ),
    )


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------
api = APIRouter()


@api.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@api.get("/api/meta")
def meta() -> dict:
    """Bins and available centers for populating the UI."""
    return {
        "center": DATASET.center,
        "period": DATASET.period,
        # Single center today; more centers (names TBD) will be added here later.
        "centers": [DATASET.center],
        "weight_bins": [
            {"label": b.label, "low": b.low, "high": b.high, "midpoint": b.midpoint}
            for b in WEIGHT_BINS
        ],
        "ga_bins": [
            {"label": b.label, "low": b.low, "high": b.high, "midpoint": b.midpoint}
            for b in GA_BINS
        ],
        "nurse_levels": NURSE_LEVELS,
    }


@api.get("/api/analytics")
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


@api.get("/api/acuity-tool")
def api_acuity_tool() -> dict:
    """Dr. Altaf's nurse-skills classifier, with the finding ids /api/schedule accepts."""
    return ACUITY_TOOL


@api.post("/api/predict")
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


@api.post("/api/schedule")
def api_schedule(req: ScheduleRequest) -> dict:
    infants = [i.model_dump() for i in req.infants]
    result = schedule_unit(infants, req.shifts_per_day)
    if req.available_nurses:
        result["roster"] = build_roster(
            result["infants"], req.available_nurses, req.shifts_per_day
        )
    return result


# ---------------------------------------------------------------------------
# Time series analysis (over the generated datasets)
# ---------------------------------------------------------------------------
@api.get("/api/ts/available")
def ts_available() -> dict:
    return {"available": timeseries.available()}


@api.get("/api/ts/summary")
def ts_summary() -> dict:
    if not timeseries.available():
        raise HTTPException(status_code=404, detail="Generated data not found. Run datagen/generate.py")
    return timeseries.summary()


@api.get("/api/ts/infants")
def ts_infants() -> dict:
    if not timeseries.available():
        raise HTTPException(status_code=404, detail="Generated data not found.")
    return {"infants": timeseries.representative_infants()}


@api.get("/api/ts/infant/{infant_id}")
def ts_infant(infant_id: str) -> dict:
    data = timeseries.infant_series(infant_id)
    if not data:
        raise HTTPException(status_code=404, detail="Infant not found")
    return data


@api.get("/api/ts/unit-week")
def ts_unit_week() -> dict:
    if not timeseries.available():
        raise HTTPException(status_code=404, detail="Generated data not found.")
    return timeseries.busiest_week()


# ---------------------------------------------------------------------------
# The application
# ---------------------------------------------------------------------------
def _needs_session(path: str) -> bool:
    """Data and API calls need a signed-in user; the pages themselves do not."""
    if path.startswith("/api/"):
        return path not in auth.PUBLIC_API
    return path.startswith("/data/")


def _web_origins(values: list[str]) -> list[str]:
    clean = []
    for value in values:
        parts = urlsplit(value)
        if (
            parts.scheme not in {"http", "https"}
            or not parts.netloc
            or parts.username
            or parts.password
            or parts.path not in {"", "/"}
            or parts.query
            or parts.fragment
        ):
            raise RuntimeError(f"Invalid NEOSTAY_CORS_ORIGINS entry: {value!r}")
        clean.append(value.rstrip("/"))
    return clean


def check_settings() -> None:
    """Refuse to start with settings that would leave the data unprotected."""
    if config.ENVIRONMENT not in {"development", "test", "production"}:
        raise RuntimeError("NEOSTAY_ENV must be development, test or production")
    if config.AUTH_MODE not in {"off", "password", "proxy"}:
        raise RuntimeError("NEOSTAY_AUTH_MODE must be password, proxy or off")
    if any("://" in host or "/" in host for host in config.TRUSTED_HOSTS):
        raise RuntimeError("NEOSTAY_TRUSTED_HOSTS entries must be host names, without schemes or paths")
    if config.ENVIRONMENT == "production" and "*" in config.TRUSTED_HOSTS:
        raise RuntimeError("Production does not allow a wildcard in NEOSTAY_TRUSTED_HOSTS")
    if config.AUTH_MODE == "proxy" and (
        not config.AUTH_USER_HEADER or len(config.PROXY_SECRET) < 32
    ):
        raise RuntimeError("Proxy sign-in requires a user header and a 32+ character proxy secret")
    if config.ENVIRONMENT == "production" and config.AUTH_MODE == "off":
        raise RuntimeError("Production requires sign-in: NEOSTAY_AUTH_MODE=password or proxy")
    if (
        config.ENVIRONMENT == "production"
        and config.AUTH_MODE == "password"
        and len(config.SESSION_SECRET) < 32
    ):
        raise RuntimeError("Password sign-in in production requires a 32+ character session secret")


def create_app() -> FastAPI:
    """Build the application. A factory, so tests can build one per configuration."""
    check_settings()
    origins = _web_origins(config.CORS_ORIGINS)

    app = FastAPI(
        title="NeoStay – Infant NICU Outcome & Staffing Intelligence",
        description=(
            "Analytics and predictive service for Very Low Birth Weight (VLBW) infant "
            "length-of-stay, disposition, survival and nurse-staffing planning. "
            "Every data route requires a signed-in session."
        ),
        version=__version__,
        docs_url="/docs" if config.EXPOSE_DOCS else None,
        redoc_url=None,
        openapi_url="/openapi.json" if config.EXPOSE_DOCS else None,
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=config.TRUSTED_HOSTS)
    app.add_middleware(GZipMiddleware, minimum_size=1000)

    def secured(response: Response, path: str) -> Response:
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if path not in {"/docs", "/openapi.json"}:
            response.headers["Content-Security-Policy"] = PAGE_POLICY
        if _needs_session(path) or path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        if config.ENVIRONMENT == "production":
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

    @app.middleware("http")
    async def require_sign_in(request, call_next):
        path = request.url.path
        if config.AUTH_MODE == "proxy" and path != "/api/health":
            supplied = request.headers.get("X-NeoStay-Proxy-Secret", "")
            user = request.headers.get(config.AUTH_USER_HEADER, "").strip()
            if not user or not hmac.compare_digest(supplied, config.PROXY_SECRET):
                return secured(
                    JSONResponse({"detail": "Authentication required"}, status_code=401), path
                )
        if (
            config.AUTH_MODE == "password"
            and _needs_session(path)
            and auth.current_user(request) is None
        ):
            return secured(JSONResponse({"detail": "Sign in required"}, status_code=401), path)
        return secured(await call_next(request), path)

    # Same-origin pages need no CORS. It is only for a browser app on another
    # site, and then only for the origins named -- never a wildcard.
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=True,
            allow_methods=["GET", "POST"],
            allow_headers=["Content-Type"],
        )

    app.include_router(auth.router)
    app.include_router(api)

    # Mounted last, so every /api route above resolves first.
    if config.FRONTEND_DIR.is_dir():
        app.mount("/", StaticFiles(directory=config.FRONTEND_DIR, html=True), name="frontend")
    return app


# The instance uvicorn imports: `uvicorn app.main:app`.
app = create_app()
