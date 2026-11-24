import hashlib
import json
from pathlib import Path

from alembic import command
from alembic.config import Config
from mage_med_backend.database import create_sqlite_engine
from mage_med_backend.importing import FhirImportService
from mage_med_backend.importing.text_service import ClinicalTextService
from mage_med_backend.persistence import (
    ClinicalNoteChunkRecord,
    ClinicalNoteRecord,
    EncounterRecord,
    PatientRecord,
)
from mage_med_contracts import NoteContentOrigin, SourceFormat, TextNoteImportStatus
from sqlalchemy import func, select
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[3]
FHIR_FIXTURE = ROOT / "data/synthetic/fhir/r4/synthetic_patient_bundle.json"
TEXT_FIXTURE = ROOT / "data/synthetic/clinical_text/synthetic_notes.json"


def _services(tmp_path: Path, attachment_root: Path | None = None):
    database_path = tmp_path / "clinical-text.db"
    config = Config(ROOT / "apps/backend/alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")
    command.upgrade(config, "head")
    engine = create_sqlite_engine(f"sqlite:///{database_path}")
    fhir = FhirImportService(
        engine,
        max_bytes=1024 * 1024,
        text_import_root=attachment_root,
        max_note_bytes=4096,
        chunk_characters=96,
        chunk_overlap=12,
    )
    text = ClinicalTextService(
        engine,
        max_upload_bytes=1024 * 1024,
        max_note_bytes=4096,
        max_notes=100,
        chunk_characters=96,
        chunk_overlap=12,
    )
    return fhir, text, engine


def _import_structured(fhir: FhirImportService) -> None:
    fhir.import_bytes(
        FHIR_FIXTURE.read_bytes(),
        original_filename=FHIR_FIXTURE.name,
        source_locator="fixture://synthetic_patient_bundle.json",
        dataset_id="mage-med-synthetic-r4",
        synthetic_seed=20261123,
    )


def _linked_payload(engine) -> bytes:
    payload = json.loads(TEXT_FIXTURE.read_text(encoding="utf-8"))
    with Session(engine) as session:
        patient = session.scalar(select(PatientRecord))
        encounter = session.scalar(select(EncounterRecord))
        assert patient is not None and encounter is not None
        for note in payload["notes"]:
            note["patient_id"] = patient.internal_id
            if note.get("encounter_id"):
                note["encounter_id"] = encounter.internal_id
    return json.dumps(payload, sort_keys=True).encode()


def test_retrieve_linked_structured_records_notes_and_exact_chunks(tmp_path: Path) -> None:
    fhir, text, engine = _services(tmp_path)
    _import_structured(fhir)
    report = text.import_bytes(
        _linked_payload(engine),
        source_format=SourceFormat.JSON,
        original_filename=TEXT_FIXTURE.name,
        source_locator="fixture://synthetic_notes.json",
        dataset_id="mage-med-synthetic-clinical-text",
        dataset_version="1.0.0",
        synthetic=True,
        synthetic_seed=20261123,
    )
    assert report.record_counts == {"imported": 4}
    with Session(engine) as session:
        patient = session.scalar(select(PatientRecord))
        assert patient is not None
        patient_id = patient.internal_id
    context = text.get_patient_context(__import__("uuid").UUID(patient_id))
    assert {item.record_type for item in context.structured_records} >= {
        "patient",
        "encounter",
        "condition",
        "observation",
        "medication_request",
        "allergy",
    }
    assert len(context.notes) == 5  # Four direct notes plus embedded FHIR text.
    direct_notes = [
        note for note in context.notes if note.content_origin is NoteContentOrigin.DIRECT_FILE
    ]
    assert len(direct_notes) == 4
    assert all(note.synthetic for note in context.notes)
    combined = "\n".join(note.text for note in direct_notes)
    assert "INTENTIONAL CONFLICT" in combined
    assert "NEGATION TEST" in combined
    assert "OUTDATED TEST DATA" in combined
    for note in context.notes:
        for chunk in note.chunks:
            assert note.text[chunk.start_offset : chunk.end_offset] == chunk.text
            assert hashlib.sha256(chunk.text.encode()).hexdigest() == chunk.sha256
    engine.dispose()


def test_repeat_text_import_is_idempotent(tmp_path: Path) -> None:
    fhir, text, engine = _services(tmp_path)
    _import_structured(fhir)
    content = _linked_payload(engine)
    first = text.import_bytes(
        content,
        source_format=SourceFormat.JSON,
        original_filename="notes.json",
        source_locator="fixture://notes.json",
        synthetic=True,
        synthetic_seed=20261123,
    )
    replay = text.import_bytes(
        content,
        source_format=SourceFormat.JSON,
        original_filename="notes.json",
        source_locator="fixture://notes.json",
        synthetic=True,
        synthetic_seed=20261123,
    )
    assert replay.import_id == first.import_id
    assert replay.idempotent_replay is True
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(ClinicalNoteRecord)) == 5
    engine.dispose()


