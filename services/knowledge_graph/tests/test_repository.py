from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest
from mage_med_contracts import AssertionType
from mage_med_knowledge_graph import (
    GRAPH_SCHEMA_MIGRATIONS,
    GraphNode,
    GraphRelation,
    GraphScopeError,
    Neo4jGraphRepository,
    NodeKind,
    RelationKind,
)

PATIENT_ID = UUID("40000000-0000-4000-8000-000000000001")
OBSERVATION_ID = UUID("40000000-0000-4000-8000-000000000002")
SOURCE_ID = UUID("40000000-0000-4000-8000-000000000003")
PROVENANCE_ID = UUID("40000000-0000-4000-8000-000000000004")
NOW = datetime(2026, 11, 24, tzinfo=UTC)


def _result(record_id: UUID | None) -> SimpleNamespace:
    records = [] if record_id is None else [{"id": str(record_id)}]
    return SimpleNamespace(records=records)


def test_schema_migration_is_static_idempotent_and_versioned() -> None:
    driver = Mock()
    driver.execute_query.return_value = _result(None)
    repository = Neo4jGraphRepository(driver, database="neo4j")

    expected = ("0001_multi_tier_graph", "0002_patient_projection")
    assert repository.initialize_schema() == expected
    assert repository.initialize_schema() == expected

    ddl_count = sum(len(item.statements) for item in GRAPH_SCHEMA_MIGRATIONS)
    calls = driver.execute_query.call_args_list
    assert len(calls) == 2 * (ddl_count + len(GRAPH_SCHEMA_MIGRATIONS))
    ddl_queries = [call.args[0] for call in calls if call.args[0].startswith("CREATE")]
    assert ddl_queries
    assert all("IF NOT EXISTS" in query for query in ddl_queries)
    assert any("GraphEntity" in query and "IS UNIQUE" in query for query in ddl_queries)
    assert any("HAS_OBSERVATION" in query and "IS UNIQUE" in query for query in ddl_queries)


def test_node_upsert_is_allowlisted_parameterized_and_nonconfirmed() -> None:
    driver = Mock()
    hypothesis_id = UUID("41000000-0000-4000-8000-000000000001")
    driver.execute_query.return_value = _result(hypothesis_id)
    repository = Neo4jGraphRepository(driver, database="neo4j")
    node = GraphNode(
        id=hypothesis_id,
        kind=NodeKind.HYPOTHESIS,
        patient_id=PATIENT_ID,
        source_artifact_id=SOURCE_ID,
        provenance_id=PROVENANCE_ID,
        imported_at=NOW,
        assertion_type=AssertionType.HYPOTHESIZED,
        properties={"statement_hash": "synthetic-hash"},
    )

    assert repository.upsert_node(node) == str(hypothesis_id)
    query = driver.execute_query.call_args.args[0]
    parameters = driver.execute_query.call_args.kwargs["parameters_"]
    assert "MERGE (n:GraphEntity:NonConfirmedInferenceTier:Hypothesis" in query
    assert "$id" in query and str(hypothesis_id) not in query
    assert parameters["confirmation_status"] == "nonconfirmed"
    assert parameters["clinically_confirmed"] is False
    assert driver.execute_query.call_args.kwargs["database_"] == "neo4j"
    assert not hasattr(repository, "execute_cypher")


def test_relationship_query_enforces_both_patient_scopes_and_rejects_no_match() -> None:
    driver = Mock()
    driver.execute_query.return_value = _result(None)
    repository = Neo4jGraphRepository(driver, database="neo4j")
    relationship = GraphRelation(
        id=UUID("42000000-0000-4000-8000-000000000001"),
        kind=RelationKind.HAS_OBSERVATION,
        source_id=PATIENT_ID,
        source_kind=NodeKind.PATIENT,
        target_id=OBSERVATION_ID,
        target_kind=NodeKind.OBSERVATION,
        patient_id=PATIENT_ID,
        source_artifact_id=SOURCE_ID,
        provenance_id=PROVENANCE_ID,
        created_at=NOW,
        assertion_type=AssertionType.OBSERVED,
    )

    with pytest.raises(GraphScopeError, match="outside the explicit patient scope"):
        repository.upsert_relationship(relationship)
    query = driver.execute_query.call_args.args[0]
    assert "a.id = $patient_id" in query
    assert "b.patient_id = $patient_id" in query
    assert "HAS_OBSERVATION" in query
    assert str(PATIENT_ID) not in query


def test_patient_fact_read_is_fixed_bounded_and_parameterized() -> None:
    driver = Mock()
    driver.execute_query.return_value = SimpleNamespace(
        records=[{"id": str(OBSERVATION_ID), "kind": "Observation"}]
    )
    repository = Neo4jGraphRepository(driver, database="neo4j")
    driver.execute_query.side_effect = [
        SimpleNamespace(records=[{"id": str(PATIENT_ID)}]),
        SimpleNamespace(records=[{"id": str(OBSERVATION_ID), "kind": "Observation"}]),
    ]
    assert repository.get_patient_facts(PATIENT_ID, limit=25)[0]["kind"] == "Observation"
    query = driver.execute_query.call_args.args[0]
    assert "f.patient_id = $patient_id" in query
    assert driver.execute_query.call_args.kwargs["parameters_"]["limit"] == 25
    with pytest.raises(ValueError, match="between 1 and 500"):
        repository.get_patient_facts(PATIENT_ID, limit=501)


def test_all_read_queries_require_patient_scope_and_use_parameters() -> None:
    driver = Mock()
    repository = Neo4jGraphRepository(driver, database="neo4j")

    driver.execute_query.side_effect = [
        SimpleNamespace(records=[{"id": str(PATIENT_ID)}]),
        SimpleNamespace(records=[{"id": str(OBSERVATION_ID), "kind": "Observation"}]),
    ]
    assert repository.get_patient_neighborhood(PATIENT_ID, limit=10)[0]["kind"] == "Observation"
    neighborhood_call = driver.execute_query.call_args_list[-1]
    assert "$patient_id" in neighborhood_call.args[0]
    assert neighborhood_call.kwargs["parameters_"]["patient_id"] == str(PATIENT_ID)

    driver.execute_query.side_effect = [
        SimpleNamespace(records=[{"id": str(PATIENT_ID)}]),
        SimpleNamespace(records=[{"id": str(OBSERVATION_ID), "code": "4548-4"}]),
    ]
    labs = repository.get_temporal_lab_facts(
        PATIENT_ID,
        date_from=datetime(2026, 1, 1, tzinfo=UTC),
        date_to=datetime(2026, 12, 31, tzinfo=UTC),
    )
    assert labs[0]["code"] == "4548-4"
    lab_parameters = driver.execute_query.call_args_list[-1].kwargs["parameters_"]
    assert lab_parameters["date_from"] == "2026-01-01T00:00:00+00:00"

    driver.execute_query.side_effect = [
        SimpleNamespace(records=[{"id": str(PATIENT_ID)}]),
        SimpleNamespace(records=[{"id": "condition", "code": "44054006"}]),
    ]
    assert repository.get_condition_history(PATIENT_ID)[0]["code"] == "44054006"

    driver.execute_query.side_effect = [
        SimpleNamespace(records=[{"id": str(PATIENT_ID)}]),
        SimpleNamespace(records=[]),
    ]
    with pytest.raises(GraphScopeError, match="note was not found"):
        repository.get_note_provenance(PATIENT_ID, UUID(int=99))

    driver.execute_query.side_effect = [SimpleNamespace(records=[])]
    with pytest.raises(GraphScopeError, match="patient graph scope was not found"):
        repository.get_graph_json(UUID(int=98))
