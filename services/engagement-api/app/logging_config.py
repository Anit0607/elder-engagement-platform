from __future__ import annotations

import json
import logging
import re
from contextvars import ContextVar
from datetime import UTC, datetime

request_id_context: ContextVar[str | None] = ContextVar("request_id", default=None)
trace_id_context: ContextVar[str | None] = ContextVar("trace_id", default=None)

SENSITIVE_NAME = (
    r"authorization|cookie|access_?token|refresh_?token|provider_?id_?token|"
    r"phone(?:_?(?:number|e164))?|signed_?url|upload_?url|[a-z0-9_]*secret_ref|password|secret|token"
)
SENSITIVE_KEY = re.compile(rf"(?i)^(?:{SENSITIVE_NAME})$")
QUOTED_SENSITIVE = re.compile(
    rf'''(?i)\b({SENSITIVE_NAME})'''
    r'''(["']?\s*[:=]\s*)(["'])(.*?)(\3)'''
)
AUTHORIZATION_VALUE = re.compile(
    r'''(?i)\b(authorization(?:["']?\s*[:=]\s*|\s+))(?:Bearer\s+)?([^,}"'\s]+)'''
)
UNQUOTED_SENSITIVE = re.compile(
    rf"(?i)\b({SENSITIVE_NAME})([\s:=]+)([^,}}\s]+)"
)
SIGNED_URL_QUERY = re.compile(
    r'''(?i)([?&](?:x-goog-signature|x-amz-signature)=)[^&#\s"']+'''
)


def redact(value: str) -> str:
    value = SIGNED_URL_QUERY.sub(r"\1[REDACTED]", value)
    value = QUOTED_SENSITIVE.sub(r"\1\2\3[REDACTED]\5", value)
    value = AUTHORIZATION_VALUE.sub(r"\1[REDACTED]", value)
    return UNQUOTED_SENSITIVE.sub(r"\1\2[REDACTED]", value)


def sanitize(value: object, key: str | None = None) -> object:
    if key and SENSITIVE_KEY.fullmatch(key):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(item_key): sanitize(item_value, str(item_key)) for item_key, item_value in value.items()}
    if isinstance(value, (list, tuple)):
        return [sanitize(item) for item in value]
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return redact(str(value))


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact(record.getMessage()),
        }
        request_id = getattr(record, "request_id", None) or request_id_context.get()
        trace_id = getattr(record, "trace_id", None) or trace_id_context.get()
        if request_id:
            payload["request_id"] = request_id
        if trace_id:
            payload["trace_id"] = trace_id
        for key in ("method", "route", "status_code", "duration_ms", "dependency"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = sanitize(value, key)
        context = getattr(record, "context", None)
        if context is not None:
            payload["context"] = sanitize(context)
        if record.exc_info:
            payload["exception_type"] = record.exc_info[0].__name__
        return json.dumps(payload, separators=(",", ":"), ensure_ascii=True)


def configure_logging(level: str) -> None:
    logger = logging.getLogger("engagement")
    logger.handlers.clear()
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False
