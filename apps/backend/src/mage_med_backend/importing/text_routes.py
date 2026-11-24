"""FastAPI boundary for bounded clinical-text import and retrieval."""

from pathlib import PurePath
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile, status
from mage_med_contracts import (
    ClinicalNoteResponse,
    ErrorResponse,
    NoteType,
    PatientClinicalContextResponse,
    SourceFormat,
    TextImportReport,
)

from mage_med_backend.importing.text_service import (
    ClinicalContextNotFound,
    ClinicalTextService,
    TextImportRejected,
)

FORMAT_BY_SUFFIX = {
    ".txt": SourceFormat.TXT,
    ".csv": SourceFormat.CSV,
    ".json": SourceFormat.JSON,
}
ALLOWED_MEDIA_TYPES = {
    SourceFormat.TXT: {"text/plain", "application/octet-stream"},
    SourceFormat.CSV: {"text/csv", "application/csv", "application/octet-stream"},
    SourceFormat.JSON: {"application/json", "text/json", "application/octet-stream"},
}


def _source_format(filename: str | None) -> tuple[str, SourceFormat]:
    if not filename or "\x00" in filename:
        raise HTTPException(status_code=400, detail="A safe clinical text filename is required")
    if "/" in filename or "\\" in filename or PurePath(filename).name != filename:
        raise HTTPException(status_code=400, detail="Upload filename must not contain a path")
    suffix = PurePath(filename).suffix.lower()
    source_format = FORMAT_BY_SUFFIX.get(suffix)
    if source_format is None:
        raise HTTPException(status_code=415, detail="Clinical text must be TXT, CSV, or JSON")
    return filename, source_format


def create_text_router(service: ClinicalTextService, *, max_bytes: int) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["clinical-text"])

    @router.post(
        "/import/text",
        response_model=TextImportReport,
        status_code=status.HTTP_201_CREATED,
        responses={
            400: {"model": ErrorResponse},
            413: {"model": ErrorResponse},
            415: {"model": ErrorResponse},
            422: {"model": ErrorResponse},
        },
    )
    async def import_text(
        response: Response,
        file: Annotated[UploadFile, File()],
        dataset_id: Annotated[
            str,
            Form(
                min_length=1,
                max_length=256,
                pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,255}$",
            ),
        ] = "local-clinical-text",
        dataset_version: Annotated[str, Form(min_length=1, max_length=128)] = "1",
        synthetic: Annotated[bool, Form()] = False,
        synthetic_seed: Annotated[int | None, Form()] = None,
        patient_id: Annotated[UUID | None, Form()] = None,
        encounter_id: Annotated[UUID | None, Form()] = None,
        note_type: Annotated[NoteType, Form()] = NoteType.CLINICAL_NARRATIVE,
        title: Annotated[str | None, Form(max_length=512)] = None,
        source_label: Annotated[str | None, Form(max_length=512)] = None,
        authored_at: Annotated[str | None, Form(max_length=64)] = None,
    ) -> TextImportReport:
        filename, source_format = _source_format(file.filename)
        if file.content_type not in ALLOWED_MEDIA_TYPES[source_format]:
            raise HTTPException(status_code=415, detail="Unsupported clinical text media type")
        try:
            content = await file.read(max_bytes + 1)
        finally:
            await file.close()
        if len(content) > max_bytes:
            raise HTTPException(status_code=413, detail="Clinical text upload exceeds size limit")
        defaults = None
        if source_format is SourceFormat.TXT:
            defaults = {
                "patient_id": str(patient_id) if patient_id else None,
                "encounter_id": str(encounter_id) if encounter_id else None,
                "note_type": note_type.value,
                "title": title,
                "source_label": source_label,
                "authored_at": authored_at,
            }
        try:
            report = service.import_bytes(
                content,
                source_format=source_format,
                original_filename=filename,
                source_locator=f"upload://{filename}",
                dataset_id=dataset_id,
                dataset_version=dataset_version,
                synthetic=synthetic,
                synthetic_seed=synthetic_seed,
                actor_id="local-api-upload",
                txt_defaults=defaults,
            )
        except TextImportRejected as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        response.status_code = 200 if report.idempotent_replay else 201
        return report

    @router.get(
        "/patients/{patient_id}/clinical-context",
        response_model=PatientClinicalContextResponse,
        responses={404: {"model": ErrorResponse}},
    )
    async def get_patient_context(patient_id: UUID) -> PatientClinicalContextResponse:
        try:
            return service.get_patient_context(patient_id)
        except ClinicalContextNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get(
        "/patients/{patient_id}/notes/{note_id}",
        response_model=ClinicalNoteResponse,
        responses={404: {"model": ErrorResponse}},
    )
    async def get_note(patient_id: UUID, note_id: UUID) -> ClinicalNoteResponse:
        try:
            return service.get_note(patient_id, note_id)
        except ClinicalContextNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    return router
