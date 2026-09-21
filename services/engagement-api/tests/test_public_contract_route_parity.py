"""Keep the iOS-facing API document honest about callable application routes."""

from __future__ import annotations

import json
from pathlib import Path

from app.main import create_app

CONTRACT_PATH = Path(__file__).parents[3] / "api" / "openapi" / "elder-engage-v1.openapi.json"
HTTP_METHODS = {"get", "post", "put", "patch", "delete"}


def test_documented_routes_match_runtime_except_explicitly_planned_operations(settings):
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    documented = {
        (method, path): operation
        for path, path_item in contract["paths"].items()
        for method, operation in path_item.items()
        if method in HTTP_METHODS
    }
    application = create_app(settings)
    runtime = {
        (method.lower(), route.path)
        for route in application.routes
        for method in getattr(route, "methods", set())
        if method.lower() in HTTP_METHODS
        and (route.path.startswith("/v1/") or route.path in {"/health", "/ready"})
    }
    planned = {
        key
        for key, operation in documented.items()
        if operation.get("x-implementation-status") == "planned-not-callable"
    }

    assert runtime <= documented.keys(), "A callable route is absent from the public contract"
    assert set(documented) - runtime == planned, (
        "Every documented but unavailable route must be explicitly marked planned"
    )
    assert planned == {("get", "/v1/admin/users"), ("post", "/v1/admin/users")}
