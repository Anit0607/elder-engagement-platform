from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, load_settings_file
from app.main import create_app
from app.readiness import DependencyStatus

CONFIG_EXAMPLE = Path(__file__).parents[3] / "config" / "engagement" / ".env.example"


class FakeProbe:
    def __init__(self, *, ready: bool = True, raises: bool = False) -> None:
        self.ready = ready
        self.raises = raises

    async def check(self) -> DependencyStatus:
        if self.raises:
            raise RuntimeError("synthetic probe failure with password=not-real")
        return DependencyStatus(self.ready, "UNAVAILABLE" if not self.ready else "READY")


@pytest.fixture
def settings() -> Settings:
    return load_settings_file(CONFIG_EXAMPLE)


@pytest.fixture
def ready_probes() -> dict[str, FakeProbe]:
    return {
        "database": FakeProbe(),
        "rate_limit_store": FakeProbe(),
        "object_storage": FakeProbe(),
        "identity_verifier": FakeProbe(),
    }


@pytest.fixture
def client(settings, ready_probes):
    with TestClient(create_app(settings, ready_probes)) as test_client:
        yield test_client
