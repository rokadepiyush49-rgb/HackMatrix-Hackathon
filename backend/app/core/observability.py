"""Logging, request correlation and tracing.

* Every request gets an ``X-Request-ID`` (the caller's, if it sent a sane one) that is echoed back,
  put on every log line and attached to the trace, so a user-reported ID finds the exact request.
* Logs are one JSON object per line in staging/prod — CloudWatch/Loki index fields, not prose.
* Traces use OpenTelemetry and export over OTLP to whatever collector the environment runs
  (ADOT on EKS → X-Ray/Tempo). Nothing is exported unless OTEL_EXPORTER_OTLP_ENDPOINT is set,
  so local runs and tests have zero overhead.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import uuid
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.core.config import get_settings

request_id: ContextVar[str] = ContextVar("request_id", default="-")
_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
log = logging.getLogger("sutra.access")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out = {"ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"), "level": record.levelname,
               "logger": record.name, "msg": record.getMessage(), "request_id": request_id.get()}
        for key in ("method", "path", "status", "duration_ms", "client"):
            if hasattr(record, key):
                out[key] = getattr(record, key)
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        return json.dumps(out, ensure_ascii=False)


def configure_logging() -> None:
    s = get_settings()
    handler = logging.StreamHandler()
    if s.log_json:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-5s %(name)s · %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(s.log_level.upper())
    # uvicorn's own access log is replaced by RequestContext below (it lacks the request ID).
    logging.getLogger("uvicorn.access").handlers.clear()
    logging.getLogger("uvicorn.access").propagate = False


class RequestContext(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        incoming = request.headers.get("x-request-id", "")
        rid = incoming if _SAFE_ID.match(incoming) else uuid.uuid4().hex
        token = request_id.set(rid)
        start = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["X-Request-ID"] = rid
            return response
        finally:
            if not request.url.path.startswith("/health"):
                log.info("%s %s %s", request.method, request.url.path, status,
                         extra={"method": request.method, "path": request.url.path, "status": status,
                                "duration_ms": round((time.perf_counter() - start) * 1000, 1),
                                "client": request.client.host if request.client else None})
            request_id.reset(token)


def configure_tracing(app, engine) -> bool:
    """Instrument FastAPI and SQLAlchemy if an OTLP endpoint is configured. Returns True when on."""
    if not os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
        return False
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    s = get_settings()
    resource = Resource.create({"service.name": os.environ.get("OTEL_SERVICE_NAME", "sutra-api"),
                                "deployment.environment": s.env})
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app, excluded_urls="health")
    SQLAlchemyInstrumentor().instrument(engine=engine)
    return True
