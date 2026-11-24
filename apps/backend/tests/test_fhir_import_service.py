import copy
import json
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from mage_med_backend.database import create_sqlite_engine
from mage_med_backend.importing import FhirImportRejected, FhirImportService
from mage_med_backend.persistence import (
    ClinicalNoteChunkRecord,
    ClinicalNoteRecord,
    EncounterRecord,
    ImportManifestRecord,
    ObservationRecord,
    PatientRecord,
    SourceArtifactRecord,
    SourceResourceMappingRecord,
)
from mage_med_contracts import ResourceImportStatus
from sqlalchemy import func, select
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[3]
VALID_FIXTURE = ROOT / "data/synthetic/fhir/r4/synthetic_patient_bundle.json"
INVALID_REFERENCE_FIXTURE = ROOT / "data/synthetic/fhir/r4/synthetic_invalid_reference_bundle.json"


def _service(tmp_path: Path) -> tuple[FhirImportService, object]:
    database_path = tmp_path / "fhir-import.db"
    config = Config(ROOT / "apps/backend/alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")
    command.upgrade(config, "head")
    engine = create_sqlite_engine(f"sqlite:///{database_path}")
    return FhirImportService(engine, max_bytes=1024 * 1024), engine


def _count(session: Session, model: type[object]) -> int:
    return session.scalar(select(func.count()).select_from(model)) or 0


def test_import_preserves_relations_units_originals_and_mapping(tmp_path: Path) -> None:
    service, engine = _service(tmp_path)
    report = service.import_bytes(
        VALID_FIXTURE.read_bytes(),
        original_filename=VALID_FIXTURE.name,
        source_locator="fixture://synthetic_patient_bundle.json",
        synthetic_seed=20261123,
    )

    assert report.status.value == "succeeded"
    assert report.record_counts == {"imported": 7}
    assert report.profile_conformance == "not_evaluated"
    with Session(engine) as session:
        patient = session.scalar(select(PatientRecord))
        encounter = session.scalar(select(EncounterRecord))
        observation = session.scalar(select(ObservationRecord))
        note = session.scalar(select(ClinicalNoteRecord))
        mapping = session.scalar(
            select(SourceResourceMappingRecord).where(
                SourceResourceMappingRecord.resource_type == "Observation"
            )
        )
        assert patient is not None
        assert encounter is not None and encounter.patient_id == patient.internal_id
        assert observation is not None
        assert observation.patient_id == patient.internal_id
        assert observation.encounter_id == encounter.internal_id
        assert str(observation.value_quantity) == "7.200000"
        assert observation.value_unit == "%"
        assert observation.reference_range[0]["high"] == "6.5"
        assert note is not None and note.patient_id == patient.internal_id
        assert note.original_text == note.text
        assert _count(session, ClinicalNoteChunkRecord) >= 1
        assert mapping is not None
        assert mapping.original_resource["valueQuantity"]["value"] == 7.2
        assert mapping.normalized_id == observation.internal_id
        assert _count(session, SourceResourceMappingRecord) == 7
    engine.dispose()


def test_repeat_is_idempotent_and_changed_source_updates_without_duplicates(tmp_path: Path) -> None:
    service, engine = _service(tmp_path)
    content = VALID_FIXTURE.read_bytes()
    first = service.import_bytes(
        content,
        original_filename="bundle.json",
        source_locator="fixture://bundle.json",
        synthetic_seed=20261123,
    )
    replay = service.import_bytes(
        content,
        original_filename="bundle.json",
        source_locator="fixture://bundle.json",
        synthetic_seed=20261123,
    )
    assert replay.import_id == first.import_id
    assert replay.idempotent_replay is True

    changed = json.loads(content)
    changed["entry"][3]["resource"]["valueQuantity"]["value"] = 7.4
    updated = service.import_bytes(
        json.dumps(changed, sort_keys=True).encode(),
        original_filename="bundle.json",
        source_locator="fixture://bundle.json",
        synthetic_seed=20261123,
    )
    assert updated.record_counts == {"updated": 7}
    with Session(engine) as session:
        assert _count(session, PatientRecord) == 1
        assert _count(session, ObservationRecord) == 1
        assert _count(session, SourceArtifactRecord) == 2
        assert _count(session, ImportManifestRecord) == 2
        observation = session.scalar(select(ObservationRecord))
        assert observation is not None and str(observation.value_quantity) == "7.400000"
    engine.dispose()


