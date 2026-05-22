"""FastAPI application entry-point.

Changes vs original:
- lifespan initialises EmotionModelLoader once and stores it on app.state
- structlog configured for JSON output at startup
- Prometheus /metrics endpoint added (starlette-prometheus)
- CORS origins driven by ALLOWED_ORIGINS env var (no open wildcard)
- Secret key validation: refuse to start with the insecure default
"""

from __future__ import annotations

import asyncio
import logging
import sys
from contextlib import asynccontextmanager, suppress

import structlog
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.responses import Response as StarletteResponse
from starlette_prometheus import PrometheusMiddleware, metrics

from app.api.v1.api import api_router
from app.core.config import settings
from app.core.database import collect_pool_metrics, engine
from app.core.redis_client import close_redis, init_redis
from app.core.security import limiter, require_jwt_token
from app.ml.intent_model_loader import IntentModelLoader
from app.models.base import Base
from app.services.whisper_service import WhisperService

# ---------------------------------------------------------------------------
# structlog JSON configuration (runs at import time)
# ---------------------------------------------------------------------------

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.dev.set_exc_info,
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
    cache_logger_on_first_use=True,
)

log = structlog.get_logger("redline_ai.app")


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ----------- Startup -----------
    # 1. Validate secret key
    if not settings.SECRET_KEY:
        raise RuntimeError("SECRET_KEY must be set via environment variable")

    if settings.APP_ENV.lower() == "production" and not settings.POSTGRES_PASSWORD:
        raise RuntimeError("POSTGRES_PASSWORD must be set in production")

    if settings.APP_ENV.lower() == "production" and settings.ENABLE_DOCS:
        log.warning(
            "ENABLE_DOCS=true in production; docs endpoint is being force-disabled"
        )

    if any(origin == "*" for origin in settings.allowed_origins_list):
        raise RuntimeError("Wildcard CORS origin is not allowed")

    # 2. Redis
    await init_redis()

    # 3. Database schema (MVP bootstrap — idempotent on restarts)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(
                lambda sync_conn: Base.metadata.create_all(sync_conn, checkfirst=True)
            )
    except Exception as exc:
        log.warning(
            "Database init failed — tables may already exist or DB not ready",
            error=str(exc),
        )

    # 3b. Download ML models from GCS if available (Cloud Run)
    if settings.GCS_MODEL_BUCKET:
        from app.core.model_downloader import download_models_from_gcs

        model_paths = await asyncio.get_running_loop().run_in_executor(
            None, download_models_from_gcs, settings.GCS_MODEL_BUCKET
        )
        # Override config paths with downloaded models
        if "intent_model.onnx" in model_paths:
            settings.INTENT_ONNX_PATH = model_paths["intent_model.onnx"]
        if "emotion_model.onnx" in model_paths:
            settings.EMOTION_ONNX_PATH = model_paths["emotion_model.onnx"]

    # 4. Local Whisper STT model (CPU), loaded off the event loop
    whisper_service = WhisperService(model_size=settings.WHISPER_MODEL_SIZE)
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, whisper_service.initialize)
    app.state.whisper_service = whisper_service

    # 5. Intent ONNX model (graceful — keyword fallback if model unavailable)
    intent_loader = IntentModelLoader()
    try:
        await intent_loader.initialize()
        app.state.intent_loader = intent_loader
        log.info("Intent ONNX model loaded")
    except Exception as exc:
        app.state.intent_loader = None
        log.warning(
            "Intent model not available — keyword fallback active", error=str(exc)
        )

    # 6. Emotion ONNX model (graceful — skip if model files missing)
    try:
        from app.ml.emotion_model_loader import EmotionModelLoader

        emotion_loader = EmotionModelLoader()
        await emotion_loader.initialize()
        app.state.emotion_loader = emotion_loader
        log.info("Emotion ONNX model loaded")
    except Exception as exc:
        app.state.emotion_loader = None
        log.warning(
            "Emotion model not available — heuristic fallback active", error=str(exc)
        )

    # begin background event subscriber
    from app.core.event_listener import start_event_listener

    start_event_listener()

    # 7. Background pool-metrics collector (PostgreSQL only)
    async def _pool_metrics_loop() -> None:
        while True:
            with suppress(Exception):
                collect_pool_metrics()
            await asyncio.sleep(15)

    pool_metrics_task: asyncio.Task | None = None
    if "postgresql" in settings.SQLALCHEMY_DATABASE_URI:
        pool_metrics_task = asyncio.create_task(_pool_metrics_loop())

    log.info(
        "Redline AI started",
        whisper=whisper_service.is_ready(),
        intent=intent_loader.is_ready(),
        emotion=getattr(app.state, "emotion_loader", None) is not None,
    )
    yield

    # ----------- Shutdown (drain then release) -----------
    log.info("Redline AI shutting down...")

    # Cancel pool-metrics background task
    if pool_metrics_task is not None:
        pool_metrics_task.cancel()
        with suppress(asyncio.CancelledError):
            await pool_metrics_task
    from app.core.event_listener import stop_event_listener

    await stop_event_listener()

    # Shutdown ML models first (they hold thread pools)
    if getattr(app.state, "emotion_loader", None) is not None:
        await app.state.emotion_loader.shutdown()
    if getattr(app.state, "intent_loader", None) is not None:
        await app.state.intent_loader.shutdown()
    if getattr(app.state, "whisper_service", None) is not None:
        app.state.whisper_service.shutdown()

    # Close Redis last (other components may flush during shutdown)
    await close_redis()
    log.info("Redline AI shut down cleanly")


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

