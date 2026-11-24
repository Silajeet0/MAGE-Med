import os
from pathlib import Path
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from mage_med_backend.database import create_sqlite_engine
from mage_med_backend.graph_sync import GraphSyncService
from mage_med_backend.importing import FhirImportService
from mage_med_knowledge_graph import (
    GraphScopeError,
    Neo4jGraphRepository,
    create_neo4j_driver,
)

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "data/synthetic/fhir/r4/synthetic_patient_bundle.json"

pytestmark = pytest.mark.neo4j_smoke


def test_real_fhir_text_projection_is_idempotent_scoped_and_traceable(
    tmp_path: Path,
) -> None:
    if os.getenv("MAGE_MED_RUN_NEO4J_SMOKE") != "1":
        pytest.skip("set MAGE_MED_RUN_NEO4J_SMOKE=1 to run against real Neo4j")
    database_path = tmp_path / "graph-sync-live.db"
    database_url = f"sqlite:///{database_path}"
    config = Config(ROOT / "apps/backend/alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")
    engine = create_sqlite_engine(database_url)
    imported = FhirImportService(engine, max_bytes=1024 * 1024).import_bytes(
        FIXTURE.read_bytes(),
        original_filename=FIXTURE.name,
        source_locator="fixture://synthetic_patient_bundle.json",
        dataset_id="graph-sync-live",
        synthetic_seed=20261123,
    )
    patient_id = next(
        item.normalized_id for item in imported.resources if item.resource_type == "Patient"
    )
    note_id = next(
        item.normalized_id
        for item in imported.resources
        if item.resource_type == "DocumentReference"
    )
    assert patient_id is not None and note_id is not None

    driver = create_neo4j_driver(
        uri=os.getenv("MAGE_MED_NEO4J_URI", "bolt://localhost:7687"),
        username=os.getenv("MAGE_MED_NEO4J_USERNAME", "neo4j"),
        password=os.getenv("MAGE_MED_NEO4J_PASSWORD", "mage-med-local"),
        timeout_seconds=5.0,
    )
    database = os.getenv("MAGE_MED_NEO4J_DATABASE", "neo4j")
    repository = Neo4jGraphRepository(driver, database=database)
    service = GraphSyncService(engine, repository)
    try:
        first = service.synchronize(rebuild=True)
        second = service.synchronize(rebuild=True)
        assert first.node_count == second.node_count
        assert first.relationship_count == second.relationship_count
        projection, _, _ = service.build_projection()
        count_result = driver.execute_query(
            "MATCH (n:GraphEntity) WHERE n.id IN $ids RETURN count(DISTINCT n) AS node_count",
            parameters_={"ids": [str(item) for item in projection.nodes]},
            database_=database,
        )
        assert count_result.records[0]["node_count"] == second.node_count

        neighborhood = repository.get_patient_neighborhood(patient_id)
        assert {item["kind"] for item in neighborhood}.issuperset(
            {"Encounter", "Observation", "Condition", "Medication", "ClinicalNote"}
        )
        labs = repository.get_temporal_lab_facts(patient_id)
        assert labs[0]["code"] == "4548-4"
        assert labs[0]["value_unit"] == "%"
        conditions = repository.get_condition_history(patient_id)
        assert conditions[0]["code"] == "44054006"
        provenance = repository.get_note_provenance(patient_id, note_id)
        assert provenance["source_artifact_id"] == str(imported.source_artifact_id)
        assert provenance["sha256"] == imported.source_sha256
        graph_json = repository.get_graph_json(patient_id)
        assert any(item["kind"] == "Patient" for item in graph_json["nodes"])
        assert any(item["type"] == "DERIVED_FROM" for item in graph_json["links"])

        wrong_patient = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
        with pytest.raises(GraphScopeError):
            repository.get_patient_neighborhood(wrong_patient)
        with pytest.raises(GraphScopeError):
            repository.get_note_provenance(wrong_patient, note_id)
    finally:
        driver.execute_query(
            "MATCH (n:TemporalPatientTier {patient_id: $patient_id}) DETACH DELETE n",
            parameters_={"patient_id": str(patient_id)},
            database_=database,
        )
        driver.execute_query(
            "MATCH (c:ClinicalConcept {projection_source: 'sqlite'}) "
            "WHERE NOT EXISTS { MATCH ()-[:MAPS_TO|MENTIONS_CONCEPT]->(c) } DETACH DELETE c",
            database_=database,
        )
        driver.execute_query(
            "MATCH (s:SourceArtifact {projection_source: 'sqlite'}) "
            "WHERE NOT EXISTS { MATCH ()-[:DERIVED_FROM]->(s) } DETACH DELETE s",
            database_=database,
        )
        driver.close()
        engine.dispose()