def test_unresolved_reference_is_reported_without_guessing(tmp_path: Path) -> None:
    service, engine = _service(tmp_path)
    report = service.import_bytes(
        INVALID_REFERENCE_FIXTURE.read_bytes(),
        original_filename=INVALID_REFERENCE_FIXTURE.name,
        source_locator="fixture://invalid-reference.json",
        synthetic_seed=20261123,
    )

    outcomes = {item.resource_type: item for item in report.resources}
    assert outcomes["Patient"].status is ResourceImportStatus.IMPORTED
    assert outcomes["Observation"].status is ResourceImportStatus.UNUSABLE
    assert outcomes["Observation"].issues == ["unresolved Patient reference"]
    with Session(engine) as session:
        assert _count(session, PatientRecord) == 1
        assert _count(session, ObservationRecord) == 0
    engine.dispose()


def test_individual_resources_resolve_prior_relative_reference(tmp_path: Path) -> None:
    service, engine = _service(tmp_path)
    bundle = json.loads(VALID_FIXTURE.read_text(encoding="utf-8"))
    patient = bundle["entry"][0]["resource"]
    encounter = copy.deepcopy(bundle["entry"][1]["resource"])
    encounter["subject"]["reference"] = f"Patient/{patient['id']}"

    service.import_bytes(
        json.dumps(patient).encode(),
        original_filename="patient.json",
        source_locator="fixture://patient.json",
        synthetic_seed=20261123,
    )
    report = service.import_bytes(
        json.dumps(encounter).encode(),
        original_filename="encounter.json",
        source_locator="fixture://encounter.json",
        synthetic_seed=20261123,
    )
    assert report.record_counts == {"imported": 1}
    with Session(engine) as session:
        patient_record = session.scalar(select(PatientRecord))
        encounter_record = session.scalar(select(EncounterRecord))
        assert patient_record is not None
        assert encounter_record is not None
        assert encounter_record.patient_id == patient_record.internal_id
    engine.dispose()


def test_transaction_rolls_back_all_rows_on_persistence_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, engine = _service(tmp_path)
    original = service._persist_record
    calls = 0

    def fail_second(session: Session, normalized, manifest_id):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("test-only forced rollback")
        return original(session, normalized, manifest_id)

    monkeypatch.setattr(service, "_persist_record", fail_second)
    with pytest.raises(FhirImportRejected, match="rolled back"):
        service.import_bytes(
            VALID_FIXTURE.read_bytes(),
            original_filename="bundle.json",
            source_locator="fixture://bundle.json",
            synthetic_seed=20261123,
        )
    with Session(engine) as session:
        assert _count(session, SourceArtifactRecord) == 0
        assert _count(session, ImportManifestRecord) == 0
        assert _count(session, PatientRecord) == 0
    engine.dispose()


def test_corrupt_json_is_rejected_without_database_writes(tmp_path: Path) -> None:
    service, engine = _service(tmp_path)
    with pytest.raises(FhirImportRejected, match="not valid JSON"):
        service.import_bytes(
            b"{broken",
            original_filename="broken.json",
            source_locator="fixture://broken.json",
        )
    with Session(engine) as session:
        assert _count(session, SourceArtifactRecord) == 0
    engine.dispose()


def test_unsafe_dataset_namespace_is_rejected_without_writes(tmp_path: Path) -> None:
    service, engine = _service(tmp_path)
    with pytest.raises(FhirImportRejected, match="unsupported characters"):
        service.import_bytes(
            b'{"resourceType":"Patient","id":"patient-1"}',
            original_filename="patient.json",
            source_locator="fixture://patient.json",
            dataset_id="unsafe:namespace",
        )
    with Session(engine) as session:
        assert _count(session, SourceArtifactRecord) == 0
    engine.dispose()


