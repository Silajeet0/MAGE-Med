import copy
import json
from pathlib import Path
from unittest.mock import Mock

from alembic import command
from alembic.config import Config
from mage_med_backend.database import create_sqlite_engine
from mage_med_backend.graph_sync import GraphSyncService
from mage_med_backend.importing import ClinicalTextService, FhirImportService
from mage_med_contracts import AssertionType, SourceFormat
from mage_med_knowledge_graph import NodeKind, RelationKind

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "data/synthetic/fhir/r4/synthetic_patient_bundle.json"


def _database(tmp_path: Path):
    database = tmp_path / "graph-sync.db"
    url = f"sqlite:///{database}"
    config = Config(ROOT / "apps/backend/alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")
    return create_sqlite_engine(url)


def test_projection_is_deterministic_scoped_and_source_traceable(tmp_path: Path) -> None:
    engine = _database(tmp_path)
    importer = FhirImportService(engine, max_bytes=1024 * 1024)
    first = importer.import_bytes(
        FIXTURE.read_bytes(),
        original_filename=FIXTURE.name,
        source_locator="fixture://synthetic_patient_bundle.json",
        dataset_id="graph-sync-primary",
        synthetic_seed=20261123,
    )
    primary_patient = next(
        item.normalized_id for item in first.resources if item.resource_type == "Patient"
    )
    primary_encounter = next(
        item.normalized_id for item in first.resources if item.resource_type == "Encounter"
    )
    assert primary_patient is not None and primary_encounter is not None
    ClinicalTextService(
        engine,
        max_upload_bytes=1024 * 1024,
        max_note_bytes=256 * 1024,
        max_notes=100,
        chunk_characters=1000,
        chunk_overlap=100,
    ).import_bytes(
        b"SYNTHETIC graph projection note; not clinician-authored.",
        source_format=SourceFormat.TXT,
        original_filename="graph-note.txt",
        source_locator="fixture://graph-note.txt",
        dataset_id="graph-sync-text",
        synthetic=True,
        synthetic_seed=20261123,
        txt_defaults={
            "patient_id": str(primary_patient),
            "encounter_id": str(primary_encounter),
            "note_type": "progress",
            "source_label": "SYNTHETIC fixture; not clinician-authored",
            "authored_at": "2026-01-16T10:00:00Z",
        },
    )

    bundle = json.loads(FIXTURE.read_text(encoding="utf-8"))
    second = copy.deepcopy(bundle["entry"][0]["resource"])
    second["id"] = "67777777-7777-4777-8777-777777777777"
    second["identifier"][0]["value"] = "SYNTHETIC-PATIENT-GRAPH-002"
    second["name"] = [{"family": "SYNTHETIC-Graph-Two", "given": ["Test"]}]
    importer.import_bytes(
        json.dumps(second, sort_keys=True).encode(),
        original_filename="second-patient.json",
        source_locator="fixture://second-patient.json",
        dataset_id="graph-sync-secondary",
        synthetic_seed=20261123,
    )

    repository = Mock()
    repository.initialize_schema.return_value = (
        "0001_multi_tier_graph",
        "0002_patient_projection",
    )
    service = GraphSyncService(engine, repository)
    first_report = service.synchronize(rebuild=True)
    first_nodes = repository.replace_all_patient_projections.call_args.args[0]
    first_relations = repository.replace_all_patient_projections.call_args.args[1]

    assert first_report.patient_count == 2
    assert first_report.skipped_allergy_count == 1
    assert {node.kind for node in first_nodes}.issuperset(
        {
            NodeKind.PATIENT,
            NodeKind.ENCOUNTER,
            NodeKind.CONDITION,
            NodeKind.OBSERVATION,
            NodeKind.MEDICATION,
            NodeKind.CLINICAL_NOTE,
            NodeKind.CLINICAL_CONCEPT,
            NodeKind.SOURCE_ARTIFACT,
        }
    )
    patient_nodes = [node for node in first_nodes if node.kind is NodeKind.PATIENT]
    assert len(patient_nodes) == 2
    primary_node = next(node for node in patient_nodes if node.id == primary_patient)
    assert primary_node.properties["identifier_keys"] == [
        "https://mage-med.example/synthetic-patient-id|SYNTHETIC-PATIENT-001"
    ]

    encounters = {node.id: node for node in first_nodes if node.kind is NodeKind.ENCOUNTER}
    facts = [
        node
        for node in first_nodes
        if node.kind
        in {
            NodeKind.OBSERVATION,
            NodeKind.CONDITION,
            NodeKind.MEDICATION,
            NodeKind.CLINICAL_NOTE,
        }
    ]
    note_nodes = [node for node in facts if node.kind is NodeKind.CLINICAL_NOTE]
    assert len(note_nodes) == 2
    assert all(node.assertion_type is AssertionType.OBSERVED for node in note_nodes)
    observation = next(node for node in facts if node.kind is NodeKind.OBSERVATION)
    assert observation.event_time is not None
    assert observation.properties["event_time_key"].startswith("2026-01-15")
    ownership = {
        relation.target_id: relation
        for relation in first_relations
        if relation.kind
        in {
            RelationKind.HAS_OBSERVATION,
            RelationKind.HAS_CONDITION,
            RelationKind.HAS_MEDICATION,
            RelationKind.HAS_NOTE,
        }
    }
    assert all(fact.id in ownership for fact in facts)
    assert all(
        ownership[fact.id].source_id in encounters
        for fact in facts
        if fact.patient_id == primary_patient
    )
    derived_targets = {
        relation.source_id
        for relation in first_relations
        if relation.kind is RelationKind.DERIVED_FROM
        and relation.target_kind is NodeKind.SOURCE_ARTIFACT
    }
    assert all(node.id in derived_targets for node in first_nodes if node.patient_id is not None)
    assert not any(relation.kind is RelationKind.ASSOCIATED_WITH for relation in first_relations)
    mappings = [relation for relation in first_relations if relation.kind is RelationKind.MAPS_TO]
    assert mappings
    assert all(
        relation.properties["mapping_basis"] == "source_supplied_code" for relation in mappings
    )
    assert all(node.properties.get("projection_source") == "sqlite" for node in first_nodes)

    service.synchronize(rebuild=True)
    second_nodes = repository.replace_all_patient_projections.call_args.args[0]
    second_relations = repository.replace_all_patient_projections.call_args.args[1]
    assert [node.id for node in second_nodes] == [node.id for node in first_nodes]
    assert [relation.id for relation in second_relations] == [
        relation.id for relation in first_relations
    ]
    engine.dispose()


def test_patient_only_projection_uses_patient_replacement(tmp_path: Path) -> None:
    engine = _database(tmp_path)
    report = FhirImportService(engine, max_bytes=1024 * 1024).import_bytes(
        FIXTURE.read_bytes(),
        original_filename=FIXTURE.name,
        source_locator="fixture://synthetic_patient_bundle.json",
        dataset_id="graph-sync-one",
        synthetic_seed=20261123,
    )
    patient_id = next(
        item.normalized_id for item in report.resources if item.resource_type == "Patient"
    )
    assert patient_id is not None
    repository = Mock()
    repository.initialize_schema.return_value = (
        "0001_multi_tier_graph",
        "0002_patient_projection",
    )
    result = GraphSyncService(engine, repository).synchronize(patient_id=patient_id)
    assert result.patient_ids == [patient_id]
    repository.replace_patient_projection.assert_called_once()
    assert repository.replace_patient_projection.call_args.args[0] == patient_id
    repository.replace_all_patient_projections.assert_not_called()
    engine.dispose()
