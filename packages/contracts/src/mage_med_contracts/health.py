"""Health and error contracts used at the initial API boundary."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class HealthStatus(StrEnum):
    """Overall API health state."""

    HEALTHY = "healthy"
    NOT_READY = "not_ready"


class ComponentStatus(StrEnum):
    """Connectivity state of a required component."""

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


class ComponentCheck(BaseModel):
    """Sanitized result of a component connectivity check."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=64)
    status: ComponentStatus
    detail: str = Field(min_length=1, max_length=256)


class HealthResponse(BaseModel):
    """Response returned by liveness and readiness routes."""

    model_config = ConfigDict(extra="forbid")

    service: str = Field(min_length=1, max_length=64)
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    status: HealthStatus
    request_id: str = Field(min_length=1, max_length=128)
    components: list[ComponentCheck] = Field(default_factory=list)


class ErrorBody(BaseModel):
    """Structured, non-sensitive error information."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1, max_length=512)
    request_id: str = Field(min_length=1, max_length=128)


class ErrorResponse(BaseModel):
    """Stable envelope for API failures."""

    model_config = ConfigDict(extra="forbid")

    error: ErrorBody
