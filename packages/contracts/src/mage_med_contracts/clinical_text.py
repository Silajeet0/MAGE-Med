"""API contracts for deterministic clinical-text ingestion and retrieval."""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from mage_med_contracts.clinical import (
    AssertionType,
    ImportStatus,
    NoteContentOrigin,
    NoteType,
)


class TextNoteImportStatus(StrEnum):
    IMPORTED = "imported"
    UPDATED = "updated"
    UNLINKED = "unlinked"
    UNUSABLE = "unusable"


class TextNoteImportOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(min_length=1, max_length=512)
    status: TextNoteImportStatus
    note_id: UUID | None = None
    patient_id: UUID | None = None
    encounter_id: UUID | None = None
    chunk_count: int = Field(default=0, ge=0)
    issues: list[str] = Field(default_factory=list)


class TextImportReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    import_id: UUID
    status: ImportStatus
    source_artifact_id: UUID
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    idempotent_replay: bool = False
    started_at: datetime
    completed_at: datetime | None = None
    record_counts: dict[str, int] = Field(default_factory=dict)
    notes: list[TextNoteImportOutcome] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class NoteChunkResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_id: UUID
    chunk_index: int
    start_offset: int
    end_offset: int
    text: str
    section: str | None = None
    sha256: str


class ClinicalNoteResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note_id: UUID
    patient_id: UUID | None = None
    encounter_id: UUID | None = None
    note_type: NoteType
    title: str | None = None
    original_text: str
    text: str
    authored_at: datetime | None = None
    author_reference: str | None = None
    source_label: str | None = None
    content_origin: NoteContentOrigin
    source_artifact_id: UUID
    source_locator: str
    assertion_type: AssertionType
    synthetic: bool
    chunks: list[NoteChunkResponse] = Field(default_factory=list)


class StructuredRecordSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record_id: UUID
    record_type: str
    encounter_id: UUID | None = None
    event_time: datetime | None = None
    source_artifact_id: UUID
    source_locator: str


class PatientClinicalContextResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    patient_id: UUID
    structured_records: list[StructuredRecordSummary] = Field(default_factory=list)
    notes: list[ClinicalNoteResponse] = Field(default_factory=list)