def test_wrong_patient_mapping_leaves_note_unlinked(tmp_path: Path) -> None:
    fhir, text, engine = _services(tmp_path)
    _import_structured(fhir)
    second_patient = {
        "resourceType": "Patient",
        "id": "second-synthetic-patient",
        "meta": {"tag": [{"code": "SYNTHETIC"}]},
    }
    fhir.import_bytes(
        json.dumps(second_patient).encode(),
        original_filename="second-patient.json",
        source_locator="fixture://second-patient.json",
        dataset_id="mage-med-synthetic-r4",
        synthetic_seed=20261123,
    )
    with Session(engine) as session:
        patients = session.scalars(select(PatientRecord).order_by(PatientRecord.internal_id)).all()
        encounter = session.scalar(select(EncounterRecord))
        assert len(patients) == 2 and encounter is not None
        wrong_patient = next(item for item in patients if item.internal_id != encounter.patient_id)
    payload = {
        "id": "wrong-patient-note",
        "text": "SYNTHETIC wrong-patient mapping test; not clinician-authored.",
        "patient_id": wrong_patient.internal_id,
        "encounter_id": encounter.internal_id,
    }
    report = text.import_bytes(
        json.dumps(payload).encode(),
        source_format=SourceFormat.JSON,
        original_filename="wrong.json",
        source_locator="fixture://wrong.json",
        synthetic=True,
        synthetic_seed=20261123,
    )
    assert report.notes[0].status is TextNoteImportStatus.UNLINKED
    assert report.notes[0].patient_id is None
    assert report.notes[0].issues == ["patient and encounter mappings belong to different patients"]
    with Session(engine) as session:
        note = session.get(ClinicalNoteRecord, str(report.notes[0].note_id))
        assert note is not None and note.patient_id is None and note.encounter_id is None
    engine.dispose()


def test_txt_and_csv_without_verified_mapping_remain_unlinked(tmp_path: Path) -> None:
    _, text, engine = _services(tmp_path)
    for source_format, content in (
        (SourceFormat.TXT, b"SYNTHETIC unlinked TXT note"),
        (SourceFormat.CSV, b"id,note_type,text\ncsv-1,progress,SYNTHETIC unlinked CSV note\n"),
    ):
        report = text.import_bytes(
            content,
            source_format=source_format,
            original_filename=f"note.{source_format.value}",
            source_locator=f"fixture://note.{source_format.value}",
            dataset_id=f"unlinked-{source_format.value}",
            synthetic=True,
            synthetic_seed=20261123,
        )
        assert report.notes[0].status is TextNoteImportStatus.UNLINKED
        assert report.notes[0].patient_id is None
    engine.dispose()


def test_unlinked_note_can_be_linked_only_by_verified_internal_mapping(
    tmp_path: Path,
) -> None:
    fhir, text, engine = _services(tmp_path)
    _import_structured(fhir)
    original = {
        "id": "mapping-transition-note",
        "text": "SYNTHETIC mapping transition note; not clinician-authored.",
    }
    unlinked = text.import_bytes(
        json.dumps(original).encode(),
        source_format=SourceFormat.JSON,
        original_filename="unlinked.json",
        source_locator="fixture://unlinked.json",
        synthetic=True,
        synthetic_seed=20261123,
    )
    assert unlinked.notes[0].status is TextNoteImportStatus.UNLINKED
    with Session(engine) as session:
        patient = session.scalar(select(PatientRecord))
        assert patient is not None
        patient_id = patient.internal_id
    linked_payload = {**original, "patient_id": patient_id}
    linked = text.import_bytes(
        json.dumps(linked_payload).encode(),
        source_format=SourceFormat.JSON,
        original_filename="linked.json",
        source_locator="fixture://linked.json",
        synthetic=True,
        synthetic_seed=20261123,
    )
    assert linked.notes[0].status is TextNoteImportStatus.UPDATED
    assert str(linked.notes[0].patient_id) == patient_id
    with Session(engine) as session:
        note = session.get(ClinicalNoteRecord, str(linked.notes[0].note_id))
        assert note is not None and note.patient_id == patient_id
    engine.dispose()


def test_fhir_document_reference_reads_only_allowlisted_relative_text(tmp_path: Path) -> None:
    attachment_root = tmp_path / "attachments"
    attachment_root.mkdir()
    (attachment_root / "linked.txt").write_text(
        "SYNTHETIC linked FHIR note; not clinician-authored.", encoding="utf-8"
    )
    fhir, _, engine = _services(tmp_path, attachment_root)
    payload = json.loads(FHIR_FIXTURE.read_text(encoding="utf-8"))
    document_reference = payload["entry"][6]["resource"]
    document_reference["content"] = [
        {
            "attachment": {
                "contentType": "text/plain",
                "url": "linked.txt",
                "title": "SYNTHETIC linked note",
            }
        }
    ]
    report = fhir.import_bytes(
        json.dumps(payload).encode(),
        original_filename="linked-bundle.json",
        source_locator="fixture://linked-bundle.json",
        dataset_id="linked-fhir",
        synthetic_seed=20261123,
    )
    outcome = next(item for item in report.resources if item.resource_type == "DocumentReference")
    assert outcome.status.value == "imported"
    with Session(engine) as session:
        note = session.scalar(select(ClinicalNoteRecord))
        assert note is not None
        assert note.content_origin is NoteContentOrigin.FHIR_LOCAL_FILE
        assert note.source_label == "linked.txt"
        assert note.original_text.startswith("SYNTHETIC linked FHIR note")
        assert session.scalar(select(func.count()).select_from(ClinicalNoteChunkRecord)) >= 1
    engine.dispose()
