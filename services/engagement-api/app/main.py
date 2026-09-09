from __future__ import annotations

import asyncio
import logging
import re
import secrets
import time
import uuid
from collections.abc import Mapping
from typing import Literal

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import __version__
from app.config import Settings, load_settings
from app.logging_config import configure_logging, request_id_context, trace_id_context
from app.problems import problem_response
from app.readiness import REQUIRED_DEPENDENCIES, DependencyProbe, NotConfiguredProbe
from app.request_limits import RequestBodyLimitMiddleware

REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
TRACEPARENT_PATTERN = re.compile(
    r"^[\da-f]{2}-([\da-f]{32})-([\da-f]{16})-[\da-f]{2}$",
    flags=re.IGNORECASE,
)


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"]


def _problem(request: Request, status: int, code: str, title: str, *, retryable=False) -> JSONResponse:
    return problem_response(request.state.trace_id, status, code, title, retryable=retryable)


def _route_template(request: Request) -> str:
    route = request.scope.get("route")
    template = getattr(route, "path", None)
    return template if isinstance(template, str) and template.startswith("/") else "<unmatched>"


def _correlation_ids(request: Request) -> tuple[str, str]:
    candidate = request.headers.get("X-Request-Id", "")
    request_id = candidate if REQUEST_ID_PATTERN.fullmatch(candidate) else str(uuid.uuid4())
    traceparent = request.headers.get("traceparent", "")
    match = TRACEPARENT_PATTERN.fullmatch(traceparent)
    valid_traceparent = (
        match
        and traceparent[:2].lower() != "ff"
        and match.group(1) != "0" * 32
        and match.group(2) != "0" * 16
    )
    trace_id = match.group(1).lower() if valid_traceparent else secrets.token_hex(16)
    return request_id, trace_id


def create_app(
    settings: Settings | None = None,
    probes: Mapping[str, DependencyProbe] | None = None,
    *,
    probe_timeout_seconds: float = 2.0,
    max_request_body_bytes: int = 1_048_576,
) -> FastAPI:
    if not 0 < probe_timeout_seconds <= 30:
        raise ValueError("probe_timeout_seconds must be greater than zero and at most 30")
    if max_request_body_bytes < 1:
        raise ValueError("max_request_body_bytes must be positive")
    config = settings or load_settings()
    configure_logging(config.log_level)
    logger = logging.getLogger("engagement.api")
    provided_probes = dict(probes or {})
    unknown_probes = set(provided_probes) - set(REQUIRED_DEPENDENCIES)
    if unknown_probes:
        raise ValueError("unknown readiness dependency")
    readiness_probes = {
        name: provided_probes.get(name, NotConfiguredProbe()) for name in REQUIRED_DEPENDENCIES
    }

    app = FastAPI(
        title=config.app_name,
        version=__version__,
        docs_url=None if config.environment == "production" else "/docs",
        redoc_url=None,
        openapi_url=None if config.environment == "production" else "/openapi.json",
    )
    app.state.settings = config
    app.state.readiness_probes = readiness_probes

    app.add_middleware(TrustedHostMiddleware, allowed_hosts=config.trusted_host_list)
    if config.cors_origin_list:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=config.cors_origin_list,
            allow_credentials=False,
            allow_methods=["GET"],
            allow_headers=["Content-Type", "X-Request-Id", "traceparent"],
            expose_headers=["X-Request-Id", "traceparent"],
        )
    app.add_middleware(RequestBodyLimitMiddleware, max_bytes=max_request_body_bytes)

    @app.exception_handler(StarletteHTTPException)
    async def normalize_http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        if exc.status_code == 404:
            return _problem(request, 404, "NOT_FOUND", "Resource not found")
        if exc.status_code == 405:
            return _problem(request, 405, "METHOD_NOT_ALLOWED", "Method not allowed")
        return _problem(request, 400, "INVALID_REQUEST", "Invalid request")

    @app.exception_handler(RequestValidationError)
    async def normalize_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        del exc
        return _problem(request, 400, "VALIDATION_FAILED", "Request validation failed")

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        started = time.perf_counter()
        request_id, trace_id = _correlation_ids(request)
        request.state.request_id = request_id
        request.state.trace_id = trace_id
        request_token = request_id_context.set(request_id)
        trace_token = trace_id_context.set(trace_id)
        try:
            if request.url.hostname not in config.trusted_host_list:
                response = _problem(request, 400, "INVALID_REQUEST", "Invalid request")
            else:
                response = await call_next(request)
        except Exception:
            logger.exception("unhandled_request_error")
            response = _problem(
                request,
                500,
                "INTERNAL_ERROR",
                "Internal server error",
            )
        finally:
            request_id_context.reset(request_token)
            trace_id_context.reset(trace_token)

        response.headers["X-Request-Id"] = request_id
        response.headers["traceparent"] = f"00-{trace_id}-{secrets.token_hex(8)}-01"
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        logger.info(
            "request_completed",
            extra={
                "request_id": request_id,
                "trace_id": trace_id,
                "method": request.method,
                "route": _route_template(request),
                "status_code": response.status_code,
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            },
        )
        return response

    @app.get("/health", tags=["Operations"], response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(status="ok")

    @app.get("/ready", tags=["Operations"], response_model=HealthResponse)
    async def ready(request: Request) -> JSONResponse:
        async def check_dependency(name: str, probe: DependencyProbe) -> tuple[str, bool, str]:
            try:
                result = await asyncio.wait_for(probe.check(), timeout=probe_timeout_seconds)
                return name, result.ready is True, "ready" if result.ready is True else "unavailable"
            except TimeoutError:
                return name, False, "timeout"
            except Exception:
                logger.exception("readiness_probe_failed", extra={"dependency": name})
                return name, False, "error"

        checks = await asyncio.gather(
            *(check_dependency(name, probe) for name, probe in readiness_probes.items())
        )
        is_ready = len(checks) == len(REQUIRED_DEPENDENCIES) and all(ready for _, ready, _ in checks)
        if is_ready:
            return JSONResponse({"status": "ok"})
        for name, dependency_ready, outcome in checks:
            if not dependency_ready:
                logger.warning(
                    "readiness_failed", extra={"dependency": name, "context": {"outcome": outcome}}
                )
        response = _problem(
            request,
            503,
            "DEPENDENCY_UNAVAILABLE",
            "A required dependency is unavailable",
            retryable=True,
        )
        response.headers["Retry-After"] = "30"
        return response

    return app
