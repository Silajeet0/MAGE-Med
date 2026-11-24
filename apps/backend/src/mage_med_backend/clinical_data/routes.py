"""Thin FastAPI routes over the patient-scoped clinical data domain service."""

from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import PlainTextResponse
from mage_med_contracts import (
    DataQualityReport,
    ErrorResponse,
    NotePage,
    ObservationPage,
    PatientDetail,
    PatientPage,
    SourceProvenance,
    TimelinePage,
    TimelineRecordType,
)

from mage_med_backend.clinical_data.service import ClinicalDataNotFound, ClinicalDataService

PatientScopeHeader = Annotated[UUID | None, Header(alias="X-Patient-Scope")]


def _enforce_scope(path_patient_id: UUID, header_patient_id: UUID | None) -> None:
    if header_patient_id is not None and header_patient_id != path_patient_id:
        raise HTTPException(status_code=403, detail="patient scope does not match the request")


def create_clinical_data_router(service: ClinicalDataService) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["clinical-data"])

    @router.get("/patients", response_model=PatientPage)
    async def list_patients(
        patient_scope: PatientScopeHeader = None,
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=100)] = 25,
    ) -> PatientPage:
        return service.list_patients(
            page=page, page_size=page_size, scoped_patient_id=patient_scope
        )

    @router.get(
        "/patients/{patient_id}",
        response_model=PatientDetail,
        responses={403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
    )
    async def get_patient(
        patient_id: UUID, patient_scope: PatientScopeHeader = None
    ) -> PatientDetail:
        _enforce_scope(patient_id, patient_scope)
        try:
            return service.get_patient(patient_id)
        except ClinicalDataNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get(
        "/patients/{patient_id}/timeline",
        response_model=TimelinePage,
        responses={403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
    )
    async def get_timeline(
        patient_id: UUID,
        patient_scope: PatientScopeHeader = None,
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=100)] = 25,
        record_type: Annotated[list[TimelineRecordType] | None, Query()] = None,
        encounter_id: UUID | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        sort: Literal["asc", "desc"] = "desc",
    ) -> TimelinePage:
        _enforce_scope(patient_id, patient_scope)
        if date_from and date_to and date_to < date_from:
            raise HTTPException(status_code=422, detail="date_to must not precede date_from")
        try:
            return service.get_timeline(
                patient_id,
                page=page,
                page_size=page_size,
                record_types=set(record_type) if record_type else None,
                encounter_id=encounter_id,
                date_from=date_from,
                date_to=date_to,
                descending=sort == "desc",
            )
        except ClinicalDataNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get(
        "/patients/{patient_id}/observations",
        response_model=ObservationPage,
        responses={403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
    )
    async def get_observations(
        patient_id: UUID,
        patient_scope: PatientScopeHeader = None,
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=100)] = 25,
        code: str | None = None,
        status: str | None = None,
        encounter_id: UUID | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> ObservationPage:
        _enforce_scope(patient_id, patient_scope)
        try:
            return service.get_observations(
                patient_id,
                page=page,
                page_size=page_size,
                code=code,
                status=status,
                encounter_id=encounter_id,
                date_from=date_from,
                date_to=date_to,
            )
        except ClinicalDataNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get(
        "/patients/{patient_id}/notes",
        response_model=NotePage,
        responses={403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
    )
    async def get_notes(
        patient_id: UUID,
        patient_scope: PatientScopeHeader = None,
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=100)] = 25,
        note_type: str | None = None,
        encounter_id: UUID | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> NotePage:
        _enforce_scope(patient_id, patient_scope)
        try:
            return service.get_notes(
                patient_id,
                page=page,
                page_size=page_size,
                note_type=note_type,
                encounter_id=encounter_id,
                date_from=date_from,
                date_to=date_to,
            )
        except ClinicalDataNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get(
        "/sources/{source_id}",
        response_model=SourceProvenance,
        responses={403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
    )
    async def get_source(
        source_id: UUID,
        patient_id: UUID,
        patient_scope: PatientScopeHeader = None,
        include_content: bool = False,
    ) -> SourceProvenance:
        _enforce_scope(patient_id, patient_scope)
        try:
            return service.get_source(
                source_id, patient_id=patient_id, include_content=include_content
            )
        except ClinicalDataNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/data-quality", response_model=DataQualityReport)
    async def get_data_quality(dataset_id: str | None = None) -> DataQualityReport:
        return service.data_quality_report(dataset_id)

    @router.get("/data-quality/report", response_class=PlainTextResponse)
    async def get_human_data_quality_report(dataset_id: str | None = None) -> str:
        return service.data_quality_report(dataset_id).human_readable

    return router
