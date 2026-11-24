"""Canonical, versioned clinical and provenance contracts.

Both structured-data and clinical-text importers normalize into these models.
FHIR remains a source format; it is never represented as a third modality.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any, Final, Literal, TypeAlias
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

SchemaVersion = Literal["1.0.0"]
CLINICAL_SCHEMA_VERSION: Final[SchemaVersion] = "1.0.0"


def _timezone_aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must include an explicit UTC offset")
    return value


AwareDateTime = Annotated[datetime, AfterValidator(_timezone_aware)]
ClinicalTime: TypeAlias = AwareDateTime | date


class ContractModel(BaseModel):
    """Strict base configuration for versioned wire contracts."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class DataModality(StrEnum):
    """The only two patient-data modalities in MAGE-Med."""

    STRUCTURED_CLINICAL_DATA = "structured_clinical_data"
    UNSTRUCTURED_CLINICAL_TEXT = "unstructured_clinical_text"


class AssertionType(StrEnum):
    """How a clinical fact or assertion came to be stated."""

    OBSERVED = "observed"
    EXTRACTED = "extracted"
    MODEL_INFERRED = "model_inferred"
    HYPOTHESIZED = "hypothesized"
    CLINICIAN_CONFIRMED = "clinician_confirmed"
    CLINICIAN_REJECTED = "clinician_rejected"


class VerificationStatus(StrEnum):
    """Verification state, intentionally distinct from assertion type."""

    UNVERIFIED = "unverified"
    VERIFIED = "verified"
    REJECTED = "rejected"


class AssertionLifecycleStatus(StrEnum):
    """Lifecycle status for a derived assertion."""

    ACTIVE = "active"
    SUPERSEDED = "superseded"
    ENTERED_IN_ERROR = "entered_in_error"


class SourceFormat(StrEnum):
    """Supported source serialization formats."""

    FHIR_R4_JSON = "fhir_r4_json"
    JSON = "json"
    CSV = "csv"
    TXT = "txt"


class ImportStatus(StrEnum):
    """Actual outcome of an import attempt."""

    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class NoteType(StrEnum):
    """Supported unstructured clinical-note categories."""

    CONSULTATION = "consultation"
    CLINICAL_HISTORY = "clinical_history"
    PROGRESS = "progress"
    CLINICAL_NARRATIVE = "clinical_narrative"


class NoteContentOrigin(StrEnum):
    """How note text was supplied without implying clinical authorship."""

    DIRECT_FILE = "direct_file"
    FHIR_EMBEDDED = "fhir_embedded"
    FHIR_LOCAL_FILE = "fhir_local_file"


class Identifier(ContractModel):
    """A source identifier without assuming global uniqueness."""

    system: str | None = Field(default=None, max_length=512)
    value: str = Field(min_length=1, max_length=512)


class CodeableConcept(ContractModel):
    """A terminology code with its source semantics preserved."""

    system: str | None = Field(default=None, max_length=512)
    code: str | None = Field(default=None, max_length=256)
    display: str | None = Field(default=None, max_length=512)
    version: str | None = Field(default=None, max_length=128)
    text: str | None = Field(default=None, max_length=1024)

    @model_validator(mode="after")
    def require_code_or_text(self) -> CodeableConcept:
        if not self.code and not self.text:
            raise ValueError("a coded concept requires a code or text")
        return self


class SourceReference(ContractModel):
    """Resolvable pointer from a normalized record to its original source."""

    source_artifact_id: UUID
    source_locator: str = Field(min_length=1, max_length=2048)
    resource_type: str | None = Field(default=None, min_length=1, max_length=128)
    resource_id: str | None = Field(default=None, min_length=1, max_length=256)

    @model_validator(mode="after")
    def keep_fhir_identity_complete(self) -> SourceReference:
        if (self.resource_type is None) != (self.resource_id is None):
            raise ValueError("resource_type and resource_id must be supplied together")
        return self


class Provenance(ContractModel):
    """Parser and run provenance attached to every normalized clinical fact."""

    import_manifest_id: UUID
    importer_name: str = Field(min_length=1, max_length=128)
    importer_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    transformation_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    run_id: UUID
    actor_id: str = Field(min_length=1, max_length=256)
    synthetic: bool
    seed: int | None = None

    @model_validator(mode="after")
    def validate_seed(self) -> Provenance:
        if self.synthetic and self.seed is None:
            raise ValueError("synthetic provenance requires a fixed seed")
        if not self.synthetic and self.seed is not None:
            raise ValueError("a seed is meaningful only for synthetic provenance")
        return self


class ClinicalFact(ContractModel):
    """Fields required on every normalized clinical fact."""

    schema_version: SchemaVersion = CLINICAL_SCHEMA_VERSION
    internal_id: UUID
    modality: DataModality
    source_reference: SourceReference
    patient_id: UUID | None = None
    encounter_id: UUID | None = None
    event_time: ClinicalTime | None = None
    recorded_time: AwareDateTime | None = None
    imported_at: AwareDateTime
    provenance: Provenance
    assertion_type: AssertionType