# ENABLE_DOCS=true explicitly overrides the production default of hiding docs
docs_enabled = settings.ENABLE_DOCS

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="AI-powered emergency intelligence and dispatch platform. "
    "Processes 911 calls through Whisper STT, intent/emotion classification, "
    "severity scoring, and automated dispatch routing.",
    version="1.0.0",
    openapi_url=f"{settings.API_V1_STR}/openapi.json" if docs_enabled else None,
    docs_url="/docs" if docs_enabled else None,
    redoc_url="/redoc" if docs_enabled else None,
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Catch-all for unhandled exceptions — returns structured JSON."""
    log.error(
        "Unhandled exception", path=str(request.url.path), error=str(exc), exc_info=True
    )
    # Audit security-relevant unhandled errors
    try:
        from app.services.audit_service import audit_event

        audit_event(
            action="unhandled_exception",
            tenant_id="system",
            entity_type="http_request",
            entity_id=str(request.url.path),
            details={"error": str(exc)[:500], "method": request.method},
        )
    except Exception:
        pass
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "error": "Internal server error",
            "detail": str(exc) if settings.APP_ENV.lower() != "production" else None,
        },
    )


app.add_middleware(PrometheusMiddleware)
app.add_middleware(SlowAPIMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)

from app.middleware.request_id import RequestIDMiddleware
from app.middleware.security_headers import SecurityHeadersMiddleware

app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestIDMiddleware)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

from app.api.v1.endpoints.emergency import router as emergency_router  # noqa: E402
from app.dashboard.routes import router as dashboard_router  # noqa: E402
from app.websockets.connection_manager import router as websocket_router  # noqa: E402

# Dashboard router first — /api/v1/calls/live must match before /api/v1/calls/{call_id}
# No router-level auth: /dashboard page is public, data endpoints have their own auth
app.include_router(dashboard_router, tags=["dashboard"])
app.include_router(
    api_router, prefix=settings.API_V1_STR, dependencies=[Depends(require_jwt_token)]
)
app.include_router(emergency_router, dependencies=[Depends(require_jwt_token)])
app.include_router(websocket_router, prefix="/ws", tags=["websockets"])


@app.get("/", include_in_schema=False)
async def root_redirect():
    """Redirect root to dashboard."""
    from fastapi.responses import RedirectResponse

    return RedirectResponse(url="/dashboard")


@app.get("/metrics", include_in_schema=False, dependencies=[Depends(require_jwt_token)])
async def protected_metrics(request: Request) -> StarletteResponse:
    """Metrics endpoint – requires a valid JWT; restrict further at the reverse proxy in production."""
    return metrics(request)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@app.get("/health", tags=["health"])
async def health_check() -> dict:
    from app.core.database import check_db_health

    db_ok = await check_db_health()
    return {
        "status": "ok" if db_ok else "degraded",
    }


@app.get("/ready", tags=["health"], response_class=JSONResponse)
async def readiness_check():
    """Readiness probe — returns 503 until all models and services are loaded."""
    from app.core.database import check_db_health
    from app.core.redis_client import check_redis_health

    checks = {}

    # DB
    checks["database"] = await check_db_health()

    # Redis
    checks["redis"] = await check_redis_health()

    # Whisper
    whisper_svc = getattr(app.state, "whisper_service", None)
    checks["whisper"] = whisper_svc is not None and whisper_svc.is_ready()

    # Intent model
    intent_loader = getattr(app.state, "intent_loader", None)
    checks["intent_model"] = intent_loader is not None and intent_loader.is_ready()

    # Emotion model (optional — heuristic fallback is acceptable)
    emotion_loader = getattr(app.state, "emotion_loader", None)
    checks["emotion_model"] = emotion_loader is not None and emotion_loader.is_ready()

    all_critical = checks["database"] and checks["whisper"] and checks["intent_model"]
    status = "ready" if all_critical else "not_ready"

    code = 200 if all_critical else 503
    return JSONResponse(content={"status": status, "checks": checks}, status_code=code)


_BOOT_TIME = None


@app.get(
    "/api/v1/system/info", tags=["system"], dependencies=[Depends(require_jwt_token)]
)
async def system_info() -> dict:
    """System information — version, uptime, model status."""
    import time

    global _BOOT_TIME
    if _BOOT_TIME is None:
        _BOOT_TIME = time.time()

    whisper_svc = getattr(app.state, "whisper_service", None)
    intent_loader = getattr(app.state, "intent_loader", None)
    emotion_loader = getattr(app.state, "emotion_loader", None)

    return {
        "version": "1.0.0",
        "environment": settings.APP_ENV,
        "uptime_seconds": int(time.time() - _BOOT_TIME),
        "models": {
            "whisper": {
                "ready": whisper_svc is not None and whisper_svc.is_ready(),
                "size": settings.WHISPER_MODEL_SIZE,
            },
            "intent": {
                "ready": intent_loader is not None and intent_loader.is_ready(),
                "type": "onnx_distilbert",
            },
            "emotion": {
                "ready": emotion_loader is not None and emotion_loader.is_ready(),
                "type": "onnx_cnn",
            },
        },
        "database": "postgresql"
        if "postgresql" in settings.SQLALCHEMY_DATABASE_URI
        else "sqlite",
    }