def test_invalid_coding_and_unsupported_resource_are_reported(tmp_path: Path) -> None:
    service, engine = _service(tmp_path)
    payload = json.loads(VALID_FIXTURE.read_text(encoding="utf-8"))
    payload["entry"][2]["resource"]["code"] = {"coding": [{"display": "missing code"}]}
    payload["entry"].append(
        {
            "fullUrl": "urn:uuid:00000000-0000-4000-8000-000000000001",
            "resource": {
                "resourceType": "Procedure",
                "id": "00000000-0000-4000-8000-000000000001",
                "status": "completed",
                "subject": {"reference": payload["entry"][0]["fullUrl"]},
            },
        }
    )
    report = service.import_bytes(
        json.dumps(payload).encode(),
        original_filename="mixed.json",
        source_locator="fixture://mixed.json",
        synthetic_seed=20261123,
    )

    outcomes = {item.resource_type: item for item in report.resources}
    assert outcomes["Condition"].status is ResourceImportStatus.UNUSABLE
    assert outcomes["Condition"].issues == ["coded element has no usable code or text"]
    assert outcomes["Procedure"].status is ResourceImportStatus.UNSUPPORTED
    assert report.record_counts == {"imported": 6, "unusable": 1, "unsupported": 1}
    engine.dispose()


def test_missing_optional_patient_elements_are_accepted(tmp_path: Path) -> None:
    service, engine = _service(tmp_path)
    report = service.import_bytes(
        b'{"resourceType":"Patient","id":"minimal-patient"}',
        original_filename="minimal-patient.json",
        source_locator="fixture://minimal-patient.json",
    )
    assert report.record_counts == {"imported": 1}
    with Session(engine) as session:
        patient = session.scalar(select(PatientRecord))
        assert patient is not None
        assert patient.identifiers == []
        assert patient.family_name is None
        assert patient.birth_date is None
    engine.dispose()


def test_synthetic_source_requires_explicit_seed_without_writes(tmp_path: Path) -> None:
    service, engine = _service(tmp_path)
    with pytest.raises(FhirImportRejected, match="explicit generation seed"):
        service.import_bytes(
            VALID_FIXTURE.read_bytes(),
            original_filename=VALID_FIXTURE.name,
            source_locator="fixture://synthetic-without-seed.json",
        )
    with Session(engine) as session:
        assert _count(session, SourceArtifactRecord) == 0
    engine.dispose()


def test_document_reference_url_is_not_fetched(tmp_path: Path) -> None:
    service, engine = _service(tmp_path)
    payload = json.loads(VALID_FIXTURE.read_text(encoding="utf-8"))
    document_reference = payload["entry"][6]["resource"]
    document_reference["content"] = [
        {"attachment": {"contentType": "text/plain", "url": "https://example.invalid/note"}}
    ]
    report = service.import_bytes(
        json.dumps(payload).encode(),
        original_filename="linked-note.json",
        source_locator="fixture://linked-note.json",
        synthetic_seed=20261123,
    )
    outcome = next(item for item in report.resources if item.resource_type == "DocumentReference")
    assert outcome.status is ResourceImportStatus.UNAVAILABLE
    assert outcome.issues == [
        "unavailable linked DocumentReference: external or non-file attachment URL is unavailable"
    ]
    with Session(engine) as session:
        assert _count(session, ClinicalNoteRecord) == 0
        mapping = session.scalar(
            select(SourceResourceMappingRecord).where(
                SourceResourceMappingRecord.resource_type == "DocumentReference"
            )
        )
        assert mapping is not None
        assert mapping.original_resource["content"][0]["attachment"]["url"] == (
            "https://example.invalid/note"
        )
        assert mapping.issues == outcome.issues
    engine.dispose()


