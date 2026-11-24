"""Deterministic SQLite-to-Neo4j projection for canonical patient records."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid5

from mage_med_contracts import AssertionType
from mage_med_knowledge_graph import (
    GraphNode,
    GraphRelation,
    Neo4jGraphRepository,
    NodeKind,
    RelationKind,
)
from pydantic import BaseModel, ConfigDict
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from mage_med_backend.persistence import (
    AllergyRecord,
    ClinicalNoteRecord,
    ConditionRecord,
    EncounterRecord,
    MedicationRequestRecord,
    ObservationRecord,
    PatientRecord,
    SourceArtifactRecord,
)

CONCEPT_NAMESPACE = UUID("0eaed62d-0b3a-4f30-916a-c43f4a9e383e")
RELATION_NAMESPACE = UUID("39abef8f-2040-4705-b48d-ef78cd290803")


class GraphSyncError(RuntimeError):
    """Canonical records cannot be projected without guessing or losing scope."""


class GraphSyncReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: str
    patient_ids: list[UUID]
    patient_count: int
    node_count: int
    relationship_count: int
    source_artifact_count: int
    concept_count: int
    skipped_allergy_count: int
    schema_migrations: list[str]


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _required_aware(value: datetime) -> datetime:
    return _aware(value) or value.replace(tzinfo=UTC)


def _event(record: Any) -> datetime | date | None:
    return cast(datetime | date | None, record.event_time or record.event_date)


def _event_key(value: datetime | date | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return (_aware(value) or value).isoformat()
    return value.isoformat()


def _clean_properties(values: dict[str, Any]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, value in values.items():
        if value is None:
            continue
        if isinstance(value, Decimal):
            output[key] = str(value)
        elif isinstance(value, list) and value and isinstance(value[0], dict):
            output[key] = json.dumps(value, sort_keys=True, separators=(",", ":"))
        else:
            output[key] = value
    return output


def _code_properties(concept: dict[str, Any] | None) -> dict[str, Any]:
    if not concept:
        return {}
    return _clean_properties(
        {
            "code_system": concept.get("system"),
            "code": concept.get("code"),
            "display": concept.get("display"),
            "code_version": concept.get("version"),
            "code_text": concept.get("text"),
        }
    )


def _status_code(concept: dict[str, Any] | None) -> str | None:
    if not concept:
        return None
    return concept.get("code") or concept.get("text")


def _relation_id(kind: RelationKind, source_id: UUID, target_id: UUID, provenance_id: UUID) -> UUID:
    return uuid5(
        RELATION_NAMESPACE,
        f"{kind.value}|{source_id}|{target_id}|{provenance_id}",
    )


class _Projection:
    def __init__(self) -> None:
        self.nodes: dict[UUID, GraphNode] = {}
        self.relationships: dict[UUID, GraphRelation] = {}

    def add_node(self, node: GraphNode) -> None:
        existing = self.nodes.get(node.id)
        if existing is not None and existing.kind is not node.kind:
            raise GraphSyncError(f"stable graph ID {node.id} maps to multiple node kinds")
        if existing is None:
            self.nodes[node.id] = node

    def add_relation(self, relation: GraphRelation) -> None:
        existing = self.relationships.get(relation.id)
        if existing is not None and (
            existing.source_id != relation.source_id or existing.target_id != relation.target_id
        ):
            raise GraphSyncError(f"stable graph relationship ID {relation.id} is ambiguous")
        self.relationships[relation.id] = relation


class GraphSyncService:
    """Build and atomically replace Neo4j projections from canonical SQLite rows."""

    def __init__(self, engine: Engine, repository: Neo4jGraphRepository) -> None:
        self._engine = engine
        self._repository = repository

    def synchronize(
        self, *, patient_id: UUID | None = None, rebuild: bool = False
    ) -> GraphSyncReport:
        migrations = self._repository.initialize_schema()
        projection, patient_ids, skipped_allergies = self.build_projection(patient_id=patient_id)
        nodes = sorted(projection.nodes.values(), key=lambda item: (item.kind.value, str(item.id)))
        relationships = sorted(
            projection.relationships.values(), key=lambda item: (item.kind.value, str(item.id))
        )
        if patient_id is None:
            self._repository.replace_all_patient_projections(nodes, relationships)
            mode = "rebuild_all" if rebuild else "synchronize_all"
        else:
            self._repository.replace_patient_projection(patient_id, nodes, relationships)
            mode = "rebuild_patient" if rebuild else "synchronize_patient"
        return GraphSyncReport(
            mode=mode,
            patient_ids=patient_ids,
            patient_count=len(patient_ids),
            node_count=len(nodes),
            relationship_count=len(relationships),
            source_artifact_count=sum(node.kind is NodeKind.SOURCE_ARTIFACT for node in nodes),
            concept_count=sum(node.kind is NodeKind.CLINICAL_CONCEPT for node in nodes),
            skipped_allergy_count=skipped_allergies,
            schema_migrations=list(migrations),
        )

    def build_projection(
        self, *, patient_id: UUID | None = None
    ) -> tuple[_Projection, list[UUID], int]:
        projection = _Projection()
        with Session(self._engine) as session:
            query = select(PatientRecord).order_by(PatientRecord.internal_id)
            if patient_id is not None:
                query = query.where(PatientRecord.internal_id == str(patient_id))
            patients = list(session.scalars(query).all())
            if patient_id is not None and not patients:
                raise GraphSyncError("canonical patient was not found in SQLite")
            for patient in patients:
                self._project_patient(session, projection, patient)
            patient_ids = [UUID(patient.internal_id) for patient in patients]
            skipped_allergies = sum(
                session.scalar(
                    select(func.count())
                    .select_from(AllergyRecord)
                    .where(AllergyRecord.patient_id == patient.internal_id)
                )
                or 0
                for patient in patients
            )
        return projection, patient_ids, skipped_allergies

    def _project_patient(
        self, session: Session, projection: _Projection, patient: PatientRecord
    ) -> None:
        patient_node = self._clinical_node(
            session,
            patient,
            NodeKind.PATIENT,
            properties={
                "identifier_keys": [
                    f"{item.get('system') or ''}|{item['value']}" for item in patient.identifiers
                ],
                "birth_date": patient.birth_date,
                "administrative_gender": patient.administrative_gender,
                "active": patient.active,
            },
        )
        projection.add_node(patient_node)
        self._attach_source(session, projection, patient_node, patient)

        encounters = list(
            session.scalars(
                select(EncounterRecord)
                .where(EncounterRecord.patient_id == patient.internal_id)
                .order_by(EncounterRecord.internal_id)
            ).all()
        )
        encounter_ids = {item.internal_id for item in encounters}
        for encounter in encounters:
            node = self._clinical_node(
                session,
                encounter,
                NodeKind.ENCOUNTER,
                properties={
                    "status": encounter.status,
                    "period_start": _aware(encounter.period_start),
                    "period_end": _aware(encounter.period_end),
                    **_code_properties(encounter.encounter_type or encounter.class_code),
                },
            )
            projection.add_node(node)
            self._add_patient_edge(projection, patient_node, node, RelationKind.HAS_ENCOUNTER)
            self._attach_source(session, projection, node, encounter)

        record_groups: tuple[tuple[type[Any], NodeKind, RelationKind], ...] = (
            (ObservationRecord, NodeKind.OBSERVATION, RelationKind.HAS_OBSERVATION),
            (ConditionRecord, NodeKind.CONDITION, RelationKind.HAS_CONDITION),
            (MedicationRequestRecord, NodeKind.MEDICATION, RelationKind.HAS_MEDICATION),
            (ClinicalNoteRecord, NodeKind.CLINICAL_NOTE, RelationKind.HAS_NOTE),
        )
        for model, kind, relation_kind in record_groups:
            records = session.scalars(
                select(model)
                .where(model.patient_id == patient.internal_id)
                .order_by(model.internal_id)
            ).all()
            for record in records:
                node = self._fact_node(session, record, kind)
                projection.add_node(node)
                if record.encounter_id:
                    if record.encounter_id not in encounter_ids:
                        raise GraphSyncError(
                            f"{kind.value} {record.internal_id} references an encounter "
                            "outside its canonical patient scope"
                        )
                    owner = projection.nodes[UUID(record.encounter_id)]
                else:
                    owner = patient_node
                self._add_patient_edge(projection, owner, node, relation_kind)
                self._attach_source(session, projection, node, record)
                if kind in {NodeKind.OBSERVATION, NodeKind.CONDITION, NodeKind.MEDICATION}:
                    concept = (
                        record.code
                        if kind in {NodeKind.OBSERVATION, NodeKind.CONDITION}
                        else record.medication
                    )
                    self._attach_direct_source_concept(session, projection, node, record, concept)

    def _clinical_node(
        self,
        session: Session,
        record: Any,
        kind: NodeKind,
        *,
        properties: dict[str, Any],
    ) -> GraphNode:
        self._require_artifact(session, record.source_artifact_id)
        event_time = _event(record)
        return GraphNode(
            id=UUID(record.internal_id),
            kind=kind,
            patient_id=(
                UUID(record.internal_id) if kind is NodeKind.PATIENT else UUID(record.patient_id)
            ),
            source_artifact_id=UUID(record.source_artifact_id),
            provenance_id=UUID(record.import_manifest_id),
            event_time=_aware(event_time) if isinstance(event_time, datetime) else event_time,
            recorded_time=_aware(record.recorded_time),
            imported_at=_required_aware(record.imported_at),
            assertion_type=record.assertion_type,
            properties=_clean_properties(
                {
                    "projection_source": "sqlite",
                    "source_locator": record.source_locator,
                    "source_resource_type": record.source_resource_type,
                    "source_resource_id": record.source_resource_id,
                    "event_time_key": _event_key(event_time),
                    **properties,
                }
            ),
        )

    def _fact_node(self, session: Session, record: Any, kind: NodeKind) -> GraphNode:
        properties: dict[str, Any]
        if kind is NodeKind.OBSERVATION:
            properties = {
                "status": record.status,
                **_code_properties(record.code),
                "value_quantity": record.value_quantity,
                "value_text": record.value_text,
                "value_unit": record.value_unit,
                "value_unit_system": record.value_unit_system,
                "value_unit_code": record.value_unit_code,
                "data_absent_reason": _status_code(record.data_absent_reason),
                "reference_range_json": record.reference_range,
            }
        elif kind is NodeKind.CONDITION:
            properties = {
                **_code_properties(record.code),
                "clinical_status": _status_code(record.clinical_status),
                "verification": _status_code(record.verification_status),
                "abatement_time": _aware(record.abatement_time),
                "abatement_date": record.abatement_date,
            }
        elif kind is NodeKind.MEDICATION:
            properties = {
                **_code_properties(record.medication),
                "status": record.status,
                "intent": record.intent,
                "authored_on": _aware(record.authored_on),
                "dosage_text": record.dosage_text,
            }
        else:
            properties = {
                "note_type": record.note_type.value,
                "content_origin": record.content_origin.value,
                "authored_at": _aware(record.authored_at),
                "content_sha256": hashlib.sha256(record.original_text.encode("utf-8")).hexdigest(),
            }
        return self._clinical_node(session, record, kind, properties=properties)

    def _require_artifact(self, session: Session, artifact_id: str) -> SourceArtifactRecord:
        artifact = session.get(SourceArtifactRecord, artifact_id)
        if artifact is None:
            raise GraphSyncError(f"source artifact {artifact_id} is missing")
        return artifact

    def _source_node(self, artifact: SourceArtifactRecord) -> GraphNode:
        artifact_id = UUID(artifact.internal_id)
        return GraphNode(
            id=artifact_id,
            kind=NodeKind.SOURCE_ARTIFACT,
            source_artifact_id=artifact_id,
            provenance_id=artifact_id,
            imported_at=_required_aware(artifact.imported_at),
            assertion_type=AssertionType.OBSERVED,
            properties=_clean_properties(
                {
                    "projection_source": "sqlite",
                    "source_locator": artifact.source_locator,
                    "source_format": artifact.source_format.value,
                    "media_type": artifact.media_type,
                    "sha256": artifact.sha256,
                    "synthetic": artifact.synthetic,
                }
            ),
        )

    def _attach_source(
        self, session: Session, projection: _Projection, node: GraphNode, record: Any
    ) -> None:
        artifact = self._require_artifact(session, record.source_artifact_id)
        source = self._source_node(artifact)
        projection.add_node(source)
        relation = GraphRelation(
            id=_relation_id(
                RelationKind.DERIVED_FROM,
                node.id,
                source.id,
                UUID(record.import_manifest_id),
            ),
            kind=RelationKind.DERIVED_FROM,
            source_id=node.id,
            source_kind=node.kind,
            target_id=source.id,
            target_kind=NodeKind.SOURCE_ARTIFACT,
            patient_id=node.patient_id,
            source_artifact_id=source.id,
            provenance_id=UUID(record.import_manifest_id),
            created_at=node.imported_at,
            assertion_type=node.assertion_type,
            properties={"projection_source": "sqlite"},
        )
        projection.add_relation(relation)

    def _add_patient_edge(
        self,
        projection: _Projection,
        owner: GraphNode,
        target: GraphNode,
        kind: RelationKind,
    ) -> None:
        relation = GraphRelation(
            id=_relation_id(kind, owner.id, target.id, target.provenance_id),
            kind=kind,
            source_id=owner.id,
            source_kind=owner.kind,
            target_id=target.id,
            target_kind=target.kind,
            patient_id=target.patient_id,
            source_artifact_id=target.source_artifact_id,
            provenance_id=target.provenance_id,
            created_at=target.imported_at,
            assertion_type=target.assertion_type,
            properties={"projection_source": "sqlite"},
        )
        projection.add_relation(relation)

    def _attach_direct_source_concept(
        self,
        session: Session,
        projection: _Projection,
        fact: GraphNode,
        record: Any,
        concept: dict[str, Any],
    ) -> None:
        system = concept.get("system")
        code = concept.get("code")
        if not system or not code:
            return
        concept_id = uuid5(
            CONCEPT_NAMESPACE,
            f"{system}|{code}|{concept.get('version') or ''}",
        )
        concept_node = GraphNode(
            id=concept_id,
            kind=NodeKind.CLINICAL_CONCEPT,
            source_artifact_id=fact.source_artifact_id,
            provenance_id=fact.provenance_id,
            imported_at=fact.imported_at,
            assertion_type=AssertionType.OBSERVED,
            properties=_clean_properties(
                {
                    "projection_source": "sqlite",
                    "system": system,
                    "code": code,
                    "display": concept.get("display"),
                    "version": concept.get("version"),
                    "mapping_basis": "source_supplied_code",
                }
            ),
        )
        projection.add_node(concept_node)
        mapping = GraphRelation(
            id=_relation_id(RelationKind.MAPS_TO, fact.id, concept_id, fact.provenance_id),
            kind=RelationKind.MAPS_TO,
            source_id=fact.id,
            source_kind=fact.kind,
            target_id=concept_id,
            target_kind=NodeKind.CLINICAL_CONCEPT,
            patient_id=fact.patient_id,
            source_artifact_id=fact.source_artifact_id,
            provenance_id=fact.provenance_id,
            created_at=fact.imported_at,
            assertion_type=fact.assertion_type,
            properties={
                "projection_source": "sqlite",
                "mapping_basis": "source_supplied_code",
            },
        )
        projection.add_relation(mapping)
        artifact = self._require_artifact(session, record.source_artifact_id)
        source = self._source_node(artifact)
        projection.add_node(source)
        concept_source = GraphRelation(
            id=_relation_id(
                RelationKind.DERIVED_FROM,
                concept_id,
                source.id,
                fact.provenance_id,
            ),
            kind=RelationKind.DERIVED_FROM,
            source_id=concept_id,
            source_kind=NodeKind.CLINICAL_CONCEPT,
            target_id=source.id,
            target_kind=NodeKind.SOURCE_ARTIFACT,
            source_artifact_id=source.id,
            provenance_id=fact.provenance_id,
            created_at=fact.imported_at,
            assertion_type=AssertionType.OBSERVED,
            properties={"projection_source": "sqlite"},
        )
        projection.add_relation(concept_source)