class Patient(ClinicalFact):
    """Normalized patient demographics needed by the PoC."""

    record_type: Literal["patient"] = "patient"
    modality: Literal[DataModality.STRUCTURED_CLINICAL_DATA] = DataModality.STRUCTURED_CLINICAL_DATA
    identifiers: list[Identifier] = Field(default_factory=list)
    family_name: str | None = Field(default=None, max_length=256)
    given_names: list[str] = Field(default_factory=list)
    birth_date: date | None = None
    administrative_gender: str | None = Field(default=None, max_length=64)
    active: bool | None = None


class Encounter(ClinicalFact):
    """Normalized encounter context."""

    record_type: Literal["encounter"] = "encounter"
    modality: Literal[DataModality.STRUCTURED_CLINICAL_DATA] = DataModality.STRUCTURED_CLINICAL_DATA
    status: str = Field(min_length=1, max_length=64)
    class_code: CodeableConcept | None = None
    encounter_type: CodeableConcept | None = None
    period_start: AwareDateTime | None = None
    period_end: AwareDateTime | None = None

    @model_validator(mode="after")
    def validate_period(self) -> Encounter:
        if self.period_start and self.period_end and self.period_end < self.period_start:
            raise ValueError("encounter period_end cannot precede period_start")
        return self


class Condition(ClinicalFact):
    """Normalized condition without converting uncertainty into certainty."""

    record_type: Literal["condition"] = "condition"
    modality: Literal[DataModality.STRUCTURED_CLINICAL_DATA] = DataModality.STRUCTURED_CLINICAL_DATA
    code: CodeableConcept
    clinical_status: CodeableConcept | None = None
    verification_status: CodeableConcept | None = None
    onset_time: ClinicalTime | None = None
    abatement_time: ClinicalTime | None = None


class ReferenceRange(ContractModel):
    """Original quantitative reference interval supplied by the source."""

    low: Decimal | None = None
    high: Decimal | None = None
    unit: str | None = Field(default=None, max_length=128)
    unit_system: str | None = Field(default=None, max_length=512)
    unit_code: str | None = Field(default=None, max_length=128)
    text: str | None = Field(default=None, max_length=512)

    @model_validator(mode="after")
    def validate_bounds(self) -> ReferenceRange:
        if self.low is None and self.high is None and self.text is None:
            raise ValueError("reference range requires a bound or source text")
        if self.low is not None and self.high is not None and self.low > self.high:
            raise ValueError("reference range low cannot exceed high")
        return self


class Quantity(ContractModel):
    """Original quantity and unit as received from the source."""

    value: Decimal
    unit: str | None = Field(default=None, max_length=128)
    system: str | None = Field(default=None, max_length=512)
    code: str | None = Field(default=None, max_length=128)


class Observation(ClinicalFact):
    """Normalized laboratory observation with source units and range."""

    record_type: Literal["observation"] = "observation"
    modality: Literal[DataModality.STRUCTURED_CLINICAL_DATA] = DataModality.STRUCTURED_CLINICAL_DATA
    code: CodeableConcept
    status: str = Field(min_length=1, max_length=64)
    value_quantity: Quantity | None = None
    value_text: str | None = Field(default=None, max_length=4096)
    data_absent_reason: CodeableConcept | None = None
    reference_range: list[ReferenceRange] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_value_and_units(self) -> Observation:
        representations = (
            self.value_quantity is not None,
            self.value_text is not None,
            self.data_absent_reason is not None,
        )
        if sum(representations) != 1:
            raise ValueError("observation requires exactly one value or data_absent_reason")
        if self.value_quantity and self.value_quantity.unit:
            for interval in self.reference_range:
                if interval.unit and interval.unit != self.value_quantity.unit:
                    raise ValueError("reference range unit must match the observed source unit")
        return self


class MedicationRequestSummary(ClinicalFact):
    """Bounded summary of a FHIR R4 MedicationRequest."""

    record_type: Literal["medication_request"] = "medication_request"
    modality: Literal[DataModality.STRUCTURED_CLINICAL_DATA] = DataModality.STRUCTURED_CLINICAL_DATA
    medication: CodeableConcept
    status: str = Field(min_length=1, max_length=64)
    intent: str = Field(min_length=1, max_length=64)
    authored_on: AwareDateTime | None = None
    dosage_text: str | None = Field(default=None, max_length=4096)


class Allergy(ClinicalFact):
    """Normalized allergy or intolerance with reaction text/codes preserved."""

    record_type: Literal["allergy"] = "allergy"
    modality: Literal[DataModality.STRUCTURED_CLINICAL_DATA] = DataModality.STRUCTURED_CLINICAL_DATA
    substance: CodeableConcept
    clinical_status: CodeableConcept | None = None
    verification_status: CodeableConcept | None = None
    allergy_type: str | None = Field(default=None, max_length=64)
    categories: list[str] = Field(default_factory=list)
    criticality: str | None = Field(default=None, max_length=64)
    reactions: list[CodeableConcept] = Field(default_factory=list)


