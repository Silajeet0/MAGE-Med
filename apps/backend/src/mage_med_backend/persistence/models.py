"""SQLAlchemy persistence models for the canonical clinical contracts."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from mage_med_contracts import (
    AssertionLifecycleStatus,
    AssertionType,
    DataModality,
    ImportStatus,
    NoteContentOrigin,
    NoteType,
    ResourceImportStatus,
    SourceFormat,
    VerificationStatus,
)
from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _string_enum(enum_type: type[Any], name: str) -> Enum:
    return Enum(
        enum_type,
        values_callable=lambda members: [member.value for member in members],
        name=name,
        native_enum=False,
        create_constraint=True,
        validate_strings=True,
    )


class Base(DeclarativeBase):
    """Declarative metadata used by Alembic and persistence tests."""


class SourceArtifactRecord(Base):
    """Immutable original file/resource payload."""

    __tablename__ = "source_artifacts"

    internal_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    schema_version: Mapped[str] = mapped_column(String(16), nullable=False)
    modality: Mapped[DataModality] = mapped_column(
        _string_enum(DataModality, "data_modality"), nullable=False
    )
    source_format: Mapped[SourceFormat] = mapped_column(
        _string_enum(SourceFormat, "source_format"), nullable=False
    )
    source_locator: Mapped[str] = mapped_column(String(2048), nullable=False)
    original_filename: Mapped[str | None] = mapped_column(String(512))
    media_type: Mapped[str] = mapped_column(String(256), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    raw_content: Mapped[dict[str, Any] | list[Any] | str] = mapped_column(JSON, nullable=False)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False)


class ImportManifestRecord(Base):
    """Persistence representation of a deterministic import attempt."""

    __tablename__ = "import_manifests"
    __table_args__ = (
        UniqueConstraint("dataset_id", "dataset_version", "internal_id", name="uq_import_run"),
        UniqueConstraint("primary_source_artifact_id", name="uq_import_manifest_primary_artifact"),
    )

    internal_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    schema_version: Mapped[str] = mapped_column(String(16), nullable=False)
    dataset_id: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    dataset_version: Mapped[str] = mapped_column(String(128), nullable=False)
    source_format: Mapped[SourceFormat] = mapped_column(
        _string_enum(SourceFormat, "manifest_source_format"), nullable=False
    )
    status: Mapped[ImportStatus] = mapped_column(
        _string_enum(ImportStatus, "import_status"), nullable=False
    )
    source_artifact_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    importer_name: Mapped[str] = mapped_column(String(128), nullable=False)
    importer_version: Mapped[str] = mapped_column(String(32), nullable=False)
    synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False)
    seed: Mapped[int | None]
    record_counts: Mapped[dict[str, int]] = mapped_column(JSON, nullable=False)
    errors: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    primary_source_artifact_id: Mapped[str | None] = mapped_column(
        ForeignKey("source_artifacts.internal_id", ondelete="RESTRICT"),
        index=True,
    )
    validation_summary: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    resource_outcomes: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)


class SourceResourceMappingRecord(Base):
    """Current source-to-normalized identity map with original resource JSON."""

    __tablename__ = "source_resource_mappings"

    internal_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_key: Mapped[str] = mapped_column(String(1024), nullable=False, unique=True)
    source_artifact_id: Mapped[str] = mapped_column(
        ForeignKey("source_artifacts.internal_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    import_manifest_id: Mapped[str] = mapped_column(
        ForeignKey("import_manifests.internal_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    resource_type: Mapped[str | None] = mapped_column(String(128), index=True)
    resource_id: Mapped[str | None] = mapped_column(String(256))
    full_url: Mapped[str | None] = mapped_column(String(2048), index=True)
    normalized_type: Mapped[str | None] = mapped_column(String(128))
    normalized_id: Mapped[str | None] = mapped_column(String(36), index=True)
    outcome_status: Mapped[ResourceImportStatus] = mapped_column(
        _string_enum(ResourceImportStatus, "resource_import_status"), nullable=False
    )
    issues: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    original_resource: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ClinicalFactRecord(Base):
    """Abstract columns shared by all normalized clinical fact tables."""

    __abstract__ = True

    internal_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    schema_version: Mapped[str] = mapped_column(String(16), nullable=False)
    modality: Mapped[DataModality] = mapped_column(
        _string_enum(DataModality, "fact_data_modality"), nullable=False
    )
    source_artifact_id: Mapped[str] = mapped_column(
        ForeignKey("source_artifacts.internal_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    import_manifest_id: Mapped[str] = mapped_column(
        ForeignKey("import_manifests.internal_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    source_locator: Mapped[str] = mapped_column(String(2048), nullable=False)
    source_resource_type: Mapped[str | None] = mapped_column(String(128))
    source_resource_id: Mapped[str | None] = mapped_column(String(256))
    event_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    event_date: Mapped[date | None] = mapped_column(Date)
    recorded_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    assertion_type: Mapped[AssertionType] = mapped_column(
        _string_enum(AssertionType, "assertion_type"), nullable=False
    )
    provenance: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class PatientRecord(ClinicalFactRecord):
    __tablename__ = "patients"
    __table_args__ = (
        UniqueConstraint(
            "source_artifact_id",
            "source_resource_type",
            "source_resource_id",
            name="uq_patient_source_resource",
        ),
    )

    identifiers: Mapped[list[dict[str, str | None]]] = mapped_column(JSON, nullable=False)
    family_name: Mapped[str | None] = mapped_column(String(256))
    given_names: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    birth_date: Mapped[date | None] = mapped_column(Date)
    administrative_gender: Mapped[str | None] = mapped_column(String(64))
    active: Mapped[bool | None] = mapped_column(Boolean)


class EncounterRecord(ClinicalFactRecord):
    __tablename__ = "encounters"
    __table_args__ = (
        UniqueConstraint(
            "source_artifact_id",
            "source_resource_type",
            "source_resource_id",
            name="uq_encounter_source_resource",
        ),
    )

    patient_id: Mapped[str | None] = mapped_column(
        ForeignKey("patients.internal_id", ondelete="RESTRICT"), index=True
    )
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    class_code: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    encounter_type: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PatientEncounterFactRecord(ClinicalFactRecord):
    """Abstract fact that can link to patient and encounter context."""

    __abstract__ = True

    patient_id: Mapped[str | None] = mapped_column(
        ForeignKey("patients.internal_id", ondelete="RESTRICT"), index=True
    )
    encounter_id: Mapped[str | None] = mapped_column(
        ForeignKey("encounters.internal_id", ondelete="RESTRICT"), index=True
    )


class ConditionRecord(PatientEncounterFactRecord):
    __tablename__ = "conditions"

    code: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    clinical_status: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    verification_status: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    onset_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    onset_date: Mapped[date | None] = mapped_column(Date)
    abatement_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    abatement_date: Mapped[date | None] = mapped_column(Date)


class ObservationRecord(PatientEncounterFactRecord):
    __tablename__ = "observations"

    code: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    value_quantity: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    value_unit: Mapped[str | None] = mapped_column(String(128))
    value_unit_system: Mapped[str | None] = mapped_column(String(512))
    value_unit_code: Mapped[str | None] = mapped_column(String(128))
    value_text: Mapped[str | None] = mapped_column(Text)
    data_absent_reason: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    reference_range: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)


class MedicationRequestRecord(PatientEncounterFactRecord):
    __tablename__ = "medication_requests"

    medication: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    intent: Mapped[str] = mapped_column(String(64), nullable=False)
    authored_on: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dosage_text: Mapped[str | None] = mapped_column(Text)


class AllergyRecord(PatientEncounterFactRecord):
    __tablename__ = "allergies"

    substance: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    clinical_status: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    verification_status: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    allergy_type: Mapped[str | None] = mapped_column(String(64))
    categories: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    criticality: Mapped[str | None] = mapped_column(String(64))
    reactions: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)


class ClinicalNoteRecord(PatientEncounterFactRecord):
    __tablename__ = "clinical_notes"

    note_type: Mapped[NoteType] = mapped_column(
        _string_enum(NoteType, "clinical_note_type"), nullable=False
    )
    title: Mapped[str | None] = mapped_column(String(512))
    original_text: Mapped[str] = mapped_column(Text, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    authored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    author_reference: Mapped[str | None] = mapped_column(String(512))
    source_label: Mapped[str | None] = mapped_column(String(512))
    content_origin: Mapped[NoteContentOrigin] = mapped_column(
        _string_enum(NoteContentOrigin, "clinical_note_content_origin"), nullable=False
    )


class ClinicalNoteChunkRecord(Base):
    """Exact cleaned-text span for deterministic note retrieval."""

    __tablename__ = "clinical_note_chunks"
    __table_args__ = (
        UniqueConstraint("note_id", "chunk_index", name="uq_note_chunk_index"),
        CheckConstraint("start_offset >= 0", name="ck_note_chunk_start"),
        CheckConstraint("end_offset > start_offset", name="ck_note_chunk_offsets"),
    )

    internal_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    schema_version: Mapped[str] = mapped_column(String(16), nullable=False)
    note_id: Mapped[str] = mapped_column(
        ForeignKey("clinical_notes.internal_id", ondelete="CASCADE"), nullable=False, index=True
    )
    chunk_index: Mapped[int] = mapped_column(nullable=False)
    start_offset: Mapped[int] = mapped_column(nullable=False)
    end_offset: Mapped[int] = mapped_column(nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    section: Mapped[str | None] = mapped_column(String(256))
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)


class ClinicalAssertionRecord(PatientEncounterFactRecord):
    __tablename__ = "clinical_assertions"

    subject_record_type: Mapped[str] = mapped_column(String(128), nullable=False)
    subject_record_id: Mapped[str] = mapped_column(String(36), nullable=False)
    predicate: Mapped[str] = mapped_column(String(256), nullable=False)
    value: Mapped[str | int | float | bool] = mapped_column(JSON, nullable=False)
    lifecycle_status: Mapped[AssertionLifecycleStatus | None] = mapped_column(
        _string_enum(AssertionLifecycleStatus, "assertion_lifecycle_status")
    )
    verification_status: Mapped[VerificationStatus] = mapped_column(
        _string_enum(VerificationStatus, "assertion_verification_status"), nullable=False
    )
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))


for table_name in (
    "patients",
    "encounters",
    "conditions",
    "observations",
    "medication_requests",
    "allergies",
    "clinical_notes",
    "clinical_assertions",
):
    table = Base.metadata.tables[table_name]
    Index(
        f"ix_{table_name}_source_resource", table.c.source_resource_type, table.c.source_resource_id
    )


@event.listens_for(SourceArtifactRecord, "before_update")
def _prevent_source_artifact_update(*_: object) -> None:
    raise ValueError("source artifacts are immutable; create a new artifact instead")
