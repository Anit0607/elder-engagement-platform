from __future__ import annotations

from starlette.responses import JSONResponse


def problem_response(
    trace_id: str,
    status: int,
    code: str,
    title: str,
    *,
    retryable: bool = False,
) -> JSONResponse:
    return JSONResponse(
        {
            "type": f"about:blank#{code.lower()}",
            "title": title,
            "status": status,
            "code": code,
            "traceId": trace_id,
            "retryable": retryable,
        },
        status_code=status,
        media_type="application/problem+json",
    )
