"""Patient-scoped read contracts for the canonical clinical store."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from mage_med_contracts.clinical import (
    AssertionType,
    CodeableConcept,
    Identifier,
    ImportStatus,
    NoteContentOrigin,
    NoteType,
    ReferenceRange,
    SourceFormat,
)


class ReadModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ValueState(StrEnum):
    """Source value semantics; missing is never treated as a negative finding."""

    OBSERVED = "observed"
    OBSERVED_NEGATIVE = "observed_negative"
    MISSING = "missing"


class TimelineRecordType(StrEnum):
    ENCOUNTER = "encounter"
    CONDITION = "condition"
    OBSERVATION = "observation"
    MEDICATION_REQUEST = "medication_request"
    ALLERGY = "allergy"
    CLINICAL_NOTE = "clinical_note"


class PageInfo(ReadModel):
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
    total: int = Field(ge=0)


class SourceLink(ReadModel):
    source_artifact_id: UUID
    source_locator: str
    resource_type: str | None = None
    resource_id: str | None = None
    provenance_href: str


class PatientSummary(ReadModel):
    patient_id: UUID
    identifiers: list[Identifier] = Field(default_factory=list)
    family_name: str | None = None
    given_names: list[str] = Field(default_factory=list)
    birth_date: date | None = None
    administrative_gender: str | None = None
    active: bool | None = None
    imported_at: datetime
    source: SourceLink


class PatientPage(ReadModel):
    items: list[PatientSummary]
    page: PageInfo


class PatientDetail(PatientSummary):
    encounter_count: int
    condition_count: int
    observation_count: int
    medication_request_count: int
    allergy_count: int
    note_count: int


class TimelineDetails(ReadModel):
    code: CodeableConcept | None = None
    status: str | None = None
    secondary_status: CodeableConcept | None = None
    value_quantity: Decimal | None = None
    value_unit: str | None = None
    value_unit_system: str | None = None
    value_unit_code: str | None = None
    value_text: str | None = None
    data_absent_reason: CodeableConcept | None = None
    reference_range: list[ReferenceRange] = Field(default_factory=list)
    period_start: datetime | None = None
    period_end: datetime | None = None
    authored_on: datetime | None = None
    dosage_text: str | None = None
    title: str | None = None
    note_type: NoteType | None = None
    content_origin: NoteContentOrigin | None = None
    chunk_count: int | None = None


class TimelineEntry(ReadModel):
    record_id: UUID
    record_type: TimelineRecordType
    patient_id: UUID
    encounter_id: UUID | None = None
    event_time: datetime | date | None = None
    recorded_time: datetime | None = None
    imported_at: datetime
    sort_time_basis: str
    assertion_type: AssertionType
    value_state: ValueState
    missing_fields: list[str] = Field(default_factory=list)
    details: TimelineDetails
    source: SourceLink


class TimelinePage(ReadModel):
    patient_id: UUID
    items: list[TimelineEntry]
    page: PageInfo


class ObservationView(ReadModel):
    observation_id: UUID
    patient_id: UUID
    encounter_id: UUID | None = None
    event_time: datetime | date | None = None
    recorded_time: datetime | None = None
    imported_at: datetime
    assertion_type: AssertionType
    code: CodeableConcept
    status: str
    value_quantity: Decimal | None = None
    value_unit: str | None = None
    value_unit_system: str | None = None
    value_unit_code: str | None = None
    value_text: str | None = None
    data_absent_reason: CodeableConcept | None = None
    reference_range: list[ReferenceRange] = Field(default_factory=list)
    value_state: ValueState
    source: SourceLink


class ObservationPage(ReadModel):
    patient_id: UUID
    items: list[ObservationView]
    page: PageInfo


class NoteReference(ReadModel):
    note_id: UUID
    patient_id: UUID
    encounter_id: UUID | None = None
    note_type: NoteType
    title: str | None = None
    authored_at: datetime | None = None
    recorded_time: datetime | None = None
    imported_at: datetime
    author_reference: str | None = None
    source_label: str | None = None
    content_origin: NoteContentOrigin
    chunk_count: int
    source: SourceLink


class NotePage(ReadModel):
    patient_id: UUID
    items: list[NoteReference]
    page: PageInfo


class SourceRecordReference(ReadModel):
    record_type: str
    record_id: UUID
    patient_id: UUID | None = None
    encounter_id: UUID | None = None


class SourceMappingView(ReadModel):
    source_key: str
    resource_type: str | None = None
    resource_id: str | None = None
    normalized_type: str | None = None
    normalized_id: UUID | None = None
    outcome_status: str
    issues: list[str]


class ImportDiagnostic(ReadModel):
    manifest_id: UUID
    dataset_id: str
    dataset_version: str
    status: ImportStatus
    importer_name: str
    importer_version: str
    record_counts: dict[str, int]
    idempotency_key: str
    duplicate_normalized_mappings: int = 0
    replay_attempts_persisted: bool = False


class SourceProvenance(ReadModel):
    source_artifact_id: UUID
    source_format: SourceFormat
    source_locator: str
    original_filename: str | None = None
    media_type: str
    sha256: str
    imported_at: datetime
    synthetic: bool
    raw_content: dict[str, Any] | list[Any] | str | None = None
    import_diagnostic: ImportDiagnostic | None = None
    mappings: list[SourceMappingView] = Field(default_factory=list)
    normalized_records: list[SourceRecordReference] = Field(default_factory=list)


class DataQualityIssue(ReadModel):
    category: str
    count: int = Field(ge=0)
    examples: list[str] = Field(default_factory=list)


class DataQualityReport(ReadModel):
    generated_at: datetime
    dataset_id: str | None = None
    issues: list[DataQualityIssue]
    human_readable: str
