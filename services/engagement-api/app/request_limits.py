from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from app.problems import problem_response

ASGIApp = Callable[
    [dict[str, Any], Callable[..., Awaitable[dict]], Callable[..., Awaitable[None]]],
    Awaitable[None],
]


class RequestBodyLimitMiddleware:
    """Bound request buffering so chunked bodies cannot bypass Content-Length checks."""

    def __init__(self, app: ASGIApp, max_bytes: int = 1_048_576) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: dict[str, Any], receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        header_map = {key.lower(): value for key, value in scope.get("headers", [])}
        content_length = header_map.get(b"content-length", b"")
        try:
            declared_length = int(content_length) if content_length else 0
        except ValueError:
            await self._send_problem(scope, receive, send, 400, "INVALID_REQUEST", "Invalid request")
            return
        if declared_length < 0:
            await self._send_problem(scope, receive, send, 400, "INVALID_REQUEST", "Invalid request")
            return
        if declared_length > self.max_bytes:
            await self._send_problem(
                scope, receive, send, 413, "PAYLOAD_TOO_LARGE", "Request payload is too large"
            )
            return

        messages: list[dict[str, Any]] = []
        total = 0
        while True:
            message = await receive()
            messages.append(message)
            if message["type"] != "http.request":
                break
            total += len(message.get("body", b""))
            if total > self.max_bytes:
                await self._send_problem(
                    scope, receive, send, 413, "PAYLOAD_TOO_LARGE", "Request payload is too large"
                )
                return
            if not message.get("more_body", False):
                break

        index = 0

        async def replay() -> dict[str, Any]:
            nonlocal index
            if index < len(messages):
                message = messages[index]
                index += 1
                return message
            return {"type": "http.request", "body": b"", "more_body": False}

        await self.app(scope, replay, send)

    @staticmethod
    async def _send_problem(scope, receive, send, status: int, code: str, title: str) -> None:
        state = scope.get("state", {})
        trace_id = state.get("trace_id", "0" * 32) if isinstance(state, dict) else "0" * 32
        response = problem_response(trace_id, status, code, title)
        await response(scope, receive, send)
