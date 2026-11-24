from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from conftest import AvailableConnectivity
from httpx2 import ASGITransport, AsyncClient
from mage_med_backend.config import Settings
from mage_med_backend.main import create_app

ROOT = Path(__file__).resolve().parents[3]
FHIR_FIXTURE = ROOT / "data/synthetic/fhir/r4/synthetic_patient_bundle.json"

pytestmark = pytest.mark.anyio


def _migrate(settings: Settings) -> None:
    config = Config(ROOT / "apps/backend/alembic.ini")
    config.set_main_option("sqlalchemy.url", settings.database_url)
    command.upgrade(config, "head")


async def test_text_upload_and_patient_scoped_retrieval(settings: Settings) -> None:
    _migrate(settings)
    app = create_app(settings, neo4j_connectivity=AvailableConnectivity())
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            fhir = await client.post(
                "/api/v1/import/fhir",
                files={
                    "file": (
                        FHIR_FIXTURE.name,
                        FHIR_FIXTURE.read_bytes(),
                        "application/fhir+json",
                    )
                },
                data={"dataset_id": "api-synthetic-r4", "synthetic_seed": "20261123"},
            )
            assert fhir.status_code == 201
            patient = next(
                item for item in fhir.json()["resources"] if item["resource_type"] == "Patient"
            )
            encounter = next(
                item for item in fhir.json()["resources"] if item["resource_type"] == "Encounter"
            )
            imported = await client.post(
                "/api/v1/import/text",
                files={
                    "file": (
                        "synthetic-note.txt",
                        b"SYNTHETIC NOTE -- API fixture, not clinician-authored.",
                        "text/plain",
                    )
                },
                data={
                    "dataset_id": "api-synthetic-text",
                    "synthetic": "true",
                    "synthetic_seed": "20261123",
                    "patient_id": patient["normalized_id"],
                    "encounter_id": encounter["normalized_id"],
                    "note_type": "progress",
                    "source_label": "SYNTHETIC fixture generator; not clinician-authored",
                    "authored_at": "2026-01-15T09:25:00Z",
                },
            )
            assert imported.status_code == 201
            outcome = imported.json()["notes"][0]
            assert outcome["status"] == "imported"

            context = await client.get(
                f"/api/v1/patients/{patient['normalized_id']}/clinical-context"
            )
            assert context.status_code == 200
            body = context.json()
            assert any(item["record_type"] == "observation" for item in body["structured_records"])
            imported_note = next(
                item for item in body["notes"] if item["note_id"] == outcome["note_id"]
            )
            assert imported_note["source_label"].startswith("SYNTHETIC fixture")
            chunk = imported_note["chunks"][0]
            assert (
                imported_note["text"][chunk["start_offset"] : chunk["end_offset"]] == chunk["text"]
            )

            note = await client.get(
                f"/api/v1/patients/{patient['normalized_id']}/notes/{outcome['note_id']}"
            )
            assert note.status_code == 200
            wrong_scope = await client.get(
                f"/api/v1/patients/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/notes/{outcome['note_id']}"
            )
            assert wrong_scope.status_code == 404


async def test_text_upload_limits_type_and_path(settings: Settings) -> None:
    bounded = settings.model_copy(update={"clinical_text_max_upload_bytes": 1024})
    _migrate(bounded)
    app = create_app(bounded, neo4j_connectivity=AvailableConnectivity())
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            traversal = await client.post(
                "/api/v1/import/text",
                files={"file": ("../note.txt", b"text", "text/plain")},
            )
            assert traversal.status_code == 400
            wrong_type = await client.post(
                "/api/v1/import/text",
                files={"file": ("note.txt", b"text", "application/pdf")},
            )
            assert wrong_type.status_code == 415
            oversized = await client.post(
                "/api/v1/import/text",
                files={"file": ("note.txt", b"x" * 1025, "text/plain")},
            )
            assert oversized.status_code == 413
            invalid_encoding = await client.post(
                "/api/v1/import/text",
                files={"file": ("note.txt", b"\xff", "text/plain")},
            )
            assert invalid_encoding.status_code == 422
