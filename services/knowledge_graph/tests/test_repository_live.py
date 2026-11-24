import os
from datetime import UTC, datetime
from uuid import UUID

import pytest
from mage_med_contracts import AssertionType
from mage_med_knowledge_graph import (
    GraphNode,
    GraphRelation,
    GraphScopeError,
    Neo4jGraphRepository,
    NodeKind,
    RelationKind,
)
from neo4j import GraphDatabase

pytestmark = pytest.mark.neo4j_smoke


def test_clean_schema_idempotent_upsert_and_cross_patient_denial() -> None:
    if os.getenv("MAGE_MED_RUN_NEO4J_SMOKE") != "1":
        pytest.skip("set MAGE_MED_RUN_NEO4J_SMOKE=1 to run against real Neo4j")
    uri = os.getenv("MAGE_MED_NEO4J_URI", "bolt://localhost:7687")
    username = os.getenv("MAGE_MED_NEO4J_USERNAME", "neo4j")
    password = os.getenv("MAGE_MED_NEO4J_PASSWORD", "mage-med-local")
    database = os.getenv("MAGE_MED_NEO4J_DATABASE", "neo4j")
    patient_a = UUID("50000000-0000-4000-8000-000000000001")
    patient_b = UUID("50000000-0000-4000-8000-000000000002")
    encounter_b = UUID("50000000-0000-4000-8000-000000000003")
    source_id = UUID("50000000-0000-4000-8000-000000000004")
    provenance_id = UUID("50000000-0000-4000-8000-000000000005")
    relation_id = UUID("50000000-0000-4000-8000-000000000006")
    now = datetime(2026, 11, 24, tzinfo=UTC)
    ids = [str(patient_a), str(patient_b), str(encounter_b), str(source_id)]

    with GraphDatabase.driver(uri, auth=(username, password)) as driver:
        repository = Neo4jGraphRepository(driver, database=database)
        try:
            expected = ("0001_multi_tier_graph", "0002_patient_projection")
            assert repository.initialize_schema() == expected
            assert repository.initialize_schema() == expected
            source = GraphNode(
                id=source_id,
                kind=NodeKind.SOURCE_ARTIFACT,
                source_artifact_id=source_id,
                provenance_id=provenance_id,
                imported_at=now,
                assertion_type=AssertionType.OBSERVED,
                properties={"synthetic": True},
            )
            for patient_id in (patient_a, patient_b):
                patient = GraphNode(
                    id=patient_id,
                    kind=NodeKind.PATIENT,
                    patient_id=patient_id,
                    source_artifact_id=source_id,
                    provenance_id=provenance_id,
                    imported_at=now,
                    assertion_type=AssertionType.OBSERVED,
                    properties={"synthetic": True},
                )
                repository.upsert_node(patient)
                repository.upsert_node(patient)
            repository.upsert_node(source)
            encounter = GraphNode(
                id=encounter_b,
                kind=NodeKind.ENCOUNTER,
                patient_id=patient_b,
                source_artifact_id=source_id,
                provenance_id=provenance_id,
                event_time=now,
                imported_at=now,
                assertion_type=AssertionType.OBSERVED,
            )
            repository.upsert_node(encounter)
            wrong_scope = GraphRelation(
                id=relation_id,
                kind=RelationKind.HAS_ENCOUNTER,
                source_id=patient_a,
                source_kind=NodeKind.PATIENT,
                target_id=encounter_b,
                target_kind=NodeKind.ENCOUNTER,
                patient_id=patient_a,
                source_artifact_id=source_id,
                provenance_id=provenance_id,
                created_at=now,
                assertion_type=AssertionType.OBSERVED,
            )
            with pytest.raises(GraphScopeError):
                repository.upsert_relationship(wrong_scope)
            result = driver.execute_query(
                "MATCH (n:GraphEntity) WHERE n.id IN $ids "
                "RETURN n.id AS id, count(*) AS copies ORDER BY id",
                parameters_={"ids": ids},
                database_=database,
            )
            assert len(result.records) == 4
            assert all(record["copies"] == 1 for record in result.records)
            constraints = driver.execute_query(
                "SHOW CONSTRAINTS YIELD name WHERE name STARTS WITH 'mage_' RETURN name",
                database_=database,
            )
            assert len(constraints.records) >= 14
        finally:
            driver.execute_query(
                "MATCH (n:GraphEntity) WHERE n.id IN $ids DETACH DELETE n",
                parameters_={"ids": ids},
                database_=database,
            )
