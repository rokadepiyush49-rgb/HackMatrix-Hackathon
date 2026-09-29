"""SUTRA API — FastAPI application factory."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.middleware.base import BaseHTTPMiddleware

from app.api import router as api_router
from app.core.config import get_settings
from app.core.limiter import limiter

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
    app = FastAPI(
        title="SUTRA API",
        version="0.1.0",
        description=DESCRIPTION,
    )
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SecurityHeaders)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_settings().cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api_router, prefix="/api/v1")

    @app.get("/health", tags=["meta"])
    def health() -> dict:
        return {"status": "ok"}

    return app


app = create_app()
