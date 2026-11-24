"""Thin FastAPI boundary for bounded local FHIR file uploads."""

from pathlib import PurePath
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile, status
from mage_med_contracts import ErrorResponse, FhirImportReport

from mage_med_backend.importing.service import (
    FhirImportNotFound,
    FhirImportRejected,
    FhirImportService,
)

ALLOWED_CONTENT_TYPES = {
    "application/json",
    "application/fhir+json",
    "application/octet-stream",
    "text/json",
}


def _safe_filename(filename: str | None) -> str:
    if not filename or "\x00" in filename:
        raise HTTPException(status_code=400, detail="A safe JSON filename is required")
    if "/" in filename or "\\" in filename or PurePath(filename).name != filename:
        raise HTTPException(status_code=400, detail="Upload filename must not contain a path")
    if not filename.lower().endswith(".json"):
        raise HTTPException(status_code=415, detail="FHIR uploads must use a .json filename")
    return filename


def create_import_router(service: FhirImportService, *, max_bytes: int) -> APIRouter:
    """Create import routes around an injected transactional service."""

    router = APIRouter(prefix="/api/v1", tags=["imports"])

    @router.post(
        "/import/fhir",
        response_model=FhirImportReport,
        status_code=status.HTTP_201_CREATED,
        responses={
            400: {"model": ErrorResponse},
            413: {"model": ErrorResponse},
            415: {"model": ErrorResponse},
            422: {"model": ErrorResponse},
            500: {"model": ErrorResponse},
        },
    )
    async def import_fhir(
        response: Response,
        file: Annotated[UploadFile, File()],
        dataset_id: Annotated[
            str,
            Form(
                min_length=1,
                max_length=256,
                pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,255}$",
            ),
        ] = "local-fhir-r4",
        dataset_version: Annotated[str, Form(min_length=1, max_length=128)] = "1",
        synthetic_seed: Annotated[int | None, Form()] = None,
    ) -> FhirImportReport:
        filename = _safe_filename(file.filename)
        if file.content_type not in ALLOWED_CONTENT_TYPES:
            raise HTTPException(status_code=415, detail="Unsupported FHIR upload media type")
        try:
            content = await file.read(max_bytes + 1)
        finally:
            await file.close()
        if len(content) > max_bytes:
            raise HTTPException(status_code=413, detail="FHIR upload exceeds the size limit")
        try:
            report = service.import_bytes(
                content,
                original_filename=filename,
                source_locator=f"upload://{filename}",
                dataset_id=dataset_id,
                dataset_version=dataset_version,
                synthetic_seed=synthetic_seed,
                actor_id="local-api-upload",
            )
        except FhirImportRejected as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        response.status_code = (
            status.HTTP_200_OK if report.idempotent_replay else status.HTTP_201_CREATED
        )
        return report

    @router.get(
        "/imports/{import_id}",
        response_model=FhirImportReport,
        responses={404: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    )
    async def get_import(import_id: UUID) -> FhirImportReport:
        try:
            return service.get_report(import_id)
        except FhirImportNotFound as exc:
            raise HTTPException(status_code=404, detail="FHIR import not found") from exc

    return router
