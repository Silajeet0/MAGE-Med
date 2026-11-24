"""Read-only patient-centric access over the canonical SQLite clinical store."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, time
from typing import Any, cast
from uuid import UUID

from mage_med_contracts import (
    ClinicalNoteResponse,
    CodeableConcept,
    DataQualityIssue,
    DataQualityReport,
    Identifier,
    ImportDiagnostic,
    NoteChunkResponse,
    NotePage,
    NoteReference,
    ObservationPage,
    ObservationView,
    PageInfo,
    PatientClinicalContextResponse,
    PatientDetail,
    PatientPage,
    PatientSummary,
    ReferenceRange,
    SourceLink,
    SourceMappingView,
    SourceProvenance,
    SourceRecordReference,
    StructuredRecordSummary,
    TimelineDetails,
    TimelineEntry,
    TimelinePage,
    TimelineRecordType,
    ValueState,
)
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from mage_med_backend.persistence import (
    AllergyRecord,
    ClinicalNoteChunkRecord,
    ClinicalNoteRecord,
    ConditionRecord,
    EncounterRecord,
    ImportManifestRecord,
    MedicationRequestRecord,
    ObservationRecord,
    PatientRecord,
    SourceArtifactRecord,
    SourceResourceMappingRecord,
)

FACT_MODELS = (
    EncounterRecord,
    ConditionRecord,
    ObservationRecord,
    MedicationRequestRecord,
    AllergyRecord,
    ClinicalNoteRecord,
)
RECORD_TYPE_BY_MODEL = {
    EncounterRecord: "encounter",
    ConditionRecord: "condition",
    ObservationRecord: "observation",
    MedicationRequestRecord: "medication_request",
    AllergyRecord: "allergy",
    ClinicalNoteRecord: "clinical_note",
}
EXPLICIT_NEGATIVE_TEXT = frozenset({"negative", "not detected", "absent"})


class ClinicalDataNotFound(LookupError):
    """A patient-scoped resource was not found or was outside the requested scope."""


def _source(record: Any) -> SourceLink:
    patient_id = (
        record.internal_id
        if isinstance(record, PatientRecord)
        else getattr(record, "patient_id", None)
    )
    scope_query = f"?patient_id={patient_id}" if patient_id else ""
    return SourceLink(
        source_artifact_id=record.source_artifact_id,
        source_locator=record.source_locator,
        resource_type=record.source_resource_type,
        resource_id=record.source_resource_id,
        provenance_href=f"/api/v1/sources/{record.source_artifact_id}{scope_query}",
    )


def _event_value(record: Any) -> datetime | date | None:
    return cast(datetime | date | None, record.event_time or record.event_date)


def _uuid(value: str | None) -> UUID | None:
    return UUID(value) if value is not None else None


def _sort_value(record: Any) -> tuple[datetime, str]:
    event = _event_value(record)
    if isinstance(event, datetime):
        value = event
    elif isinstance(event, date):
        value = datetime.combine(event, time.min)
    elif record.recorded_time is not None:
        value = record.recorded_time
    else:
        value = record.imported_at
    if value.tzinfo is not None:
        value = value.astimezone(UTC).replace(tzinfo=None)
    return value, record.internal_id


def _sort_basis(record: Any) -> str:
    if _event_value(record) is not None:
        return "clinical_event_time"
    if record.recorded_time is not None:
        return "recorded_time_fallback"
    return "import_time_fallback"


def _concept(value: dict[str, Any] | None) -> CodeableConcept | None:
    return CodeableConcept.model_validate(value) if value else None


def _ranges(values: list[dict[str, Any]]) -> list[ReferenceRange]:
    return [ReferenceRange.model_validate(value) for value in values]


def _value_state(record: Any) -> ValueState:
    if isinstance(record, ObservationRecord):
        if record.data_absent_reason is not None:
            return ValueState.MISSING
        if record.value_text and record.value_text.strip().casefold() in EXPLICIT_NEGATIVE_TEXT:
            return ValueState.OBSERVED_NEGATIVE
    return ValueState.OBSERVED


def _missing_fields(record: Any) -> list[str]:
    missing: list[str] = []
    if _event_value(record) is None:
        missing.append("event_time")
    if record.recorded_time is None:
        missing.append("recorded_time")
    if getattr(record, "encounter_id", None) is None and not isinstance(record, EncounterRecord):
        missing.append("encounter_link")
    return missing


def _in_time_window(record: Any, start: date | None, end: date | None) -> bool:
    value = _event_value(record)
    if value is None:
        return start is None and end is None
    day = value.date() if isinstance(value, datetime) else value
    return (start is None or day >= start) and (end is None or day <= end)


class ClinicalDataService:
    """The sole domain layer used by patient and provenance API routes."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def list_patients(
        self, *, page: int, page_size: int, scoped_patient_id: UUID | None = None
    ) -> PatientPage:
        with Session(self._engine) as session:
            query = select(PatientRecord)
            count_query = select(func.count()).select_from(PatientRecord)
            if scoped_patient_id is not None:
                clause = PatientRecord.internal_id == str(scoped_patient_id)
                query = query.where(clause)
                count_query = count_query.where(clause)
            total = session.scalar(count_query) or 0
            records = session.scalars(
                query.order_by(PatientRecord.family_name, PatientRecord.internal_id)
                .offset((page - 1) * page_size)
                .limit(page_size)
            ).all()
            return PatientPage(
                items=[self._patient_summary(item) for item in records],
                page=PageInfo(page=page, page_size=page_size, total=total),
            )

    def get_patient(self, patient_id: UUID) -> PatientDetail:
        with Session(self._engine) as session:
            patient = self._require_patient(session, patient_id)
            summary = self._patient_summary(patient)
            return PatientDetail.model_validate(
                {
                    **summary.model_dump(),
                    "encounter_count": self._count(session, EncounterRecord, patient_id),
                    "condition_count": self._count(session, ConditionRecord, patient_id),
                    "observation_count": self._count(session, ObservationRecord, patient_id),
                    "medication_request_count": self._count(
                        session, MedicationRequestRecord, patient_id
                    ),
                    "allergy_count": self._count(session, AllergyRecord, patient_id),
                    "note_count": self._count(session, ClinicalNoteRecord, patient_id),
                }
            )

    def get_timeline(
        self,
        patient_id: UUID,
        *,
        page: int,
        page_size: int,
        record_types: set[TimelineRecordType] | None = None,
        encounter_id: UUID | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        descending: bool = True,
    ) -> TimelinePage:
        with Session(self._engine) as session:
            self._require_patient(session, patient_id)
            if encounter_id is not None:
                encounter = session.get(EncounterRecord, str(encounter_id))
                if encounter is None or encounter.patient_id != str(patient_id):
                    raise ClinicalDataNotFound("encounter is not in the requested patient scope")
            records: list[Any] = []
            for model, record_type in (
                (EncounterRecord, TimelineRecordType.ENCOUNTER),
                (ConditionRecord, TimelineRecordType.CONDITION),
                (ObservationRecord, TimelineRecordType.OBSERVATION),
                (MedicationRequestRecord, TimelineRecordType.MEDICATION_REQUEST),
                (AllergyRecord, TimelineRecordType.ALLERGY),
                (ClinicalNoteRecord, TimelineRecordType.CLINICAL_NOTE),
            ):
                if record_types and record_type not in record_types:
                    continue
                query = select(model).where(model.patient_id == str(patient_id))
                if encounter_id is not None:
                    if model is EncounterRecord:
                        query = query.where(model.internal_id == str(encounter_id))
                    else:
                        query = query.where(cast(Any, model).encounter_id == str(encounter_id))
                records.extend(session.scalars(query).all())
            records = [item for item in records if _in_time_window(item, date_from, date_to)]
            records.sort(key=_sort_value, reverse=descending)
            total = len(records)
            selected = records[(page - 1) * page_size : page * page_size]
            return TimelinePage(
                patient_id=patient_id,
                items=[self._timeline_entry(session, item, patient_id) for item in selected],
                page=PageInfo(page=page, page_size=page_size, total=total),
            )

    def get_observations(
        self,
        patient_id: UUID,
        *,
        page: int,
        page_size: int,
        code: str | None = None,
        status: str | None = None,
        encounter_id: UUID | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> ObservationPage:
        with Session(self._engine) as session:
            self._require_patient(session, patient_id)
            records = list(
                session.scalars(
                    select(ObservationRecord).where(ObservationRecord.patient_id == str(patient_id))
                ).all()
            )
            if code:
                records = [item for item in records if item.code.get("code") == code]
            if status:
                records = [item for item in records if item.status == status]
            if encounter_id:
                records = [item for item in records if item.encounter_id == str(encounter_id)]
            records = [item for item in records if _in_time_window(item, date_from, date_to)]
            records.sort(key=_sort_value, reverse=True)
            total = len(records)
            selected = records[(page - 1) * page_size : page * page_size]
            return ObservationPage(
                patient_id=patient_id,
                items=[self._observation(item, patient_id) for item in selected],
                page=PageInfo(page=page, page_size=page_size, total=total),
            )

    def get_notes(
        self,
        patient_id: UUID,
        *,
        page: int,
        page_size: int,
        note_type: str | None = None,
        encounter_id: UUID | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> NotePage:
        with Session(self._engine) as session:
            self._require_patient(session, patient_id)
            records = list(
                session.scalars(
                    select(ClinicalNoteRecord).where(
                        ClinicalNoteRecord.patient_id == str(patient_id)
                    )
                ).all()
            )
            if note_type:
                records = [item for item in records if item.note_type.value == note_type]
            if encounter_id:
                records = [item for item in records if item.encounter_id == str(encounter_id)]
            records = [item for item in records if _in_time_window(item, date_from, date_to)]
            records.sort(key=_sort_value, reverse=True)
            total = len(records)
            selected = records[(page - 1) * page_size : page * page_size]
            items = []
            for record in selected:
                chunk_count = (
                    session.scalar(
                        select(func.count())
                        .select_from(ClinicalNoteChunkRecord)
                        .where(ClinicalNoteChunkRecord.note_id == record.internal_id)
                    )
                    or 0
                )
                items.append(
                    NoteReference(
                        note_id=UUID(record.internal_id),
                        patient_id=patient_id,
                        encounter_id=_uuid(record.encounter_id),
                        note_type=record.note_type,
                        title=record.title,
                        authored_at=record.authored_at,
                        recorded_time=record.recorded_time,
                        imported_at=record.imported_at,
                        author_reference=record.author_reference,
                        source_label=record.source_label,
                        content_origin=record.content_origin,
                        chunk_count=chunk_count,
                        source=_source(record),
                    )
                )
            return NotePage(
                patient_id=patient_id,
                items=items,
                page=PageInfo(page=page, page_size=page_size, total=total),
            )

    def get_note(self, patient_id: UUID, note_id: UUID) -> ClinicalNoteResponse:
        with Session(self._engine) as session:
            self._require_patient(session, patient_id)
            note = session.get(ClinicalNoteRecord, str(note_id))
            if note is None or note.patient_id != str(patient_id):
                raise ClinicalDataNotFound("patient-scoped clinical note not found")
            return self._full_note(session, note)

    def get_patient_context(self, patient_id: UUID) -> PatientClinicalContextResponse:
        with Session(self._engine) as session:
            patient = self._require_patient(session, patient_id)
            summaries = [
                StructuredRecordSummary(
                    record_id=UUID(patient.internal_id),
                    record_type="patient",
                    source_artifact_id=UUID(patient.source_artifact_id),
                    source_locator=patient.source_locator,
                )
            ]
            for model in FACT_MODELS[:-1]:
                records = session.scalars(
                    select(model).where(model.patient_id == str(patient_id))
                ).all()
                summaries.extend(
                    StructuredRecordSummary(
                        record_id=UUID(record.internal_id),
                        record_type=RECORD_TYPE_BY_MODEL[model],
                        encounter_id=_uuid(
                            record.internal_id
                            if isinstance(record, EncounterRecord)
                            else cast(Any, record).encounter_id
                        ),
                        event_time=record.event_time,
                        source_artifact_id=UUID(record.source_artifact_id),
                        source_locator=record.source_locator,
                    )
                    for record in records
                )
            notes = session.scalars(
                select(ClinicalNoteRecord)
                .where(ClinicalNoteRecord.patient_id == str(patient_id))
                .order_by(ClinicalNoteRecord.authored_at, ClinicalNoteRecord.internal_id)
            ).all()
            return PatientClinicalContextResponse(
                patient_id=patient_id,
                structured_records=summaries,
                notes=[self._full_note(session, note) for note in notes],
            )

    def get_source(
        self, source_id: UUID, *, patient_id: UUID, include_content: bool = False
    ) -> SourceProvenance:
        with Session(self._engine) as session:
            self._require_patient(session, patient_id)
            artifact = session.get(SourceArtifactRecord, str(source_id))
            if artifact is None or not self._source_in_scope(
                session, artifact.internal_id, patient_id
            ):
                raise ClinicalDataNotFound("source is not in the requested patient scope")
            manifest = session.scalar(
                select(ImportManifestRecord).where(
                    ImportManifestRecord.primary_source_artifact_id == artifact.internal_id
                )
            )
            mappings = list(
                session.scalars(
                    select(SourceResourceMappingRecord).where(
                        SourceResourceMappingRecord.source_artifact_id == artifact.internal_id
                    )
                ).all()
            )
            normalized = self._source_records(session, artifact.internal_id, patient_id)
            allowed_normalized_ids = {str(item.record_id) for item in normalized}
            mappings = [item for item in mappings if item.normalized_id in allowed_normalized_ids]
            if include_content and self._artifact_patient_ids(session, artifact.internal_id) != {
                str(patient_id)
            }:
                raise ClinicalDataNotFound(
                    "raw source spans multiple patient scopes and cannot be returned"
                )
            duplicate_mappings = len(mappings) - len(
                {
                    (item.normalized_type, item.normalized_id)
                    for item in mappings
                    if item.normalized_id
                }
            )
            diagnostic = None
            if manifest is not None:
                diagnostic = ImportDiagnostic(
                    manifest_id=UUID(manifest.internal_id),
                    dataset_id=manifest.dataset_id,
                    dataset_version=manifest.dataset_version,
                    status=manifest.status,
                    importer_name=manifest.importer_name,
                    importer_version=manifest.importer_version,
                    record_counts=manifest.record_counts,
                    idempotency_key=artifact.sha256,
                    duplicate_normalized_mappings=max(duplicate_mappings, 0),
                    replay_attempts_persisted=False,
                )
            return SourceProvenance(
                source_artifact_id=UUID(artifact.internal_id),
                source_format=artifact.source_format,
                source_locator=artifact.source_locator,
                original_filename=artifact.original_filename,
                media_type=artifact.media_type,
                sha256=artifact.sha256,
                imported_at=artifact.imported_at,
                synthetic=artifact.synthetic,
                raw_content=artifact.raw_content if include_content else None,
                import_diagnostic=diagnostic,
                mappings=[
                    SourceMappingView(
                        source_key=item.source_key,
                        resource_type=item.resource_type,
                        resource_id=item.resource_id,
                        normalized_type=item.normalized_type,
                        normalized_id=_uuid(item.normalized_id),
                        outcome_status=item.outcome_status.value,
                        issues=item.issues,
                    )
                    for item in mappings
                ],
                normalized_records=normalized,
            )

    def data_quality_report(self, dataset_id: str | None = None) -> DataQualityReport:
        with Session(self._engine) as session:
            manifest_ids: set[str] | None = None
            artifact_ids: set[str] | None = None
            if dataset_id is not None:
                manifests = list(
                    session.scalars(
                        select(ImportManifestRecord).where(
                            ImportManifestRecord.dataset_id == dataset_id
                        )
                    ).all()
                )
                manifest_ids = {item.internal_id for item in manifests}
                artifact_ids = {
                    source_id for item in manifests for source_id in item.source_artifact_ids
                }
            rows = self._quality_rows(session, manifest_ids)
            issues = [
                self._missing_links(rows),
                self._ambiguous_identifiers(rows),
                self._unsupported_types(session, artifact_ids),
                self._notes_without_text(rows),
                self._temporal_anomalies(rows),
                self._terminology_and_unit_issues(rows),
                self._contradictory_observations(rows),
                self._duplicate_mappings(session, artifact_ids),
            ]
            generated = datetime.now(UTC)
            lines = [
                "MAGE-Med data quality report",
                f"Generated: {generated.isoformat()}",
                f"Dataset: {dataset_id or 'all datasets'}",
                "",
            ]
            for issue in issues:
                lines.append(f"- {issue.category}: {issue.count}")
                lines.extend(f"  example: {example}" for example in issue.examples)
            lines.extend(
                [
                    "",
                    "Interpretation: missing data is not an observed negative finding. "
                    "Counts are integrity diagnostics, not clinical conclusions.",
                ]
            )
            return DataQualityReport(
                generated_at=generated,
                dataset_id=dataset_id,
                issues=issues,
                human_readable="\n".join(lines),
            )

    @staticmethod
    def _require_patient(session: Session, patient_id: UUID) -> PatientRecord:
        patient = session.get(PatientRecord, str(patient_id))
        if patient is None:
            raise ClinicalDataNotFound("patient was not found")
        return patient

    @staticmethod
    def _count(session: Session, model: Any, patient_id: UUID) -> int:
        return (
            session.scalar(
                select(func.count()).select_from(model).where(model.patient_id == str(patient_id))
            )
            or 0
        )

    @staticmethod
    def _patient_summary(patient: PatientRecord) -> PatientSummary:
        return PatientSummary(
            patient_id=UUID(patient.internal_id),
            identifiers=[Identifier.model_validate(item) for item in patient.identifiers],
            family_name=patient.family_name,
            given_names=patient.given_names,
            birth_date=patient.birth_date,
            administrative_gender=patient.administrative_gender,
            active=patient.active,
            imported_at=patient.imported_at,
            source=_source(patient),
        )

    @staticmethod
    def _observation(record: ObservationRecord, patient_id: UUID) -> ObservationView:
        return ObservationView(
            observation_id=UUID(record.internal_id),
            patient_id=patient_id,
            encounter_id=_uuid(record.encounter_id),
            event_time=_event_value(record),
            recorded_time=record.recorded_time,
            imported_at=record.imported_at,
            assertion_type=record.assertion_type,
            code=cast(CodeableConcept, _concept(record.code)),
            status=record.status,
            value_quantity=record.value_quantity,
            value_unit=record.value_unit,
            value_unit_system=record.value_unit_system,
            value_unit_code=record.value_unit_code,
            value_text=record.value_text,
            data_absent_reason=_concept(record.data_absent_reason),
            reference_range=_ranges(record.reference_range),
            value_state=_value_state(record),
            source=_source(record),
        )

    @staticmethod
    def _full_note(session: Session, note: ClinicalNoteRecord) -> ClinicalNoteResponse:
        artifact = session.get(SourceArtifactRecord, note.source_artifact_id)
        if artifact is None:
            raise ClinicalDataNotFound("clinical note source artifact not found")
        chunks = session.scalars(
            select(ClinicalNoteChunkRecord)
            .where(ClinicalNoteChunkRecord.note_id == note.internal_id)
            .order_by(ClinicalNoteChunkRecord.chunk_index)
        ).all()
        return ClinicalNoteResponse(
            note_id=UUID(note.internal_id),
            patient_id=_uuid(note.patient_id),
            encounter_id=_uuid(note.encounter_id),
            note_type=note.note_type,
            title=note.title,
            original_text=note.original_text,
            text=note.text,
            authored_at=note.authored_at,
            author_reference=note.author_reference,
            source_label=note.source_label,
            content_origin=note.content_origin,
            source_artifact_id=UUID(note.source_artifact_id),
            source_locator=note.source_locator,
            assertion_type=note.assertion_type,
            synthetic=artifact.synthetic,
            chunks=[
                NoteChunkResponse(
                    chunk_id=UUID(chunk.internal_id),
                    chunk_index=chunk.chunk_index,
                    start_offset=chunk.start_offset,
                    end_offset=chunk.end_offset,
                    text=chunk.text,
                    section=chunk.section,
                    sha256=chunk.sha256,
                )
                for chunk in chunks
            ],
        )

    def _timeline_entry(self, session: Session, record: Any, patient_id: UUID) -> TimelineEntry:
        details = TimelineDetails()
        record_type: TimelineRecordType
        if isinstance(record, EncounterRecord):
            record_type = TimelineRecordType.ENCOUNTER
            details = TimelineDetails(
                code=_concept(record.encounter_type) or _concept(record.class_code),
                status=record.status,
                period_start=record.period_start,
                period_end=record.period_end,
            )
        elif isinstance(record, ConditionRecord):
            record_type = TimelineRecordType.CONDITION
            details = TimelineDetails(
                code=_concept(record.code),
                status=(record.clinical_status or {}).get("code"),
                secondary_status=_concept(record.verification_status),
            )
        elif isinstance(record, ObservationRecord):
            record_type = TimelineRecordType.OBSERVATION
            details = TimelineDetails(
                code=_concept(record.code),
                status=record.status,
                value_quantity=record.value_quantity,
                value_unit=record.value_unit,
                value_unit_system=record.value_unit_system,
                value_unit_code=record.value_unit_code,
                value_text=record.value_text,
                data_absent_reason=_concept(record.data_absent_reason),
                reference_range=_ranges(record.reference_range),
            )
        elif isinstance(record, MedicationRequestRecord):
            record_type = TimelineRecordType.MEDICATION_REQUEST
            details = TimelineDetails(
                code=_concept(record.medication),
                status=record.status,
                authored_on=record.authored_on,
                dosage_text=record.dosage_text,
            )
        elif isinstance(record, AllergyRecord):
            record_type = TimelineRecordType.ALLERGY
            details = TimelineDetails(
                code=_concept(record.substance),
                status=(record.clinical_status or {}).get("code"),
                secondary_status=_concept(record.verification_status),
            )
        else:
            record_type = TimelineRecordType.CLINICAL_NOTE
            chunk_count = (
                session.scalar(
                    select(func.count())
                    .select_from(ClinicalNoteChunkRecord)
                    .where(ClinicalNoteChunkRecord.note_id == record.internal_id)
                )
                or 0
            )
            details = TimelineDetails(
                title=record.title,
                note_type=record.note_type,
                content_origin=record.content_origin,
                chunk_count=chunk_count,
            )
        return TimelineEntry(
            record_id=record.internal_id,
            record_type=record_type,
            patient_id=patient_id,
            encounter_id=_uuid(
                record.internal_id if isinstance(record, EncounterRecord) else record.encounter_id
            ),
            event_time=_event_value(record),
            recorded_time=record.recorded_time,
            imported_at=record.imported_at,
            sort_time_basis=_sort_basis(record),
            assertion_type=record.assertion_type,
            value_state=_value_state(record),
            missing_fields=_missing_fields(record),
            details=details,
            source=_source(record),
        )

    @staticmethod
    def _source_in_scope(session: Session, artifact_id: str, patient_id: UUID) -> bool:
        if session.scalar(
            select(func.count())
            .select_from(PatientRecord)
            .where(
                PatientRecord.internal_id == str(patient_id),
                PatientRecord.source_artifact_id == artifact_id,
            )
        ):
            return True
        return any(
            session.scalar(
                select(func.count())
                .select_from(model)
                .where(model.patient_id == str(patient_id), model.source_artifact_id == artifact_id)
            )
            for model in FACT_MODELS
        )

    @staticmethod
    def _artifact_patient_ids(session: Session, artifact_id: str) -> set[str]:
        patient_ids = set(
            session.scalars(
                select(PatientRecord.internal_id).where(
                    PatientRecord.source_artifact_id == artifact_id
                )
            ).all()
        )
        for model in FACT_MODELS:
            patient_ids.update(
                value
                for value in session.scalars(
                    select(model.patient_id).where(model.source_artifact_id == artifact_id)
                ).all()
                if value is not None
            )
        return patient_ids

    @staticmethod
    def _source_records(
        session: Session, artifact_id: str, patient_id: UUID
    ) -> list[SourceRecordReference]:
        output: list[SourceRecordReference] = []
        patient = session.scalar(
            select(PatientRecord).where(
                PatientRecord.internal_id == str(patient_id),
                PatientRecord.source_artifact_id == artifact_id,
            )
        )
        if patient:
            output.append(
                SourceRecordReference(
                    record_type="patient",
                    record_id=UUID(patient.internal_id),
                    patient_id=patient_id,
                )
            )
        for model in FACT_MODELS:
            records = session.scalars(
                select(model).where(
                    model.patient_id == str(patient_id), model.source_artifact_id == artifact_id
                )
            ).all()
            output.extend(
                SourceRecordReference(
                    record_type=RECORD_TYPE_BY_MODEL[model],
                    record_id=UUID(item.internal_id),
                    patient_id=patient_id,
                    encounter_id=_uuid(
                        item.internal_id
                        if isinstance(item, EncounterRecord)
                        else getattr(item, "encounter_id", None)
                    ),
                )
                for item in records
            )
        return output

    @staticmethod
    def _quality_rows(session: Session, manifest_ids: set[str] | None) -> dict[str, list[Any]]:
        output: dict[str, list[Any]] = {}
        for model in (PatientRecord, *FACT_MODELS):
            query = select(model)
            if manifest_ids is not None:
                query = query.where(model.import_manifest_id.in_(manifest_ids))
            output[model.__tablename__] = list(session.scalars(query).all())
        return output

    @staticmethod
    def _missing_links(rows: dict[str, list[Any]]) -> DataQualityIssue:
        examples: list[str] = []
        count = 0
        for table, records in rows.items():
            if table == "patients":
                continue
            for record in records:
                if record.patient_id is None:
                    count += 1
                    if len(examples) < 5:
                        examples.append(f"{table}/{record.internal_id}: patient link missing")
        return DataQualityIssue(category="missing_links", count=count, examples=examples)

    @staticmethod
    def _ambiguous_identifiers(rows: dict[str, list[Any]]) -> DataQualityIssue:
        owners: defaultdict[tuple[str | None, str], set[str]] = defaultdict(set)
        for patient in rows["patients"]:
            for identifier in patient.identifiers:
                owners[(identifier.get("system"), identifier["value"])].add(patient.internal_id)
        ambiguous = [(key, values) for key, values in owners.items() if len(values) > 1]
        return DataQualityIssue(
            category="ambiguous_patient_identifiers",
            count=len(ambiguous),
            examples=[
                f"{key[0] or '(no system)'}|{key[1]} -> {len(ids)} patients"
                for key, ids in ambiguous[:5]
            ],
        )

    @staticmethod
    def _unsupported_types(session: Session, artifact_ids: set[str] | None) -> DataQualityIssue:
        query = select(SourceResourceMappingRecord).where(
            SourceResourceMappingRecord.outcome_status == "unsupported"
        )
        if artifact_ids is not None:
            query = query.where(SourceResourceMappingRecord.source_artifact_id.in_(artifact_ids))
        records = list(session.scalars(query).all())
        return DataQualityIssue(
            category="unsupported_fhir_types",
            count=len(records),
            examples=[
                f"{item.resource_type or 'unknown'}/{item.resource_id or 'unknown'}"
                for item in records[:5]
            ],
        )

    @staticmethod
    def _notes_without_text(rows: dict[str, list[Any]]) -> DataQualityIssue:
        records = [item for item in rows["clinical_notes"] if not item.text.strip()]
        return DataQualityIssue(
            category="notes_without_text",
            count=len(records),
            examples=[f"clinical_note/{item.internal_id}" for item in records[:5]],
        )

    @staticmethod
    def _temporal_anomalies(rows: dict[str, list[Any]]) -> DataQualityIssue:
        examples: list[str] = []
        for encounter in rows["encounters"]:
            if (
                encounter.period_start
                and encounter.period_end
                and encounter.period_end < encounter.period_start
            ):
                examples.append(f"encounter/{encounter.internal_id}: end precedes start")
        for table, records in rows.items():
            for record in records:
                event = _event_value(record)
                event_dt = event if isinstance(event, datetime) else None
                if event_dt and record.recorded_time and record.recorded_time < event_dt:
                    examples.append(f"{table}/{record.internal_id}: recorded time precedes event")
                if record.recorded_time and record.imported_at < record.recorded_time:
                    examples.append(
                        f"{table}/{record.internal_id}: import time precedes recorded time"
                    )
        return DataQualityIssue(
            category="temporal_anomalies", count=len(examples), examples=examples[:5]
        )

    @staticmethod
    def _terminology_and_unit_issues(rows: dict[str, list[Any]]) -> DataQualityIssue:
        examples: list[str] = []
        for table in ("conditions", "observations", "medication_requests", "allergies"):
            field = (
                "medication"
                if table == "medication_requests"
                else "substance"
                if table == "allergies"
                else "code"
            )
            for record in rows[table]:
                concept = getattr(record, field)
                if not concept.get("code") and not concept.get("text"):
                    examples.append(f"{table}/{record.internal_id}: terminology missing")
        for record in rows["observations"]:
            if record.value_quantity is not None and not (
                record.value_unit or record.value_unit_code
            ):
                examples.append(f"observations/{record.internal_id}: quantity unit missing")
        return DataQualityIssue(
            category="terminology_or_unit_issues", count=len(examples), examples=examples[:5]
        )

    @staticmethod
    def _contradictory_observations(rows: dict[str, list[Any]]) -> DataQualityIssue:
        grouped: defaultdict[tuple[Any, ...], list[ObservationRecord]] = defaultdict(list)
        for record in rows["observations"]:
            grouped[
                (
                    record.patient_id,
                    record.code.get("system"),
                    record.code.get("code") or record.code.get("text"),
                    str(_event_value(record)),
                )
            ].append(record)
        examples: list[str] = []
        for key, records in grouped.items():
            values = {
                (
                    str(item.value_quantity),
                    item.value_unit,
                    item.value_text,
                    str(item.data_absent_reason),
                )
                for item in records
            }
            if len(values) > 1:
                examples.append(f"patient {key[0]} code {key[2]} at {key[3]}: {len(values)} values")
        return DataQualityIssue(
            category="contradictory_observations", count=len(examples), examples=examples[:5]
        )

    @staticmethod
    def _duplicate_mappings(session: Session, artifact_ids: set[str] | None) -> DataQualityIssue:
        query = select(SourceResourceMappingRecord)
        if artifact_ids is not None:
            query = query.where(SourceResourceMappingRecord.source_artifact_id.in_(artifact_ids))
        mappings = list(session.scalars(query).all())
        grouped: defaultdict[tuple[str | None, str | None], int] = defaultdict(int)
        for item in mappings:
            if item.normalized_id:
                grouped[(item.normalized_type, item.normalized_id)] += 1
        duplicates = [(key, count) for key, count in grouped.items() if count > 1]
        return DataQualityIssue(
            category="duplicate_normalized_mappings",
            count=len(duplicates),
            examples=[f"{key[0]}/{key[1]} mapped {count} times" for key, count in duplicates[:5]],
        )
