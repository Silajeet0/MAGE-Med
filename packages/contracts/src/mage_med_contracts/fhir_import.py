"""Versioned API contracts for local FHIR R4 import reporting."""

from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from mage_med_contracts.clinical import ImportStatus


class ResourceImportStatus(StrEnum):
    """Outcome for one source resource."""

    IMPORTED = "imported"
    UPDATED = "updated"
    UNAVAILABLE = "unavailable"
    UNUSABLE = "unusable"
    UNSUPPORTED = "unsupported"


class ResourceImportOutcome(BaseModel):
    """Safe source-to-normalized mapping result for one FHIR resource."""

    model_config = ConfigDict(extra="forbid")

    source_key: str = Field(min_length=1, max_length=1024)
    resource_type: str | None = Field(default=None, max_length=128)
    resource_id: str | None = Field(default=None, max_length=256)
    full_url: str | None = Field(default=None, max_length=2048)
    status: ResourceImportStatus
    normalized_type: str | None = Field(default=None, max_length=128)
    normalized_id: UUID | None = None
    issues: list[str] = Field(default_factory=list)


class FhirImportReport(BaseModel):
    """Persisted result returned by POST and GET import endpoints."""

    model_config = ConfigDict(extra="forbid")

    import_id: UUID
    status: ImportStatus
    source_artifact_id: UUID | None = None
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    validation_package: Literal["fhirclient"] = "fhirclient"
    validation_package_version: Literal["4.2.0"] = "4.2.0"
    fhir_version: Literal["4.0.1"] = "4.0.1"
    validation_scope: Literal["base_structure_and_project_invariants"] = (
        "base_structure_and_project_invariants"
    )
    profile_conformance: Literal["not_evaluated"] = "not_evaluated"
    idempotent_replay: bool = False
    started_at: datetime
    completed_at: datetime | None = None
    record_counts: dict[str, int] = Field(default_factory=dict)
    resources: list[ResourceImportOutcome] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
