"""Health aggregation independent from HTTP routing."""

import logging
from dataclasses import dataclass
from typing import Protocol

from mage_med_contracts import ComponentCheck, ComponentStatus, HealthStatus

logger = logging.getLogger(__name__)


class Connectivity(Protocol):
    """A required component that can verify and release its connection."""

    def verify(self) -> None: ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class ReadinessResult:
    """Aggregate readiness outcome and sanitized component checks."""

    status: HealthStatus
    components: list[ComponentCheck]


class HealthService:
    """Evaluate required local component connectivity."""

    def __init__(self, sqlite: Connectivity, neo4j: Connectivity) -> None:
        self._components = (("sqlite", sqlite), ("neo4j", neo4j))

    def readiness(self, request_id: str) -> ReadinessResult:
        """Run all checks and retain failures as an honest not-ready state."""

        checks: list[ComponentCheck] = []
        for name, component in self._components:
            try:
                component.verify()
                checks.append(
                    ComponentCheck(
                        name=name,
                        status=ComponentStatus.AVAILABLE,
                        detail="connectivity verified",
                    )
                )
            except Exception:
                logger.warning(
                    "required component unavailable",
                    extra={"component": name, "request_id": request_id},
                    exc_info=True,
                )
                checks.append(
                    ComponentCheck(
                        name=name,
                        status=ComponentStatus.UNAVAILABLE,
                        detail="connectivity check failed",
                    )
                )

        status = (
            HealthStatus.HEALTHY
            if all(check.status is ComponentStatus.AVAILABLE for check in checks)
            else HealthStatus.NOT_READY
        )
        return ReadinessResult(status=status, components=checks)

    def close(self) -> None:
        """Close each owned connectivity boundary."""

        for _, component in self._components:
            component.close()
