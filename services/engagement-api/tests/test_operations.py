from __future__ import annotations

import asyncio
import io
import json
import logging
import time

from fastapi import Query
from fastapi.testclient import TestClient

from app.logging_config import JsonFormatter, redact, sanitize
from app.main import create_app
from app.readiness import DependencyStatus
from app.request_limits import RequestBodyLimitMiddleware
from tests.conftest import FakeProbe


class FalseWithReadyCodeProbe:
    async def check(self) -> DependencyStatus:
        return DependencyStatus(ready=False)


class SlowProbe:
    async def check(self) -> DependencyStatus:
        await asyncio.sleep(0.1)
        return DependencyStatus(ready=True)


def test_health_is_minimal_and_has_correlation_headers(client):
    response = client.get("/health", headers={"X-Request-Id": "ios-smoke-001"})
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["X-Request-Id"] == "ios-smoke-001"
    assert response.headers["traceparent"].startswith("00-")
    assert response.headers["Cache-Control"] == "no-store"


def test_invalid_request_id_is_replaced(client):
    response = client.get("/health", headers={"X-Request-Id": "invalid request id"})
    assert response.status_code == 200
    assert response.headers["X-Request-Id"] != "invalid request id"
    assert len(response.headers["X-Request-Id"]) == 36


def test_valid_incoming_trace_is_continued(client):
    trace_id = "1" * 32
    response = client.get("/health", headers={"traceparent": f"00-{trace_id}-{'2' * 16}-01"})
    assert response.headers["traceparent"].split("-")[1] == trace_id


def test_zero_trace_id_is_replaced(client):
    response = client.get(
        "/health",
        headers={"traceparent": f"00-{'0' * 32}-{'2' * 16}-01"},
    )
    assert response.headers["traceparent"].split("-")[1] != "0" * 32