class ClinicalNote(ClinicalFact):
    """Normalized unstructured note content."""

    record_type: Literal["clinical_note"] = "clinical_note"
    modality: Literal[DataModality.UNSTRUCTURED_CLINICAL_TEXT] = (
        DataModality.UNSTRUCTURED_CLINICAL_TEXT
    )
    note_type: NoteType
    title: str | None = Field(default=None, max_length=512)
    original_text: str = Field(min_length=1)
    text: str = Field(min_length=1)
    authored_at: AwareDateTime | None = None
    author_reference: str | None = Field(default=None, max_length=512)
    source_label: str | None = Field(default=None, max_length=512)
    content_origin: NoteContentOrigin


class ClinicalNoteChunk(ContractModel):
    """Deterministic cleaned-text span traceable to one clinical note."""

    schema_version: SchemaVersion = CLINICAL_SCHEMA_VERSION
    internal_id: UUID
    note_id: UUID
    chunk_index: int = Field(ge=0)
    start_offset: int = Field(ge=0)
    end_offset: int = Field(gt=0)
    text: str = Field(min_length=1)
    section: str | None = Field(default=None, max_length=256)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_offsets(self) -> ClinicalNoteChunk:
        if self.end_offset <= self.start_offset:
            raise ValueError("chunk end_offset must follow start_offset")
        if self.end_offset - self.start_offset != len(self.text):
            raise ValueError("chunk offsets must exactly span chunk text")
        return self


class SourceArtifact(ContractModel):
    """Immutable source payload retained for audit and reproducibility."""

    schema_version: SchemaVersion = CLINICAL_SCHEMA_VERSION
    internal_id: UUID
    modality: DataModality
    source_format: SourceFormat
    source_locator: str = Field(min_length=1, max_length=2048)
    original_filename: str | None = Field(default=None, max_length=512)
    media_type: str = Field(min_length=1, max_length=256)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    raw_content: dict[str, Any] | list[Any] | str
    imported_at: AwareDateTime
    synthetic: bool


class ClinicalAssertion(ClinicalFact):
    """A source-linked extracted, inferred, hypothesized, or reviewed claim."""

    record_type: Literal["clinical_assertion"] = "clinical_assertion"
    subject_record_type: str = Field(min_length=1, max_length=128)
    subject_record_id: UUID
    predicate: str = Field(min_length=1, max_length=256)
    value: str | Decimal | bool
    lifecycle_status: AssertionLifecycleStatus | None = None
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    confidence: Decimal | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def validate_assertion_semantics(self) -> ClinicalAssertion:
        confidence_types = {
            AssertionType.EXTRACTED,
            AssertionType.MODEL_INFERRED,
            AssertionType.HYPOTHESIZED,
        }
        if self.confidence is not None and self.assertion_type not in confidence_types:
            raise ValueError("confidence is not meaningful for this assertion type")
        if self.assertion_type is AssertionType.CLINICIAN_CONFIRMED:
            if self.verification_status is not VerificationStatus.VERIFIED:
                raise ValueError("clinician_confirmed assertions must be verified")
        elif self.assertion_type is AssertionType.CLINICIAN_REJECTED:
            if self.verification_status is not VerificationStatus.REJECTED:
                raise ValueError("clinician_rejected assertions must be rejected")
        elif self.verification_status is VerificationStatus.VERIFIED:
            raise ValueError("verified status requires clinician_confirmed assertion type")
        elif self.verification_status is VerificationStatus.REJECTED:
            raise ValueError("rejected status requires clinician_rejected assertion type")
        return self


class ImportManifest(ContractModel):
    """Versioned record of one deterministic import attempt."""

    schema_version: SchemaVersion = CLINICAL_SCHEMA_VERSION
    internal_id: UUID
    dataset_id: str = Field(min_length=1, max_length=256)
    dataset_version: str = Field(min_length=1, max_length=128)
    source_format: SourceFormat
    status: ImportStatus
    source_artifact_ids: list[UUID] = Field(default_factory=list)
    started_at: AwareDateTime
    completed_at: AwareDateTime | None = None
    importer_name: str = Field(min_length=1, max_length=128)
    importer_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    synthetic: bool
    seed: int | None = None
    record_counts: dict[str, int] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_outcome(self) -> ImportManifest:
        if self.synthetic and self.seed is None:
            raise ValueError("synthetic manifests require a fixed seed")
        if not self.synthetic and self.seed is not None:
            raise ValueError("a seed is meaningful only for synthetic manifests")
        if self.completed_at and self.completed_at < self.started_at:
            raise ValueError("completed_at cannot precede started_at")
        if self.status is ImportStatus.PENDING and self.completed_at is not None:
            raise ValueError("pending imports cannot have completed_at")
        if self.status is not ImportStatus.PENDING and self.completed_at is None:
            raise ValueError("completed imports require completed_at")
        if any(count < 0 for count in self.record_counts.values()):
            raise ValueError("record counts cannot be negative")
        return self


CanonicalClinicalRecord: TypeAlias = (
    Patient
    | Encounter
    | Condition
    | Observation
    | MedicationRequestSummary
    | Allergy
    | ClinicalNote
    | ClinicalAssertion
)
