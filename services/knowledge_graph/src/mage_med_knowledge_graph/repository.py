"""Allowlisted, parameterized Neo4j repository; arbitrary Cypher is not exposed."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol, cast
from uuid import UUID

from neo4j import Driver

from mage_med_knowledge_graph.models import (
    FACT_KINDS,
    PATIENT_SCOPED_KINDS,
    TIER_BY_KIND,
    GraphNode,
    GraphRelation,
    GraphTier,
    NodeKind,
    RelationKind,
)
from mage_med_knowledge_graph.schema import Neo4jSchemaMigrator, QueryDriver

TIER_LABELS: dict[GraphTier, str] = {
    GraphTier.TEMPORAL_PATIENT: "TemporalPatientTier",
    GraphTier.BIOMEDICAL: "BiomedicalConceptTier",
    GraphTier.EVIDENCE_PROVENANCE: "EvidenceProvenanceTier",
    GraphTier.NONCONFIRMED_INFERENCE: "NonConfirmedInferenceTier",
}


class EagerQueryResult(Protocol):
    records: list[Any]


class GraphScopeError(ValueError):
    """A write failed because endpoints were absent or outside patient scope."""


_PATIENT_RELATION_TYPES = "HAS_ENCOUNTER|HAS_OBSERVATION|HAS_CONDITION|HAS_MEDICATION|HAS_NOTE"
_NEIGHBORHOOD_RELATION_TYPES = _PATIENT_RELATION_TYPES + "|MAPS_TO|MENTIONS_CONCEPT|DERIVED_FROM"


def _scope_predicate(alias: str, kind: NodeKind) -> str | None:
    if kind is NodeKind.PATIENT:
        return f"{alias}.id = $patient_id"
    if kind in PATIENT_SCOPED_KINDS:
        return f"{alias}.patient_id = $patient_id"
    return None


def _node_query(kind: NodeKind, tier: GraphTier) -> str:
    assertion_label = ":ClinicalAssertion" if kind in FACT_KINDS else ""
    return (
        f"MERGE (n:GraphEntity:{TIER_LABELS[tier]}:{kind.value}{assertion_label} {{id: $id}}) "
        "ON CREATE SET n.created_at = $updated_at "
        "SET n += $properties, n.schema_version = $schema_version, "
        "n.kind = $kind, n.tier = $tier, n.patient_id = $patient_id, "
        "n.source_artifact_id = $source_artifact_id, n.provenance_id = $provenance_id, "
        "n.event_time = $event_time, n.recorded_time = $recorded_time, "
        "n.imported_at = $imported_at, n.assertion_type = $assertion_type, "
        "n.verification_status = $verification_status, n.updated_at = $updated_at "
        "SET n.confirmation_status = $confirmation_status, "
        "n.clinically_confirmed = $clinically_confirmed "
        "RETURN n.id AS id"
    )


NODE_QUERIES = {kind: _node_query(kind, tier) for kind, tier in TIER_BY_KIND.items()}


def _relation_query(relation: GraphRelation) -> str:
    predicates = [
        predicate
        for predicate in (
            _scope_predicate("a", relation.source_kind),
            _scope_predicate("b", relation.target_kind),
        )
        if predicate is not None
    ]
    where = f" WHERE {' AND '.join(predicates)}" if predicates else ""
    return (
        f"MATCH (a:GraphEntity:{relation.source_kind.value} {{id: $source_id}}), "
        f"(b:GraphEntity:{relation.target_kind.value} {{id: $target_id}})"
        f"{where} "
        f"MERGE (a)-[r:{relation.kind.value} {{id: $id}}]->(b) "
        "ON CREATE SET r.first_created_at = $created_at "
        "SET r += $properties, r.schema_version = $schema_version, "
        "r.patient_id = $patient_id, r.source_artifact_id = $source_artifact_id, "
        "r.provenance_id = $provenance_id, r.assertion_type = $assertion_type, "
        "r.verification_status = $verification_status, r.updated_at = $created_at, "
        "r.causal = $causal, r.confirmation_status = $confirmation_status "
        "RETURN r.id AS id"
    )


def _node_parameters(node: GraphNode) -> dict[str, Any]:
    nonconfirmed = node.kind in {NodeKind.HYPOTHESIS, NodeKind.INFERENCE_RUN}
    return {
        "id": str(node.id),
        "schema_version": node.schema_version,
        "kind": node.kind.value,
        "tier": node.tier.value,
        "patient_id": str(node.patient_id) if node.patient_id else None,
        "source_artifact_id": str(node.source_artifact_id),
        "provenance_id": str(node.provenance_id),
        "event_time": node.event_time,
        "recorded_time": node.recorded_time,
        "imported_at": node.imported_at,
        "assertion_type": node.assertion_type.value,
        "verification_status": node.verification_status.value,
        "updated_at": node.imported_at,
        "confirmation_status": "nonconfirmed" if nonconfirmed else None,
        "clinically_confirmed": False if nonconfirmed else None,
        "properties": node.properties,
    }


def _relationship_parameters(relationship: GraphRelation) -> dict[str, Any]:
    nonconfirmed = relationship.kind in {
        RelationKind.SUPPORTED_BY,
        RelationKind.CONTRADICTED_BY,
    }
    return {
        "id": str(relationship.id),
        "source_id": str(relationship.source_id),
        "target_id": str(relationship.target_id),
        "schema_version": relationship.schema_version,
        "patient_id": str(relationship.patient_id) if relationship.patient_id else None,
        "source_artifact_id": str(relationship.source_artifact_id),
        "provenance_id": str(relationship.provenance_id),
        "created_at": relationship.created_at,
        "assertion_type": relationship.assertion_type.value,
        "verification_status": relationship.verification_status.value,
        "causal": False,
        "confirmation_status": "nonconfirmed" if nonconfirmed else None,
        "properties": relationship.properties,
    }


class Neo4jGraphRepository:
    """Bounded graph writes and patient reads through fixed templates only."""

    def __init__(self, driver: Driver | QueryDriver, *, database: str) -> None:
        self._driver = driver
        self._database = database

    def initialize_schema(self) -> tuple[str, ...]:
        return Neo4jSchemaMigrator(self._driver, database=self._database).apply()

    def upsert_node(self, node: GraphNode) -> str:
        result = cast(
            EagerQueryResult,
            self._driver.execute_query(
                NODE_QUERIES[node.kind],
                parameters_=_node_parameters(node),
                database_=self._database,
            ),
        )
        if not result.records:
            raise GraphScopeError("graph node upsert returned no record")
        return str(result.records[0]["id"])

    def upsert_relationship(self, relationship: GraphRelation) -> str:
        result = cast(
            EagerQueryResult,
            self._driver.execute_query(
                _relation_query(relationship),
                parameters_=_relationship_parameters(relationship),
                database_=self._database,
            ),
        )
        if not result.records:
            raise GraphScopeError(
                "relationship endpoints were absent or outside the explicit patient scope"
            )
        return str(result.records[0]["id"])

    def replace_patient_projection(
        self,
        patient_id: UUID,
        nodes: list[GraphNode],
        relationships: list[GraphRelation],
    ) -> None:
        """Atomically replace one patient's canonical SQLite-derived projection."""

        self._validate_projection(nodes, relationships, allowed_patients={patient_id})

        def replace(tx: Any) -> None:
            tx.run(
                "MATCH (n:TemporalPatientTier {patient_id: $patient_id}) DETACH DELETE n",
                {"patient_id": str(patient_id)},
            ).consume()
            self._write_projection(tx, nodes, relationships)
            self._remove_orphan_projection_metadata(tx)

        driver = cast(Any, self._driver)
        with driver.session(database=self._database) as session:
            session.execute_write(replace)

    def replace_all_patient_projections(
        self, nodes: list[GraphNode], relationships: list[GraphRelation]
    ) -> None:
        """Atomically rebuild only canonical patient projections, preserving other tiers."""

        self._validate_projection(nodes, relationships, allowed_patients=None)

        def replace(tx: Any) -> None:
            tx.run("MATCH (n:TemporalPatientTier) DETACH DELETE n").consume()
            self._write_projection(tx, nodes, relationships)
            self._remove_orphan_projection_metadata(tx)

        driver = cast(Any, self._driver)
        with driver.session(database=self._database) as session:
            session.execute_write(replace)

    @staticmethod
    def _validate_projection(
        nodes: list[GraphNode],
        relationships: list[GraphRelation],
        *,
        allowed_patients: set[UUID] | None,
    ) -> None:
        node_ids = {node.id for node in nodes}
        if len(node_ids) != len(nodes):
            raise GraphScopeError("projection contains duplicate node IDs")
        patient_nodes = {node.id for node in nodes if node.kind is NodeKind.PATIENT}
        scoped_patients = {
            node.patient_id
            for node in nodes
            if node.kind in PATIENT_SCOPED_KINDS and node.patient_id is not None
        }
        if patient_nodes != scoped_patients:
            raise GraphScopeError("every projected patient scope requires exactly one Patient node")
        if allowed_patients is not None and scoped_patients != allowed_patients:
            raise GraphScopeError("projection contains a patient outside the replacement scope")
        if any(node.properties.get("projection_source") != "sqlite" for node in nodes):
            raise GraphScopeError(
                "canonical projection nodes must declare projection_source=sqlite"
            )
        for relationship in relationships:
            if relationship.source_id not in node_ids or relationship.target_id not in node_ids:
                raise GraphScopeError("projection relationship endpoint is not in the node set")
            if (
                allowed_patients is not None
                and relationship.patient_id is not None
                and relationship.patient_id not in allowed_patients
            ):
                raise GraphScopeError("relationship is outside the replacement patient scope")

    @staticmethod
    def _write_projection(
        tx: Any, nodes: list[GraphNode], relationships: list[GraphRelation]
    ) -> None:
        for node in nodes:
            record = tx.run(NODE_QUERIES[node.kind], _node_parameters(node)).single(strict=True)
            if record is None:
                raise GraphScopeError("graph node upsert returned no record")
        for relationship in relationships:
            record = tx.run(
                _relation_query(relationship),
                _relationship_parameters(relationship),
            ).single(strict=True)
            if record is None:
                raise GraphScopeError(
                    "relationship endpoints were absent or outside the explicit patient scope"
                )

    @staticmethod
    def _remove_orphan_projection_metadata(tx: Any) -> None:
        tx.run(
            "MATCH (c:ClinicalConcept {projection_source: 'sqlite'}) "
            "WHERE NOT EXISTS { MATCH ()-[:MAPS_TO|MENTIONS_CONCEPT]->(c) } "
            "DETACH DELETE c"
        ).consume()
        tx.run(
            "MATCH (s:SourceArtifact {projection_source: 'sqlite'}) "
            "WHERE NOT EXISTS { MATCH ()-[:DERIVED_FROM]->(s) } DETACH DELETE s"
        ).consume()

    def _require_patient_scope(self, patient_id: UUID) -> None:
        result = cast(
            EagerQueryResult,
            self._driver.execute_query(
                "MATCH (p:Patient {id: $patient_id, patient_id: $patient_id}) RETURN p.id AS id",
                parameters_={"patient_id": str(patient_id)},
                database_=self._database,
            ),
        )
        if not result.records:
            raise GraphScopeError("patient graph scope was not found")

    def _read(self, query: str, parameters: dict[str, Any]) -> list[dict[str, Any]]:
        result = cast(
            EagerQueryResult,
            self._driver.execute_query(
                query,
                parameters_=parameters,
                database_=self._database,
            ),
        )
        return [dict(record) for record in result.records]

    @staticmethod
    def _validate_limit(limit: int) -> None:
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")

    def get_patient_facts(self, patient_id: UUID, *, limit: int = 100) -> list[dict[str, Any]]:
        self._validate_limit(limit)
        self._require_patient_scope(patient_id)
        return self._read(
            "MATCH (p:Patient {id: $patient_id}) "
            f"MATCH path=(p)-[:{_PATIENT_RELATION_TYPES}*1..2]->(f:TemporalPatientTier) "
            "WHERE f.patient_id = $patient_id "
            "RETURN DISTINCT f.id AS id, f.kind AS kind, f.event_time AS event_time, "
            "f.recorded_time AS recorded_time, f.source_artifact_id AS source_artifact_id "
            "ORDER BY event_time DESC, id LIMIT $limit",
            {"patient_id": str(patient_id), "limit": limit},
        )

    def get_patient_neighborhood(
        self, patient_id: UUID, *, limit: int = 100
    ) -> list[dict[str, Any]]:
        self._validate_limit(limit)
        self._require_patient_scope(patient_id)
        return self._read(
            "MATCH (p:Patient {id: $patient_id}) "
            f"MATCH path=(p)-[:{_NEIGHBORHOOD_RELATION_TYPES}*1..3]-(n:GraphEntity) "
            "WHERE all(x IN nodes(path) WHERE x.patient_id = $patient_id "
            "OR x.patient_id IS NULL OR (x:Patient AND x.id = $patient_id)) "
            "RETURN DISTINCT n.id AS id, n.kind AS kind, n.tier AS tier, "
            "n.event_time AS event_time, n.assertion_type AS assertion_type, "
            "n.source_artifact_id AS source_artifact_id "
            "ORDER BY event_time DESC, id LIMIT $limit",
            {"patient_id": str(patient_id), "limit": limit},
        )

    def get_temporal_lab_facts(
        self,
        patient_id: UUID,
        *,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        self._validate_limit(limit)
        self._require_patient_scope(patient_id)
        return self._read(
            "MATCH (o:Observation {patient_id: $patient_id}) "
            "WHERE ($date_from IS NULL OR o.event_time_key >= $date_from) "
            "AND ($date_to IS NULL OR o.event_time_key <= $date_to) "
            "RETURN o.id AS id, o.event_time AS event_time, "
            "o.recorded_time AS recorded_time, o.code_system AS code_system, "
            "o.code AS code, o.display AS display, o.value_quantity AS value_quantity, "
            "o.value_text AS value_text, o.value_unit AS value_unit, "
            "o.data_absent_reason AS data_absent_reason, "
            "o.assertion_type AS assertion_type, o.source_artifact_id AS source_artifact_id "
            "ORDER BY o.event_time_key, o.id LIMIT $limit",
            {
                "patient_id": str(patient_id),
                "date_from": date_from.isoformat() if date_from else None,
                "date_to": date_to.isoformat() if date_to else None,
                "limit": limit,
            },
        )

    def get_condition_history(self, patient_id: UUID, *, limit: int = 100) -> list[dict[str, Any]]:
        self._validate_limit(limit)
        self._require_patient_scope(patient_id)
        return self._read(
            "MATCH (c:Condition {patient_id: $patient_id}) "
            "RETURN c.id AS id, c.event_time AS event_time, c.recorded_time AS recorded_time, "
            "c.code_system AS code_system, c.code AS code, c.display AS display, "
            "c.clinical_status AS clinical_status, c.verification AS verification, "
            "c.assertion_type AS assertion_type, c.source_artifact_id AS source_artifact_id "
            "ORDER BY c.event_time_key, c.id LIMIT $limit",
            {"patient_id": str(patient_id), "limit": limit},
        )

    def get_note_provenance(self, patient_id: UUID, note_id: UUID) -> dict[str, Any]:
        self._require_patient_scope(patient_id)
        records = self._read(
            "MATCH (n:ClinicalNote {id: $note_id, patient_id: $patient_id}) "
            "MATCH (n)-[r:DERIVED_FROM]->(s:SourceArtifact) "
            "WHERE r.patient_id = $patient_id "
            "RETURN n.id AS note_id, n.event_time AS event_time, "
            "n.assertion_type AS assertion_type, s.id AS source_artifact_id, "
            "s.source_locator AS source_locator, s.sha256 AS sha256",
            {"patient_id": str(patient_id), "note_id": str(note_id)},
        )
        if not records:
            raise GraphScopeError("note was not found in the requested patient graph scope")
        return records[0]

    def get_graph_json(
        self, patient_id: UUID, *, limit: int = 200
    ) -> dict[str, list[dict[str, Any]]]:
        self._validate_limit(limit)
        self._require_patient_scope(patient_id)
        records = self._read(
            "MATCH (p:Patient {id: $patient_id}) "
            f"OPTIONAL MATCH path=(p)-[:{_NEIGHBORHOOD_RELATION_TYPES}*1..3]-(n:GraphEntity) "
            "WHERE path IS NULL OR all(x IN nodes(path) WHERE x.patient_id = $patient_id "
            "OR x.patient_id IS NULL OR (x:Patient AND x.id = $patient_id)) "
            "WITH p, collect(DISTINCT n)[..$limit] AS neighbors "
            "WITH [p] + [n IN neighbors WHERE n IS NOT NULL] AS graph_nodes "
            "UNWIND graph_nodes AS a "
            "OPTIONAL MATCH (a)-[r]->(b) WHERE b IN graph_nodes "
            "WITH graph_nodes, collect(DISTINCT CASE WHEN r IS NULL THEN NULL ELSE "
            "{id: r.id, source: a.id, target: b.id, type: type(r), "
            "assertion_type: r.assertion_type} END) AS raw_links "
            "RETURN [n IN graph_nodes | {id: n.id, kind: n.kind, tier: n.tier, "
            "event_time: n.event_time, assertion_type: n.assertion_type, "
            "source_artifact_id: n.source_artifact_id}] AS nodes, "
            "[link IN raw_links WHERE link IS NOT NULL] AS links",
            {"patient_id": str(patient_id), "limit": limit},
        )
        if not records:
            return {"nodes": [], "links": []}
        return {
            "nodes": list(records[0]["nodes"]),
            "links": list(records[0]["links"]),
        }
