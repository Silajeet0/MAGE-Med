"""FastAPI composition root for the MAGE-Med backend."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import cast

from fastapi import FastAPI, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from mage_med_contracts import ErrorResponse, HealthResponse, HealthStatus
from mage_med_knowledge_graph import Neo4jConnectivity

from mage_med_backend import __version__
from mage_med_backend.clinical_data import ClinicalDataService
from mage_med_backend.clinical_data.routes import create_clinical_data_router
from mage_med_backend.config import Settings, get_settings
from mage_med_backend.database import SqliteConnectivity, create_sqlite_engine
from mage_med_backend.errors import register_error_handlers
from mage_med_backend.health import Connectivity, HealthService
from mage_med_backend.importing import FhirImportService
from mage_med_backend.importing.routes import create_import_router
from mage_med_backend.importing.text_routes import create_text_router
from mage_med_backend.importing.text_service import ClinicalTextService
from mage_med_backend.logging import configure_logging
from mage_med_backend.middleware import RequestIdMiddleware

SERVICE_NAME = "mage-med-backend"


def create_app(
    settings: Settings | None = None,
    *,
    neo4j_connectivity: Connectivity | None = None,
) -> FastAPI:
    """Create the API with explicit settings and injectable connectivity boundaries."""

    resolved_settings = settings or get_settings()
    configure_logging(resolved_settings.log_level)
    engine = create_sqlite_engine(resolved_settings.database_url)
    sqlite_connectivity = SqliteConnectivity(engine)
    graph_connectivity = neo4j_connectivity or Neo4jConnectivity(
        uri=resolved_settings.neo4j_uri,
        username=resolved_settings.neo4j_username,
        password=resolved_settings.neo4j_password,
        database=resolved_settings.neo4j_database,
        timeout_seconds=resolved_settings.neo4j_timeout_seconds,
    )
    health_service = HealthService(sqlite_connectivity, graph_connectivity)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        health_service.close()

    app = FastAPI(
        title="MAGE-Med API",
        description="Research-grade clinician-supervised proof-of-concept API",
        version=__version__,
        lifespan=lifespan,
    )
    app.state.health_service = health_service
    app.state.fhir_import_service = FhirImportService(
        engine,
        max_bytes=resolved_settings.fhir_max_upload_bytes,
        text_import_root=resolved_settings.clinical_text_import_root,
        max_note_bytes=resolved_settings.clinical_text_max_note_bytes,
        chunk_characters=resolved_settings.clinical_text_chunk_characters,
        chunk_overlap=resolved_settings.clinical_text_chunk_overlap,
    )
    app.state.clinical_text_service = ClinicalTextService(
        engine,
        max_upload_bytes=resolved_settings.clinical_text_max_upload_bytes,
        max_note_bytes=resolved_settings.clinical_text_max_note_bytes,
        max_notes=resolved_settings.clinical_text_max_notes,
        chunk_characters=resolved_settings.clinical_text_chunk_characters,
        chunk_overlap=resolved_settings.clinical_text_chunk_overlap,
    )
    app.state.clinical_data_service = ClinicalDataService(engine)
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-Patient-Scope", "X-Request-ID"],
        expose_headers=["X-Request-ID"],
    )
    register_error_handlers(app)
    app.include_router(
        create_import_router(
            app.state.fhir_import_service,
            max_bytes=resolved_settings.fhir_max_upload_bytes,
        )
    )
    app.include_router(
        create_text_router(
            app.state.clinical_text_service,
            max_bytes=resolved_settings.clinical_text_max_upload_bytes,
        )
    )
    app.include_router(create_clinical_data_router(app.state.clinical_data_service))

    @app.get(
        "/api/v1/health/live",
        response_model=HealthResponse,
        responses={500: {"model": ErrorResponse}},
        tags=["health"],
    )
    async def liveness(request: Request) -> HealthResponse:
        return HealthResponse(
            service=SERVICE_NAME,
            version=__version__,
            status=HealthStatus.HEALTHY,
            request_id=cast(str, request.state.request_id),
        )

    @app.get(
        "/api/v1/health/ready",
        response_model=HealthResponse,
        responses={503: {"model": HealthResponse}, 500: {"model": ErrorResponse}},
        tags=["health"],
    )
    async def readiness(request: Request, response: Response) -> HealthResponse | JSONResponse:
        request_id = cast(str, request.state.request_id)
        result = health_service.readiness(request_id)
        body = HealthResponse(
            service=SERVICE_NAME,
            version=__version__,
            status=result.status,
            request_id=request_id,
            components=result.components,
        )
        if result.status is HealthStatus.NOT_READY:
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content=body.model_dump(mode="json"),
            )
        response.status_code = status.HTTP_200_OK
        return body

    return app


app = create_app()
