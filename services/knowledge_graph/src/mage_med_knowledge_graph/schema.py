"""Idempotent, versioned Neo4j schema migrations for the graph projection."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from neo4j import Driver

from mage_med_knowledge_graph.models import RelationKind


class QueryDriver(Protocol):
    def execute_query(self, query_: str, **kwargs: object) -> object: ...


@dataclass(frozen=True)
class GraphSchemaMigration:
    version: str
    statements: tuple[str, ...]


_NODE_SCHEMA = (
    "CREATE CONSTRAINT mage_graph_entity_id IF NOT EXISTS "
    "FOR (n:GraphEntity) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT mage_patient_id IF NOT EXISTS FOR (n:Patient) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT mage_graph_migration_version IF NOT EXISTS "
    "FOR (n:GraphSchemaMigration) REQUIRE n.version IS UNIQUE",
    "CREATE INDEX mage_temporal_patient_scope IF NOT EXISTS "
    "FOR (n:TemporalPatientTier) ON (n.patient_id)",
    "CREATE INDEX mage_temporal_event_time IF NOT EXISTS "
    "FOR (n:TemporalPatientTier) ON (n.event_time)",
    "CREATE INDEX mage_source_artifact IF NOT EXISTS FOR (n:GraphEntity) ON (n.source_artifact_id)",
    "CREATE INDEX mage_concept_code IF NOT EXISTS FOR (n:ClinicalConcept) ON (n.system, n.code)",
    "CREATE INDEX mage_evidence_document IF NOT EXISTS FOR (n:EvidenceChunk) ON (n.document_id)",
    "CREATE INDEX mage_inference_patient IF NOT EXISTS "
    "FOR (n:NonConfirmedInferenceTier) ON (n.patient_id)",
)

_MILESTONE_9_RELATION_SCHEMA = tuple(
    f"CREATE CONSTRAINT mage_rel_{kind.value.lower()}_id IF NOT EXISTS "
    f"FOR ()-[r:{kind.value}]-() REQUIRE r.id IS UNIQUE"
    for kind in RelationKind
    if kind is not RelationKind.HAS_MEDICATION
)

GRAPH_SCHEMA_MIGRATIONS = (
    GraphSchemaMigration(
        version="0001_multi_tier_graph",
        statements=_NODE_SCHEMA + _MILESTONE_9_RELATION_SCHEMA,
    ),
    GraphSchemaMigration(
        version="0002_patient_projection",
        statements=(
            "CREATE CONSTRAINT mage_rel_has_medication_id IF NOT EXISTS "
            "FOR ()-[r:HAS_MEDICATION]-() REQUIRE r.id IS UNIQUE",
            "CREATE INDEX mage_projection_source IF NOT EXISTS "
            "FOR (n:GraphEntity) ON (n.projection_source)",
        ),
    ),
)


class Neo4jSchemaMigrator:
    """Apply only repository-owned, static schema statements."""

    def __init__(self, driver: Driver | QueryDriver, *, database: str) -> None:
        self._driver = driver
        self._database = database

    def apply(self) -> tuple[str, ...]:
        applied: list[str] = []
        for migration in GRAPH_SCHEMA_MIGRATIONS:
            for statement in migration.statements:
                self._driver.execute_query(statement, database_=self._database)
            self._driver.execute_query(
                "MERGE (m:GraphSchemaMigration {version: $version}) "
                "ON CREATE SET m.applied_at = $applied_at "
                "RETURN m.version AS version",
                parameters_={
                    "version": migration.version,
                    "applied_at": datetime.now(UTC),
                },
                database_=self._database,
            )
            applied.append(migration.version)
        return tuple(applied)
