"""SUTRA API — FastAPI application factory."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.middleware.base import BaseHTTPMiddleware

from app.api import router as api_router
from app.core.config import get_settings
from app.core.limiter import limiter
from app.core.observability import RequestContext, configure_logging, configure_tracing

DESCRIPTION = """
**SUTRA — privilege-to-payment intelligence.**

Rebuilds time-ordered chains from an employee's privileged access to money movement,
tests every access for a legitimate reason (*Alibi*), and presents each alert as a
prosecution-and-defence argument with graded evidence (*Brief*).

All data served by this instance is synthetic (Kestrel-Sim).
"""


class SecurityHeaders(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Cache-Control", "no-store")
        return response


def create_app() -> FastAPI:
    configure_logging()
    s = get_settings()
    app = FastAPI(
        title="SUTRA API",
        version="0.1.0",
        description=DESCRIPTION,
        # Interactive docs are a development aid; production exposes the OpenAPI schema to nobody.
        docs_url=None if s.env == "prod" else "/docs",
        redoc_url=None,
        openapi_url=None if s.env == "prod" else "/openapi.json",
    )
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SecurityHeaders)
    app.add_middleware(RequestContext)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_settings().cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api_router, prefix="/api/v1")

    @app.get("/health", tags=["meta"])
    @app.get("/health/live", tags=["meta"])
    def live() -> dict:
        """Liveness: the process answers. Never touches dependencies, so a DB blip can't restart pods."""
        return {"status": "ok"}

    @app.get("/health/ready", tags=["meta"])
    def ready() -> JSONResponse:
        """Readiness: take traffic only when Postgres answers and the model artifacts are present."""
        from sqlalchemy import text

        from app.core.db import engine

        checks: dict[str, str] = {}
        try:
            with engine.connect() as c:
                c.execute(text("SELECT 1"))
            checks["database"] = "ok"
        except Exception as e:  # noqa: BLE001 — any failure means not ready
            checks["database"] = f"error: {type(e).__name__}"
        artifacts = get_settings().artifacts_path
        checks["models"] = "ok" if (artifacts / "chain_classifier.joblib").exists() else "missing"
        ok = all(v == "ok" for v in checks.values())
        return JSONResponse({"status": "ok" if ok else "degraded", "checks": checks}, status_code=200 if ok else 503)

    from app.core.db import engine

    configure_tracing(app, engine)
    return app


app = create_app()
