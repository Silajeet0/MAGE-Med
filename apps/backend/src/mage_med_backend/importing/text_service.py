"""Transactional imports and patient-scoped retrieval for clinical text."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID, uuid4, uuid5

from mage_med_contracts import (
    AssertionType,
    ClinicalNote,
    ClinicalNoteResponse,
    DataModality,
    ImportStatus,
    NoteContentOrigin,
    PatientClinicalContextResponse,
    Provenance,
    SourceFormat,
    SourceReference,
    TextImportReport,
    TextNoteImportOutcome,
    TextNoteImportStatus,
)
from mage_med_ingestion import (
    ClinicalTextError,
    ParsedTextNote,
    chunk_clinical_text,
    clean_clinical_text,
    parse_text_document,
)
from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import Session

from mage_med_backend.clinical_data import ClinicalDataNotFound, ClinicalDataService
from mage_med_backend.persistence import (
    ClinicalNoteChunkRecord,
    ClinicalNoteRecord,
    EncounterRecord,
    ImportManifestRecord,
    PatientRecord,
    SourceArtifactRecord,
)

TEXT_ARTIFACT_NAMESPACE = UUID("104e18e0-16f2-452f-afc4-42fb27e22c0f")
TEXT_NOTE_NAMESPACE = UUID("58cfe063-2254-4528-98bd-fc013b38f251")
DATASET_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,255}$")


class TextImportRejected(ValueError):
    """The clinical text source cannot be safely imported."""


class ClinicalContextNotFound(LookupError):
    """A patient or patient-scoped note was not found."""


def _clinical_times(value: date | datetime | None) -> tuple[datetime | None, date | None]:
    if isinstance(value, datetime):
        return value, None
    return None, value


def _parse_authored_at(value: str | datetime | None) -> datetime | None:
    if value is None or isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ClinicalTextError("authored_at must be an ISO 8601 timestamp") from exc
    if parsed is not None and parsed.tzinfo is None:
        raise ClinicalTextError("authored_at must include a timezone")
    return parsed


class ClinicalTextService:
    """Import local notes and expose patient-scoped source-traceable retrieval."""

    def __init__(
        self,
        engine: Engine,
        *,
        max_upload_bytes: int,
        max_note_bytes: int,
        max_notes: int,
        chunk_characters: int,
        chunk_overlap: int,
    ) -> None:
        self._engine = engine
        self._max_upload_bytes = max_upload_bytes
        self._max_note_bytes = max_note_bytes
        self._max_notes = max_notes
        self._chunk_characters = chunk_characters
        self._chunk_overlap = chunk_overlap

    def import_bytes(
        self,
        content: bytes,
        *,
        source_format: SourceFormat,
        original_filename: str,
        source_locator: str,
        dataset_id: str = "local-clinical-text",
        dataset_version: str = "1",
        synthetic: bool = False,
        synthetic_seed: int | None = None,
        actor_id: str = "local-text-import",
        txt_defaults: dict[str, Any] | None = None,
    ) -> TextImportReport:
        if not content:
            raise TextImportRejected("clinical text input is empty")
        if len(content) > self._max_upload_bytes:
            raise TextImportRejected("clinical text input exceeds the configured size limit")
        if DATASET_ID_PATTERN.fullmatch(dataset_id) is None:
            raise TextImportRejected("dataset_id contains unsupported characters")
        if not dataset_version or len(dataset_version) > 128:
            raise TextImportRejected("dataset_version must contain 1 to 128 characters")
        if synthetic and synthetic_seed is None:
            raise TextImportRejected("synthetic clinical text requires an explicit seed")
        if not synthetic and synthetic_seed is not None:
            raise TextImportRejected("a seed is valid only for synthetic clinical text")
        try:
            raw_content, parsed_notes = parse_text_document(
                content,
                source_format=source_format,
                max_bytes=self._max_upload_bytes,
                max_notes=self._max_notes,
                txt_defaults=txt_defaults,
            )
        except ClinicalTextError as exc:
            raise TextImportRejected(str(exc)) from exc
        if not parsed_notes:
            raise TextImportRejected("clinical text input contains no notes")

        sha256 = hashlib.sha256(content).hexdigest()
        with Session(self._engine) as session:
            existing = self._existing_report(session, sha256)
            if existing:
                return existing

        now = datetime.now(UTC)
        artifact_id = uuid5(TEXT_ARTIFACT_NAMESPACE, sha256)
        manifest_id = uuid4()
        try:
            with Session(self._engine) as session, session.begin():
                existing = self._existing_report(session, sha256)
                if existing:
                    return existing
                artifact = SourceArtifactRecord(
                    internal_id=str(artifact_id),
                    schema_version="1.0.0",
                    modality=DataModality.UNSTRUCTURED_CLINICAL_TEXT,
                    source_format=source_format,
                    source_locator=source_locator,
                    original_filename=original_filename,
                    media_type={
                        SourceFormat.TXT: "text/plain",
                        SourceFormat.CSV: "text/csv",
                        SourceFormat.JSON: "application/json",
                    }[source_format],
                    sha256=sha256,
                    raw_content=raw_content,
                    imported_at=now,
                    synthetic=synthetic,
                )
                manifest = ImportManifestRecord(
                    internal_id=str(manifest_id),
                    schema_version="1.0.0",
                    dataset_id=dataset_id,
                    dataset_version=dataset_version,
                    source_format=source_format,
                    status=ImportStatus.PENDING,
                    source_artifact_ids=[str(artifact_id)],
                    started_at=now,
                    completed_at=None,
                    importer_name="mage-med-clinical-text",
                    importer_version="1.0.0",
                    synthetic=synthetic,
                    seed=synthetic_seed if synthetic else None,
                    record_counts={},
                    errors=[],
                    primary_source_artifact_id=str(artifact_id),
                    validation_summary={
                        "scope": "local_text_structure_encoding_links_and_limits",
                        "model_inference": "not_used",
                    },
                    resource_outcomes=[],
                )
                session.add(artifact)
                session.flush()
                session.add(manifest)
                session.flush()
                outcomes = [
                    self._persist_note(
                        session,
                        parsed,
                        dataset_id=dataset_id,
                        artifact_id=artifact_id,
                        manifest_id=manifest_id,
                        source_locator=source_locator,
                        imported_at=now,
                        actor_id=actor_id,
                        synthetic=synthetic,
                        synthetic_seed=synthetic_seed,
                    )
                    for parsed in parsed_notes
                ]
                counts: dict[str, int] = {}
                for outcome in outcomes:
                    counts[outcome.status.value] = counts.get(outcome.status.value, 0) + 1
                manifest.status = (
                    ImportStatus.SUCCEEDED
                    if any(outcome.note_id for outcome in outcomes)
                    else ImportStatus.FAILED
                )
                manifest.completed_at = datetime.now(UTC)
                manifest.record_counts = counts
                manifest.resource_outcomes = [item.model_dump(mode="json") for item in outcomes]
                manifest.errors = (
                    [] if manifest.status is ImportStatus.SUCCEEDED else ["no notes were imported"]
                )
                session.flush()
                return self._report(manifest, sha256, idempotent_replay=False)
        except TextImportRejected:
            raise
        except Exception as exc:
            raise TextImportRejected(
                "clinical text import transaction failed and was rolled back"
            ) from exc

    def _existing_report(self, session: Session, sha256: str) -> TextImportReport | None:
        artifact = session.scalar(
            select(SourceArtifactRecord).where(SourceArtifactRecord.sha256 == sha256)
        )
        if artifact is None:
            return None
        manifest = session.scalar(
            select(ImportManifestRecord).where(
                ImportManifestRecord.primary_source_artifact_id == artifact.internal_id,
                ImportManifestRecord.importer_name == "mage-med-clinical-text",
            )
        )
        if manifest is None:
            raise TextImportRejected("content checksum is already used by another import type")
        return self._report(manifest, sha256, idempotent_replay=True)

    def _resolve_links(
        self, session: Session, parsed: ParsedTextNote
    ) -> tuple[str | None, str | None, list[str]]:
        issues: list[str] = []
        patient: PatientRecord | None = None
        encounter: EncounterRecord | None = None
        try:
            if parsed.patient_id:
                patient = session.get(PatientRecord, str(UUID(parsed.patient_id)))
                if patient is None:
                    issues.append("patient mapping is unavailable")
            if parsed.encounter_id:
                encounter = session.get(EncounterRecord, str(UUID(parsed.encounter_id)))
                if encounter is None:
                    issues.append("encounter mapping is unavailable")
        except ValueError:
            issues.append("patient or encounter mapping is not a valid internal UUID")
        if issues:
            return None, None, issues
        if patient and encounter and encounter.patient_id != patient.internal_id:
            return None, None, ["patient and encounter mappings belong to different patients"]
        if encounter and patient is None and encounter.patient_id:
            patient = session.get(PatientRecord, encounter.patient_id)
        return (
            patient.internal_id if patient else None,
            encounter.internal_id if encounter else None,
            issues,
        )

    def _persist_note(
        self,
        session: Session,
        parsed: ParsedTextNote,
        *,
        dataset_id: str,
        artifact_id: UUID,
        manifest_id: UUID,
        source_locator: str,
        imported_at: datetime,
        actor_id: str,
        synthetic: bool,
        synthetic_seed: int | None,
    ) -> TextNoteImportOutcome:
        if len(parsed.original_text.encode("utf-8")) > self._max_note_bytes:
            return TextNoteImportOutcome(
                source_id=parsed.source_id,
                status=TextNoteImportStatus.UNUSABLE,
                issues=["note exceeds the configured per-note size limit"],
            )
        try:
            cleaned = clean_clinical_text(parsed.original_text)
            authored_at = _parse_authored_at(parsed.authored_at)
            patient_id, encounter_id, issues = self._resolve_links(session, parsed)
            note_id = uuid5(TEXT_NOTE_NAMESPACE, f"{dataset_id}:{parsed.source_id}")
            note = ClinicalNote(
                internal_id=note_id,
                source_reference=SourceReference(
                    source_artifact_id=artifact_id,
                    source_locator=f"{source_locator}#note/{parsed.source_id}",
                    resource_type="ClinicalNote",
                    resource_id=parsed.source_id,
                ),
                patient_id=UUID(patient_id) if patient_id else None,
                encounter_id=UUID(encounter_id) if encounter_id else None,
                event_time=authored_at,
                recorded_time=authored_at,
                imported_at=imported_at,
                provenance=Provenance(
                    import_manifest_id=manifest_id,
                    importer_name="mage-med-clinical-text",
                    importer_version="1.0.0",
                    transformation_version="1.0.0",
                    run_id=manifest_id,
                    actor_id=actor_id,
                    synthetic=synthetic,
                    seed=synthetic_seed if synthetic else None,
                ),
                assertion_type=AssertionType.OBSERVED,
                note_type=parsed.note_type,
                title=parsed.title,
                original_text=parsed.original_text,
                text=cleaned,
                authored_at=authored_at,
                author_reference=parsed.author_reference,
                source_label=parsed.source_label,
                content_origin=NoteContentOrigin.DIRECT_FILE,
            )
        except (ClinicalTextError, ValueError) as exc:
            return TextNoteImportOutcome(
                source_id=parsed.source_id,
                status=TextNoteImportStatus.UNUSABLE,
                issues=[str(exc)],
            )
        existing = session.get(ClinicalNoteRecord, str(note_id))
        event_time, event_date = _clinical_times(note.event_time)
        session.merge(
            ClinicalNoteRecord(
                internal_id=str(note.internal_id),
                schema_version=note.schema_version,
                modality=note.modality,
                source_artifact_id=str(artifact_id),
                import_manifest_id=str(manifest_id),
                source_locator=note.source_reference.source_locator,
                source_resource_type="ClinicalNote",
                source_resource_id=parsed.source_id,
                event_time=event_time,
                event_date=event_date,
                recorded_time=note.recorded_time,
                imported_at=note.imported_at,
                assertion_type=note.assertion_type,
                provenance=note.provenance.model_dump(mode="json"),
                patient_id=patient_id,
                encounter_id=encounter_id,
                note_type=note.note_type,
                title=note.title,
                original_text=note.original_text,
                text=note.text,
                authored_at=note.authored_at,
                author_reference=note.author_reference,
                source_label=note.source_label,
                content_origin=note.content_origin,
            )
        )
        session.execute(
            delete(ClinicalNoteChunkRecord).where(ClinicalNoteChunkRecord.note_id == str(note_id))
        )
        chunks = chunk_clinical_text(
            note_id,
            cleaned,
            max_characters=self._chunk_characters,
            overlap_characters=self._chunk_overlap,
            extract_sections=True,
        )
        session.add_all(
            [
                ClinicalNoteChunkRecord(
                    internal_id=str(chunk.internal_id),
                    schema_version=chunk.schema_version,
                    note_id=str(chunk.note_id),
                    chunk_index=chunk.chunk_index,
                    start_offset=chunk.start_offset,
                    end_offset=chunk.end_offset,
                    text=chunk.text,
                    section=chunk.section,
                    sha256=chunk.sha256,
                )
                for chunk in chunks
            ]
        )
        status = (
            TextNoteImportStatus.UNLINKED
            if patient_id is None
            else TextNoteImportStatus.UPDATED
            if existing
            else TextNoteImportStatus.IMPORTED
        )
        return TextNoteImportOutcome(
            source_id=parsed.source_id,
            status=status,
            note_id=note_id,
            patient_id=UUID(patient_id) if patient_id else None,
            encounter_id=UUID(encounter_id) if encounter_id else None,
            chunk_count=len(chunks),
            issues=issues,
        )

    def _report(
        self, manifest: ImportManifestRecord, sha256: str, *, idempotent_replay: bool
    ) -> TextImportReport:
        return TextImportReport(
            import_id=UUID(manifest.internal_id),
            status=manifest.status,
            source_artifact_id=UUID(manifest.primary_source_artifact_id or ""),
            source_sha256=sha256,
            idempotent_replay=idempotent_replay,
            started_at=manifest.started_at,
            completed_at=manifest.completed_at,
            record_counts=manifest.record_counts,
            notes=[
                TextNoteImportOutcome.model_validate(item) for item in manifest.resource_outcomes
            ],
            errors=manifest.errors,
        )

    def get_note(self, patient_id: UUID, note_id: UUID) -> ClinicalNoteResponse:
        try:
            return ClinicalDataService(self._engine).get_note(patient_id, note_id)
        except ClinicalDataNotFound as exc:
            raise ClinicalContextNotFound(str(exc)) from exc

    def get_patient_context(self, patient_id: UUID) -> PatientClinicalContextResponse:
        try:
            return ClinicalDataService(self._engine).get_patient_context(patient_id)
        except ClinicalDataNotFound as exc:
            raise ClinicalContextNotFound(str(exc)) from exc