def test_cross_patient_encounter_reference_is_unusable(tmp_path: Path) -> None:
    service, engine = _service(tmp_path)
    payload = json.loads(VALID_FIXTURE.read_text(encoding="utf-8"))
    second_patient = copy.deepcopy(payload["entry"][0])
    second_patient_id = "11111111-1111-4111-8111-111111111111"
    second_patient["fullUrl"] = f"urn:uuid:{second_patient_id}"
    second_patient["resource"]["id"] = second_patient_id
    payload["entry"].append(second_patient)
    payload["entry"][1]["resource"]["subject"]["reference"] = second_patient["fullUrl"]

    report = service.import_bytes(
        json.dumps(payload).encode(),
        original_filename="cross-patient.json",
        source_locator="fixture://cross-patient.json",
        synthetic_seed=20261123,
    )
    observation = next(item for item in report.resources if item.resource_type == "Observation")
    assert observation.status is ResourceImportStatus.UNUSABLE
    assert observation.issues == ["patient and encounter references resolve to different patients"]
    with Session(engine) as session:
        assert _count(session, PatientRecord) == 2
        assert _count(session, ObservationRecord) == 0
    engine.dispose()


def test_failed_encounter_cannot_become_a_reference_target(tmp_path: Path) -> None:
    service, engine = _service(tmp_path)
    payload = json.loads(VALID_FIXTURE.read_text(encoding="utf-8"))
    payload["entry"][1]["resource"]["subject"]["reference"] = "Patient/missing"

    report = service.import_bytes(
        json.dumps(payload).encode(),
        original_filename="bad-encounter.json",
        source_locator="fixture://bad-encounter.json",
        synthetic_seed=20261123,
    )
    encounter = next(item for item in report.resources if item.resource_type == "Encounter")
    observation = next(item for item in report.resources if item.resource_type == "Observation")
    assert encounter.status is ResourceImportStatus.UNUSABLE
    assert encounter.issues == ["unresolved Patient reference"]
    assert observation.status is ResourceImportStatus.UNUSABLE
    assert observation.issues == ["unresolved Encounter reference"]
    with Session(engine) as session:
        assert _count(session, PatientRecord) == 1
        assert _count(session, EncounterRecord) == 0
        assert _count(session, ObservationRecord) == 0
    engine.dispose()


def test_same_fhir_ids_in_different_datasets_do_not_merge(tmp_path: Path) -> None:
    service, engine = _service(tmp_path)
    content = VALID_FIXTURE.read_bytes()
    first = service.import_bytes(
        content,
        original_filename="bundle.json",
        source_locator="fixture://dataset-a.json",
        dataset_id="dataset-a",
        synthetic_seed=20261123,
    )
    changed = json.loads(content)
    changed["entry"][0]["resource"]["name"][0]["family"] = "Different Synthetic Family"
    second = service.import_bytes(
        json.dumps(changed, sort_keys=True).encode(),
        original_filename="bundle.json",
        source_locator="fixture://dataset-b.json",
        dataset_id="dataset-b",
        synthetic_seed=20261123,
    )
    assert second.import_id != first.import_id
    assert second.idempotent_replay is False
    with Session(engine) as session:
        assert _count(session, SourceArtifactRecord) == 2
        assert _count(session, ImportManifestRecord) == 2
        assert _count(session, SourceResourceMappingRecord) == 14
        assert _count(session, PatientRecord) == 2
        assert _count(session, EncounterRecord) == 2
    engine.dispose()


def test_conflicting_observations_are_preserved_as_distinct_sources(tmp_path: Path) -> None:
    service, engine = _service(tmp_path)
    payload = json.loads(VALID_FIXTURE.read_text(encoding="utf-8"))
    conflicting = copy.deepcopy(payload["entry"][3])
    conflicting_id = "22222222-2222-4222-8222-222222222222"
    conflicting["fullUrl"] = f"urn:uuid:{conflicting_id}"
    conflicting["resource"]["id"] = conflicting_id
    conflicting["resource"]["valueQuantity"]["value"] = 6.1
    payload["entry"].append(conflicting)

    report = service.import_bytes(
        json.dumps(payload).encode(),
        original_filename="conflicting-observations.json",
        source_locator="fixture://conflicting-observations.json",
        synthetic_seed=20261123,
    )
    assert report.record_counts == {"imported": 8}
    with Session(engine) as session:
        values = session.scalars(
            select(ObservationRecord.value_quantity).order_by(ObservationRecord.value_quantity)
        ).all()
        assert [str(value) for value in values] == ["6.100000", "7.200000"]
    engine.dispose()
