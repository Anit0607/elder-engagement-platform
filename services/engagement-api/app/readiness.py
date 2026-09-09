from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class DependencyStatus:
    ready: bool
    code: str = "READY"


class DependencyProbe(Protocol):
    async def check(self) -> DependencyStatus: ...


class NotConfiguredProbe:
    async def check(self) -> DependencyStatus:
        return DependencyStatus(ready=False, code="NOT_CONFIGURED")


REQUIRED_DEPENDENCIES = (
    "database",
    "rate_limit_store",
    "object_storage",
    "identity_verifier",
)


def default_probes() -> dict[str, DependencyProbe]:
    return {name: NotConfiguredProbe() for name in REQUIRED_DEPENDENCIES}
