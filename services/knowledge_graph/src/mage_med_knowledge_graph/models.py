"""Validated write contracts for the bounded multi-tier clinical graph."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from mage_med_contracts import AssertionType, VerificationStatus
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

GRAPH_SCHEMA_VERSION = "1.0.0"


class GraphTier(StrEnum):
    TEMPORAL_PATIENT = "temporal_patient_facts"
    BIOMEDICAL = "biomedical_concepts"
    EVIDENCE_PROVENANCE = "evidence_reference_provenance"
    NONCONFIRMED_INFERENCE = "nonconfirmed_hypotheses_inference_runs"


class NodeKind(StrEnum):
    PATIENT = "Patient"
    ENCOUNTER = "Encounter"
    CONDITION = "Condition"
    OBSERVATION = "Observation"
    MEDICATION = "Medication"
    CLINICAL_NOTE = "ClinicalNote"
    CLINICAL_CONCEPT = "ClinicalConcept"
    EVIDENCE_DOCUMENT = "EvidenceDocument"
    EVIDENCE_CHUNK = "EvidenceChunk"
    SOURCE_ARTIFACT = "SourceArtifact"
    HYPOTHESIS = "Hypothesis"
    INFERENCE_RUN = "InferenceRun"


class RelationKind(StrEnum):
    HAS_ENCOUNTER = "HAS_ENCOUNTER"
    HAS_OBSERVATION = "HAS_OBSERVATION"
    HAS_CONDITION = "HAS_CONDITION"
    HAS_MEDICATION = "HAS_MEDICATION"
    HAS_NOTE = "HAS_NOTE"
    MENTIONS_CONCEPT = "MENTIONS_CONCEPT"
    MAPS_TO = "MAPS_TO"
    ASSOCIATED_WITH = "ASSOCIATED_WITH"
    SUPPORTED_BY = "SUPPORTED_BY"
    CONTRADICTED_BY = "CONTRADICTED_BY"
    DERIVED_FROM = "DERIVED_FROM"


TIER_BY_KIND: dict[NodeKind, GraphTier] = {
    NodeKind.PATIENT: GraphTier.TEMPORAL_PATIENT,
    NodeKind.ENCOUNTER: GraphTier.TEMPORAL_PATIENT,
    NodeKind.CONDITION: GraphTier.TEMPORAL_PATIENT,
    NodeKind.OBSERVATION: GraphTier.TEMPORAL_PATIENT,
    NodeKind.MEDICATION: GraphTier.TEMPORAL_PATIENT,
    NodeKind.CLINICAL_NOTE: GraphTier.TEMPORAL_PATIENT,
    NodeKind.CLINICAL_CONCEPT: GraphTier.BIOMEDICAL,
    NodeKind.EVIDENCE_DOCUMENT: GraphTier.EVIDENCE_PROVENANCE,
    NodeKind.EVIDENCE_CHUNK: GraphTier.EVIDENCE_PROVENANCE,
    NodeKind.SOURCE_ARTIFACT: GraphTier.EVIDENCE_PROVENANCE,
    NodeKind.HYPOTHESIS: GraphTier.NONCONFIRMED_INFERENCE,
    NodeKind.INFERENCE_RUN: GraphTier.NONCONFIRMED_INFERENCE,
}

PATIENT_SCOPED_KINDS = frozenset(
    {
        NodeKind.PATIENT,
        NodeKind.ENCOUNTER,
        NodeKind.CONDITION,
        NodeKind.OBSERVATION,
        NodeKind.MEDICATION,
        NodeKind.CLINICAL_NOTE,
        NodeKind.HYPOTHESIS,
        NodeKind.INFERENCE_RUN,
    }
)

FACT_KINDS = frozenset(
    {
        NodeKind.ENCOUNTER,
        NodeKind.CONDITION,
        NodeKind.OBSERVATION,
        NodeKind.MEDICATION,
        NodeKind.CLINICAL_NOTE,
    }
)

RELATION_ENDPOINTS: dict[RelationKind, set[tuple[NodeKind, NodeKind]]] = {
    RelationKind.HAS_ENCOUNTER: {(NodeKind.PATIENT, NodeKind.ENCOUNTER)},
    RelationKind.HAS_OBSERVATION: {
        (NodeKind.PATIENT, NodeKind.OBSERVATION),
        (NodeKind.ENCOUNTER, NodeKind.OBSERVATION),
    },
    RelationKind.HAS_CONDITION: {
        (NodeKind.PATIENT, NodeKind.CONDITION),
        (NodeKind.ENCOUNTER, NodeKind.CONDITION),
    },
    RelationKind.HAS_MEDICATION: {
        (NodeKind.PATIENT, NodeKind.MEDICATION),
        (NodeKind.ENCOUNTER, NodeKind.MEDICATION),
    },
    RelationKind.HAS_NOTE: {
        (NodeKind.PATIENT, NodeKind.CLINICAL_NOTE),
        (NodeKind.ENCOUNTER, NodeKind.CLINICAL_NOTE),
    },
    RelationKind.MENTIONS_CONCEPT: {
        (NodeKind.CONDITION, NodeKind.CLINICAL_CONCEPT),
        (NodeKind.OBSERVATION, NodeKind.CLINICAL_CONCEPT),
        (NodeKind.MEDICATION, NodeKind.CLINICAL_CONCEPT),
        (NodeKind.CLINICAL_NOTE, NodeKind.CLINICAL_CONCEPT),
        (NodeKind.EVIDENCE_CHUNK, NodeKind.CLINICAL_CONCEPT),
    },
    RelationKind.MAPS_TO: {
        (NodeKind.CONDITION, NodeKind.CLINICAL_CONCEPT),
        (NodeKind.OBSERVATION, NodeKind.CLINICAL_CONCEPT),
        (NodeKind.MEDICATION, NodeKind.CLINICAL_CONCEPT),
    },
    RelationKind.ASSOCIATED_WITH: {(NodeKind.CLINICAL_CONCEPT, NodeKind.CLINICAL_CONCEPT)},
    RelationKind.SUPPORTED_BY: {(NodeKind.HYPOTHESIS, NodeKind.EVIDENCE_CHUNK)},
    RelationKind.CONTRADICTED_BY: {(NodeKind.HYPOTHESIS, NodeKind.EVIDENCE_CHUNK)},
    RelationKind.DERIVED_FROM: {
        (kind, NodeKind.SOURCE_ARTIFACT)
        for kind in NodeKind
        if kind is not NodeKind.SOURCE_ARTIFACT
    }
    | {(NodeKind.HYPOTHESIS, NodeKind.INFERENCE_RUN)},
}

RESERVED_PROPERTIES = frozenset(
    {
        "id",
        "kind",
        "tier",
        "schema_version",
        "patient_id",
        "source_artifact_id",
        "provenance_id",
        "event_time",
        "recorded_time",
        "imported_at",
        "created_at",
        "updated_at",
        "assertion_type",
        "verification_status",
        "confirmation_status",
        "clinically_confirmed",
        "causal",
    }
)


def _aware(value: datetime | None, field_name: str) -> datetime | None:
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise ValueError(f"{field_name} must include a UTC offset")
    return value


def _validate_properties(properties: dict[str, Any]) -> dict[str, Any]:
    reserved = RESERVED_PROPERTIES.intersection(properties)
    if reserved:
        raise ValueError(f"reserved graph properties cannot be overridden: {sorted(reserved)}")
    for key, value in properties.items():
        if not key or not key.replace("_", "").isalnum():
            raise ValueError(f"invalid graph property name: {key!r}")
        values = value if isinstance(value, list) else [value]
        if isinstance(value, dict) or any(
            isinstance(item, (dict, list, tuple, set)) for item in values
        ):
            raise ValueError("graph properties must be scalar values or flat scalar lists")
        if any(
            item is not None and not isinstance(item, (str, int, float, bool, date, datetime))
            for item in values
        ):
            raise ValueError("graph property contains an unsupported value type")
    return properties


class GraphNode(BaseModel):
    """A provenance-bearing graph projection node, never the operational truth."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    schema_version: str = GRAPH_SCHEMA_VERSION
    id: UUID
    kind: NodeKind
    patient_id: UUID | None = None
    source_artifact_id: UUID
    provenance_id: UUID
    event_time: datetime | date | None = None
    recorded_time: datetime | None = None
    imported_at: datetime
    assertion_type: AssertionType
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    properties: dict[str, Any] = Field(default_factory=dict)

    @field_validator("recorded_time", "imported_at")
    @classmethod
    def validate_datetimes(cls, value: datetime | None, info: Any) -> datetime | None:
        return _aware(value, info.field_name)

    @field_validator("event_time")
    @classmethod
    def validate_event_time(cls, value: datetime | date | None) -> datetime | date | None:
        if isinstance(value, datetime):
            _aware(value, "event_time")
        return value

    @field_validator("properties")
    @classmethod
    def validate_properties(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _validate_properties(value)

    @model_validator(mode="after")
    def validate_semantics(self) -> GraphNode:
        if self.kind in PATIENT_SCOPED_KINDS and self.patient_id is None:
            raise ValueError(f"{self.kind.value} requires explicit patient scope")
        if self.kind not in PATIENT_SCOPED_KINDS and self.patient_id is not None:
            raise ValueError(f"{self.kind.value} cannot carry patient scope")
        if self.kind is NodeKind.PATIENT and self.patient_id != self.id:
            raise ValueError("Patient patient_id must equal its stable node id")
        if self.kind in {NodeKind.HYPOTHESIS, NodeKind.INFERENCE_RUN}:
            if self.assertion_type not in {
                AssertionType.MODEL_INFERRED,
                AssertionType.HYPOTHESIZED,
            }:
                raise ValueError("inference-tier nodes must be model_inferred or hypothesized")
            if self.verification_status is not VerificationStatus.UNVERIFIED:
                raise ValueError("inference-tier nodes must remain unverified/nonconfirmed")
        if (
            self.kind is NodeKind.CLINICAL_CONCEPT
            and self.assertion_type is AssertionType.EXTRACTED
            and self.verification_status is not VerificationStatus.UNVERIFIED
        ):
            raise ValueError("automatically extracted concepts must remain unverified")
        return self

    @property
    def tier(self) -> GraphTier:
        return TIER_BY_KIND[self.kind]


class GraphRelation(BaseModel):
    """A stable, provenance-bearing edge with allowlisted endpoints."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    schema_version: str = GRAPH_SCHEMA_VERSION
    id: UUID
    kind: RelationKind
    source_id: UUID
    source_kind: NodeKind
    target_id: UUID
    target_kind: NodeKind
    patient_id: UUID | None = None
    source_artifact_id: UUID
    provenance_id: UUID
    created_at: datetime
    assertion_type: AssertionType
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    properties: dict[str, Any] = Field(default_factory=dict)

    @field_validator("created_at")
    @classmethod
    def validate_created_at(cls, value: datetime) -> datetime:
        return _aware(value, "created_at")  # type: ignore[return-value]

    @field_validator("properties")
    @classmethod
    def validate_properties(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _validate_properties(value)

    @model_validator(mode="after")
    def validate_semantics(self) -> GraphRelation:
        endpoints = (self.source_kind, self.target_kind)
        if endpoints not in RELATION_ENDPOINTS[self.kind]:
            raise ValueError(
                f"{self.kind.value} does not allow "
                f"{self.source_kind.value}->{self.target_kind.value}"
            )
        scoped = (
            self.source_kind in PATIENT_SCOPED_KINDS or self.target_kind in PATIENT_SCOPED_KINDS
        )
        if scoped and self.patient_id is None:
            raise ValueError("patient-related edges require explicit patient scope")
        if not scoped and self.patient_id is not None:
            raise ValueError("reference-only edges cannot carry patient scope")
        if self.kind is RelationKind.ASSOCIATED_WITH and self.properties.get("causal") is True:
            raise ValueError("graph association must never be represented as causation")
        if self.kind in {RelationKind.SUPPORTED_BY, RelationKind.CONTRADICTED_BY}:
            if self.assertion_type not in {
                AssertionType.MODEL_INFERRED,
                AssertionType.HYPOTHESIZED,
            }:
                raise ValueError("hypothesis evidence edges must remain inferred/hypothesized")
            if self.verification_status is not VerificationStatus.UNVERIFIED:
                raise ValueError("hypothesis evidence edges must remain unverified")
        return self