def test_ready_succeeds_only_when_every_probe_is_ready(client):
    response = client.get("/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_fails_closed_for_unavailable_dependency(settings, ready_probes):
    ready_probes["database"] = FakeProbe(ready=False)
    with TestClient(create_app(settings, ready_probes)) as client:
        response = client.get("/ready")
    assert response.status_code == 503
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "DEPENDENCY_UNAVAILABLE"
    assert response.json()["traceId"]
    assert "checks" not in response.json()
    assert response.headers["Retry-After"] == "30"


def test_ready_uses_boolean_not_default_success_code(settings, ready_probes):
    ready_probes["database"] = FalseWithReadyCodeProbe()
    with TestClient(create_app(settings, ready_probes)) as client:
        response = client.get("/ready")
    assert response.status_code == 503
    assert response.json()["code"] == "DEPENDENCY_UNAVAILABLE"


def test_ready_fails_when_required_probe_is_omitted(settings):
    with TestClient(create_app(settings, {"database": FakeProbe()})) as client:
        response = client.get("/ready")
    assert response.status_code == 503


def test_ready_probe_timeout_is_bounded(settings, ready_probes):
    ready_probes["database"] = SlowProbe()
    started = time.perf_counter()
    with TestClient(create_app(settings, ready_probes, probe_timeout_seconds=0.01)) as client:
        response = client.get("/ready")
    assert response.status_code == 503
    assert time.perf_counter() - started < 1


def test_ready_fails_closed_when_probe_raises(settings, ready_probes):
    ready_probes["object_storage"] = FakeProbe(raises=True)
    with TestClient(create_app(settings, ready_probes)) as client:
        response = client.get("/ready")
    assert response.status_code == 503
    assert response.json()["code"] == "DEPENDENCY_UNAVAILABLE"
    assert "checks" not in response.json()
    assert "password" not in response.text.lower()


def test_default_unwired_probes_are_not_ready(settings):
    with TestClient(create_app(settings)) as client:
        response = client.get("/ready")
    assert response.status_code == 503
    assert response.json()["code"] == "DEPENDENCY_UNAVAILABLE"


def test_unhandled_route_error_is_safe_problem(settings, ready_probes):
    app = create_app(settings, ready_probes)

    @app.get("/synthetic-error")
    async def synthetic_error():
        raise RuntimeError("password=not-real")

    with TestClient(app) as client:
        response = client.get("/synthetic-error")
    assert response.status_code == 500
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "INTERNAL_ERROR"
    assert response.json()["retryable"] is False
    assert "password" not in response.text.lower()


def test_app_can_disable_cors(settings, ready_probes):
    without_cors = settings.model_copy(update={"cors_origins": ""})
    with TestClient(create_app(without_cors, ready_probes)) as client:
        assert client.get("/health").status_code == 200


def test_log_formatter_redacts_and_emits_context():
    message = (
        "authorization Bearer token-value accessToken=one refresh_token=two "
        "providerIdToken=three phone_number=+919876543210 DB_SECRET_REF=projects/private"
    )
    assert "token-value" not in redact(message)
    assert "+919876543210" not in redact(message)
    assert "projects/private" not in redact(message)

    record = logging.LogRecord("engagement.test", logging.ERROR, __file__, 1, message, (), None)
    record.request_id = "request-001"
    record.trace_id = "a" * 32
    payload = json.loads(JsonFormatter().format(record))
    assert payload["request_id"] == "request-001"
    assert payload["trace_id"] == "a" * 32
    assert "token-value" not in payload["message"]


def test_structured_log_context_is_recursively_sanitized():
    context = {
        "accessToken": "one",
        "nested": {"refresh_token": "two", "phone_number": "+919876543210"},
        "list": [{"providerIdToken": "three"}],
    }
    sanitized = sanitize(context)
    assert sanitized["accessToken"] == "[REDACTED]"
    assert sanitized["nested"]["refresh_token"] == "[REDACTED]"  # noqa: S105 - sentinel
    assert sanitized["nested"]["phone_number"] == "[REDACTED]"
    assert sanitized["list"][0]["providerIdToken"] == "[REDACTED]"


def test_signed_upload_urls_are_redacted():
    upload_url = (
        "https://storage.googleapis.com/synthetic/object"
        "?X-Goog-Signature=synthetic-marker&X-Goog-Expires=900"
    )
    sanitized = sanitize({"uploadUrl": upload_url})
    assert sanitized["uploadUrl"] == "[REDACTED]"
    assert "synthetic-marker" not in redact(f"callback={upload_url}")
    assert "X-Goog-Signature=[REDACTED]" in redact(f"callback={upload_url}")


def test_unmatched_user_path_is_not_logged(settings, ready_probes):
    app = create_app(settings, ready_probes)
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("engagement")
    logger.handlers[:] = [handler]
    with TestClient(app) as client:
        response = client.get("/refresh_token/super-private-value")
    assert response.status_code == 404
    assert "super-private-value" not in stream.getvalue()
    assert '"route":"<unmatched>"' in stream.getvalue()


def test_framework_404_and_405_are_safe_contract_problems(client):
    not_found = client.get("/missing")
    assert not_found.status_code == 404
    assert not_found.json()["code"] == "NOT_FOUND"
    assert not_found.headers["content-type"].startswith("application/problem+json")

    not_allowed = client.post("/health")
    assert not_allowed.status_code == 405
    assert not_allowed.json()["code"] == "METHOD_NOT_ALLOWED"


def test_request_validation_uses_contract_status(settings, ready_probes):
    app = create_app(settings, ready_probes)

    @app.get("/synthetic-validation")
    async def synthetic_validation(limit: int = Query(ge=1)):
        return {"limit": limit}

    with TestClient(app) as client:
        response = client.get("/synthetic-validation?limit=invalid")
    assert response.status_code == 400
    assert response.json()["code"] == "VALIDATION_FAILED"


def test_oversized_declared_body_is_rejected(client):
    response = client.request("GET", "/health", content=b"x" * 1_048_577)
    assert response.status_code == 413
    assert response.json()["code"] == "PAYLOAD_TOO_LARGE"
    assert response.headers["content-type"].startswith("application/problem+json")


def test_streamed_body_is_counted_without_content_length():
    called = False

    async def downstream(scope, receive, send):
        nonlocal called
        called = True

    middleware = RequestBodyLimitMiddleware(downstream, max_bytes=5)
    messages = iter(
        [
            {"type": "http.request", "body": b"abc", "more_body": True},
            {"type": "http.request", "body": b"def", "more_body": False},
        ]
    )
    sent = []

    async def receive():
        return next(messages)

    async def send(message):
        sent.append(message)

    scope = {"type": "http", "headers": [], "state": {"trace_id": "a" * 32}}
    asyncio.run(middleware(scope, receive, send))
    assert called is False
    assert sent[0]["status"] == 413
    assert b"PAYLOAD_TOO_LARGE" in sent[1]["body"]


def test_invalid_host_is_normalized(settings, ready_probes):
    with TestClient(create_app(settings, ready_probes)) as client:
        response = client.get("/health", headers={"host": "attacker.invalid"})
    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_REQUEST"


def test_create_app_rejects_unsafe_runtime_bounds(settings, ready_probes):
    for timeout in (0, 31):
        try:
            create_app(settings, ready_probes, probe_timeout_seconds=timeout)
        except ValueError as exc:
            assert "probe_timeout_seconds" in str(exc)
        else:
            raise AssertionError("unsafe timeout accepted")
    try:
        create_app(settings, ready_probes, max_request_body_bytes=0)
    except ValueError as exc:
        assert "max_request_body_bytes" in str(exc)
    else:
        raise AssertionError("unsafe request limit accepted")


def test_unknown_probe_name_is_rejected(settings, ready_probes):
    ready_probes["user_supplied_name"] = FakeProbe()
    try:
        create_app(settings, ready_probes)
    except ValueError as exc:
        assert str(exc) == "unknown readiness dependency"
    else:
        raise AssertionError("unknown dependency name accepted")
