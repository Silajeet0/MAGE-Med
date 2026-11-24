"""Transactional SQLite-backed local FHIR R4 import service."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, TypeAlias
from uuid import UUID, uuid4, uuid5

from mage_med_contracts import (
    Allergy,
    CanonicalClinicalRecord,
    ClinicalNote,
    Condition,
    DataModality,
    Encounter,
    FhirImportReport,
    ImportStatus,
    MedicationRequestSummary,
    Observation,
    Patient,
    ResourceImportOutcome,
    ResourceImportStatus,
    SourceFormat,
)
from mage_med_ingestion import (
    FHIR_VERSION,
    VALIDATION_PACKAGE,
    VALIDATION_PACKAGE_VERSION,
    FhirDocumentError,
    FhirNormalizationError,
    LocalTextAttachmentResolver,
    NormalizationContext,
    NormalizedResource,
    ResolvedReference,
    chunk_clinical_text,
    normalize_document,
    parse_fhir_json,
)
from sqlalchemy import Engine, delete, select
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

ARTIFACT_ID_NAMESPACE = UUID("9a1a19d4-0df7-4758-93c9-8fcaa1ecb498")
MAPPING_ID_NAMESPACE = UUID("96abc516-df2d-4892-bc57-01850620207b")
DATASET_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,255}$")

ClinicalOrmRecord: TypeAlias = (
    PatientRecord
    | EncounterRecord
    | ConditionRecord
    | ObservationRecord
    | MedicationRequestRecord
    | AllergyRecord
    | ClinicalNoteRecord
)


class FhirImportRejected(ValueError):
    """The source document cannot be safely accepted for import."""


class FhirImportNotFound(LookupError):
    """The requested import identifier is unknown."""


def _split_clinical_time(value: date | datetime | None) -> tuple[datetime | None, date | None]:
    if isinstance(value, datetime):
        return value, None
    return None, value


def _concept_json(value: Any) -> dict[str, Any] | None:
    return value.model_dump(mode="json") if value is not None else None


def _common_values(record: CanonicalClinicalRecord, manifest_id: UUID) -> dict[str, Any]:
    event_time, event_date = _split_clinical_time(record.event_time)
    return {
        "internal_id": str(record.internal_id),
        "schema_version": record.schema_version,
        "modality": record.modality,
        "source_artifact_id": str(record.source_reference.source_artifact_id),
        "import_manifest_id": str(manifest_id),
        "source_locator": record.source_reference.source_locator,
        "source_resource_type": record.source_reference.resource_type,
        "source_resource_id": record.source_reference.resource_id,
        "event_time": event_time,
        "event_date": event_date,
        "recorded_time": record.recorded_time,
        "imported_at": record.imported_at,
        "assertion_type": record.assertion_type,
        "provenance": record.provenance.model_dump(mode="json"),
    }


def _to_orm(record: CanonicalClinicalRecord, manifest_id: UUID) -> ClinicalOrmRecord:
    common = _common_values(record, manifest_id)
    if isinstance(record, Patient):
        return PatientRecord(
            **common,
            identifiers=[item.model_dump(mode="json") for item in record.identifiers],
            family_name=record.family_name,
            given_names=record.given_names,
            birth_date=record.birth_date,
            administrative_gender=record.administrative_gender,
            active=record.active,
        )
    if isinstance(record, Encounter):
        return EncounterRecord(
            **common,
            patient_id=str(record.patient_id) if record.patient_id else None,
            status=record.status,
            class_code=_concept_json(record.class_code),
            encounter_type=_concept_json(record.encounter_type),
            period_start=record.period_start,
            period_end=record.period_end,
        )
    patient_context = {
        "patient_id": str(record.patient_id) if record.patient_id else None,
        "encounter_id": str(record.encounter_id) if record.encounter_id else None,
    }
    if isinstance(record, Condition):
        onset_time, onset_date = _split_clinical_time(record.onset_time)
        abatement_time, abatement_date = _split_clinical_time(record.abatement_time)
        return ConditionRecord(
            **common,
            **patient_context,
            code=record.code.model_dump(mode="json"),
            clinical_status=_concept_json(record.clinical_status),
            verification_status=_concept_json(record.verification_status),
            onset_time=onset_time,
            onset_date=onset_date,
            abatement_time=abatement_time,
            abatement_date=abatement_date,
        )
    if isinstance(record, Observation):
        quantity = record.value_quantity
        return ObservationRecord(
            **common,
            **patient_context,
            code=record.code.model_dump(mode="json"),
            status=record.status,
            value_quantity=quantity.value if quantity else None,
            value_unit=quantity.unit if quantity else None,
            value_unit_system=quantity.system if quantity else None,
            value_unit_code=quantity.code if quantity else None,
            value_text=record.value_text,
            data_absent_reason=_concept_json(record.data_absent_reason),
            reference_range=[item.model_dump(mode="json") for item in record.reference_range],
        )
    if isinstance(record, MedicationRequestSummary):
        return MedicationRequestRecord(
            **common,
            **patient_context,
            medication=record.medication.model_dump(mode="json"),
            status=record.status,
            intent=record.intent,
            authored_on=record.authored_on,
            dosage_text=record.dosage_text,
        )
    if isinstance(record, Allergy):
        return AllergyRecord(
            **common,
            **patient_context,
            substance=record.substance.model_dump(mode="json"),
            clinical_status=_concept_json(record.clinical_status),
            verification_status=_concept_json(record.verification_status),
            allergy_type=record.allergy_type,
            categories=record.categories,
            criticality=record.criticality,
            reactions=[item.model_dump(mode="json") for item in record.reactions],
        )
    if isinstance(record, ClinicalNote):
        return ClinicalNoteRecord(
            **common,
            **patient_context,
            note_type=record.note_type,
            title=record.title,
            original_text=record.original_text,
            text=record.text,
            authored_at=record.authored_at,
            author_reference=record.author_reference,
            source_label=record.source_label,
            content_origin=record.content_origin,
        )
    raise TypeError(f"unsupported canonical record: {type(record).__name__}")


class FhirImportService:
    """Coordinate local parsing, normalization, and one atomic SQLite write."""

    def __init__(
        self,
        engine: Engine,
        *,
        max_bytes: int,
        text_import_root: Path | None = None,
        max_note_bytes: int = 256 * 1024,
        chunk_characters: int = 1000,
        chunk_overlap: int = 100,
    ) -> None:
        self._engine = engine
        self._max_bytes = max_bytes
        self._max_note_bytes = max_note_bytes
        self._chunk_characters = chunk_characters
        self._chunk_overlap = chunk_overlap
        self._attachment_resolver = LocalTextAttachmentResolver(
            text_import_root, max_bytes=max_note_bytes
        )

    def _existing_report_for_sha(
        self,
        session: Session,
        sha256: str,
    ) -> FhirImportReport | None:
        artifact = session.scalar(
            select(SourceArtifactRecord).where(SourceArtifactRecord.sha256 == sha256)
        )
        if artifact is None:
            return None
        manifest = session.scalar(
            select(ImportManifestRecord).where(
                ImportManifestRecord.primary_source_artifact_id == artifact.internal_id,
            )
        )
        if manifest is None:
            return None
        return self._report(manifest, artifact.sha256, idempotent_replay=True)

    def _resolve_external(
        self,
        session: Session,
        reference: str,
        expected_resource_type: str,
        dataset_id: str,
    ) -> ResolvedReference | None:
        if reference.startswith("urn:uuid:"):
            mappings = session.scalars(
                select(SourceResourceMappingRecord).where(
                    SourceResourceMappingRecord.full_url == reference,
                    SourceResourceMappingRecord.source_key.startswith(f"fhir-r4:{dataset_id}:"),
                )
            ).all()
        else:
            mappings = session.scalars(
                select(SourceResourceMappingRecord).where(
                    SourceResourceMappingRecord.source_key == f"fhir-r4:{dataset_id}:{reference}"
                )
            ).all()
        usable = [item for item in mappings if item.normalized_id and item.normalized_type]
        if len(usable) > 1:
            raise FhirNormalizationError("persisted reference is ambiguous")
        if not usable:
            return None
        mapping = usable[0]
        if mapping.resource_type != expected_resource_type:
            raise FhirNormalizationError(f"reference does not resolve to {expected_resource_type}")
        patient_id: UUID | None = None
        if expected_resource_type == "Patient":
            patient_id = UUID(mapping.normalized_id)
        elif expected_resource_type == "Encounter":
            encounter = session.get(EncounterRecord, mapping.normalized_id)
            patient_id = UUID(encounter.patient_id) if encounter and encounter.patient_id else None
        normalized_type = mapping.normalized_type
        normalized_id = mapping.normalized_id
        if normalized_type is None or normalized_id is None:
            return None
        return ResolvedReference(
            normalized_type=normalized_type,
            normalized_id=UUID(normalized_id),
            patient_id=patient_id,
        )

    def _persist_record(
        self, session: Session, normalized: NormalizedResource, manifest_id: UUID
    ) -> bool:
        orm_record = _to_orm(normalized.record, manifest_id)
        existing = session.get(type(orm_record), orm_record.internal_id)
        updated = existing is not None
        session.merge(orm_record)
        return updated

    def import_bytes(
        self,
        content: bytes,
        *,
        original_filename: str,
        source_locator: str,
        dataset_id: str = "local-fhir-r4",
        dataset_version: str = "1",
        synthetic_seed: int | None = None,
        actor_id: str = "local-import",
    ) -> FhirImportReport:
        """Import one local FHIR JSON document without network access."""

        if not content:
            raise FhirImportRejected("FHIR input is empty")
        if len(content) > self._max_bytes:
            raise FhirImportRejected("FHIR input exceeds the configured size limit")
        if DATASET_ID_PATTERN.fullmatch(dataset_id) is None:
            raise FhirImportRejected("dataset_id contains unsupported characters")
        if not dataset_version or len(dataset_version) > 128:
            raise FhirImportRejected("dataset_version must contain 1 to 128 characters")
        sha256 = hashlib.sha256(content).hexdigest()
        try:
            document = parse_fhir_json(content)
        except FhirDocumentError as exc:
            raise FhirImportRejected(str(exc)) from exc

        with Session(self._engine) as session:
            existing_report = self._existing_report_for_sha(session, sha256)
            if existing_report:
                return existing_report

        now = datetime.now(UTC)
        artifact_id = uuid5(ARTIFACT_ID_NAMESPACE, sha256)
        manifest_id = uuid4()
        synthetic = any(
            any(
                isinstance(tag, dict) and tag.get("code") == "SYNTHETIC"
                for tag in (
                    resource.raw.get("meta", {}).get("tag", [])
                    if isinstance(resource.raw.get("meta"), dict)
                    else []
                )
            )
            for resource in document.resources
        )
        if synthetic and synthetic_seed is None:
            raise FhirImportRejected("synthetic FHIR input requires an explicit generation seed")

        try:
            with Session(self._engine) as session, session.begin():
                existing_report = self._existing_report_for_sha(session, sha256)
                if existing_report:
                    return existing_report
                artifact = session.get(SourceArtifactRecord, str(artifact_id))
                if artifact is None:
                    artifact = SourceArtifactRecord(
                        internal_id=str(artifact_id),
                        schema_version="1.0.0",
                        modality=DataModality.STRUCTURED_CLINICAL_DATA,
                        source_format=SourceFormat.FHIR_R4_JSON,
                        source_locator=source_locator,
                        original_filename=original_filename,
                        media_type="application/fhir+json",
                        sha256=sha256,
                        raw_content=document.raw,
                        imported_at=now,
                        synthetic=synthetic,
                    )
                    session.add(artifact)
                    session.flush()
                manifest = ImportManifestRecord(
                    internal_id=str(manifest_id),
                    schema_version="1.0.0",
                    dataset_id=dataset_id,
                    dataset_version=dataset_version,
                    source_format=SourceFormat.FHIR_R4_JSON,
                    status=ImportStatus.PENDING,
                    source_artifact_ids=[str(artifact_id)],
                    started_at=now,
                    completed_at=None,
                    importer_name="mage-med-fhir-r4",
                    importer_version="1.0.0",
                    synthetic=synthetic,
                    seed=synthetic_seed if synthetic else None,
                    record_counts={},
                    errors=[],
                    primary_source_artifact_id=str(artifact_id),
                    validation_summary={
                        "package": VALIDATION_PACKAGE,
                        "package_version": VALIDATION_PACKAGE_VERSION,
                        "fhir_version": FHIR_VERSION,
                        "scope": "base_structure_and_project_invariants",
                        "profile_conformance": "not_evaluated",
                    },
                    resource_outcomes=[],
                )
                session.add(manifest)
                session.flush()

                result = normalize_document(
                    document,
                    NormalizationContext(
                        dataset_id=dataset_id,
                        source_artifact_id=artifact_id,
                        import_manifest_id=manifest_id,
                        run_id=manifest_id,
                        source_locator=source_locator,
                        imported_at=now,
                        actor_id=actor_id,
                        synthetic_seed=synthetic_seed,
                        max_note_bytes=self._max_note_bytes,
                    ),
                    lambda reference, expected: self._resolve_external(
                        session, reference, expected, dataset_id
                    ),
                    self._attachment_resolver,
                )
                updates: set[UUID] = set()
                for normalized in result.records:
                    if self._persist_record(session, normalized, manifest_id):
                        updates.add(normalized.record.internal_id)
                    if isinstance(normalized.record, ClinicalNote):
                        session.execute(
                            delete(ClinicalNoteChunkRecord).where(
                                ClinicalNoteChunkRecord.note_id
                                == str(normalized.record.internal_id)
                            )
                        )
                        chunks = chunk_clinical_text(
                            normalized.record.internal_id,
                            normalized.record.text,
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

                outcomes: list[ResourceImportOutcome] = []
                for outcome in result.outcomes:
                    if outcome.normalized_id in updates:
                        outcome = outcome.model_copy(
                            update={"status": ResourceImportStatus.UPDATED}
                        )
                    outcomes.append(outcome)
                for resource, outcome in zip(document.resources, outcomes, strict=True):
                    if resource.resource_type is None or resource.resource_id is None:
                        continue
                    mapping = SourceResourceMappingRecord(
                        internal_id=str(uuid5(MAPPING_ID_NAMESPACE, outcome.source_key)),
                        source_key=outcome.source_key,
                        source_artifact_id=str(artifact_id),
                        import_manifest_id=str(manifest_id),
                        resource_type=resource.resource_type,
                        resource_id=resource.resource_id,
                        full_url=resource.full_url,
                        normalized_type=outcome.normalized_type,
                        normalized_id=(
                            str(outcome.normalized_id) if outcome.normalized_id else None
                        ),
                        outcome_status=outcome.status,
                        issues=outcome.issues,
                        original_resource=resource.raw,
                        updated_at=now,
                    )
                    session.merge(mapping)

                counts: dict[str, int] = {}
                for outcome in outcomes:
                    counts[outcome.status.value] = counts.get(outcome.status.value, 0) + 1
                manifest.status = ImportStatus.SUCCEEDED if result.records else ImportStatus.FAILED
                manifest.completed_at = datetime.now(UTC)
                manifest.record_counts = counts
                manifest.resource_outcomes = [item.model_dump(mode="json") for item in outcomes]
                manifest.errors = (
                    [] if result.records else ["no supported resources could be safely imported"]
                )
                session.flush()
                report = self._report(manifest, sha256, idempotent_replay=False)
        except FhirImportRejected:
            raise
        except Exception as exc:
            raise FhirImportRejected("FHIR import transaction failed and was rolled back") from exc
        return report

    def _report(
        self,
        manifest: ImportManifestRecord,
        sha256: str,
        *,
        idempotent_replay: bool,
    ) -> FhirImportReport:
        return FhirImportReport(
            import_id=UUID(manifest.internal_id),
            status=manifest.status,
            source_artifact_id=(
                UUID(manifest.primary_source_artifact_id)
                if manifest.primary_source_artifact_id
                else None
            ),
            source_sha256=sha256,
            idempotent_replay=idempotent_replay,
            started_at=manifest.started_at,
            completed_at=manifest.completed_at,
            record_counts=manifest.record_counts,
            resources=[
                ResourceImportOutcome.model_validate(item) for item in manifest.resource_outcomes
            ],
            errors=manifest.errors,
        )

    def get_report(self, import_id: UUID) -> FhirImportReport:
        """Return a persisted import report without exposing clinical content."""

        with Session(self._engine) as session:
            manifest = session.get(ImportManifestRecord, str(import_id))
            if manifest is None:
                raise FhirImportNotFound("FHIR import not found")
            artifact = (
                session.get(SourceArtifactRecord, manifest.primary_source_artifact_id)
                if manifest.primary_source_artifact_id
                else None
            )
            if artifact is None:
                raise FhirImportNotFound("FHIR import source artifact not found")
            return self._report(manifest, artifact.sha256, idempotent_replay=False)
