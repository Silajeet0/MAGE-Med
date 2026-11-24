from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from conftest import AvailableConnectivity
from httpx2 import ASGITransport, AsyncClient
from mage_med_backend.config import Settings
from mage_med_backend.main import create_app

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "data/synthetic/fhir/r4/synthetic_patient_bundle.json"

pytestmark = pytest.mark.anyio


def _migrate(settings: Settings) -> None:
    config = Config(ROOT / "apps/backend/alembic.ini")
    config.set_main_option("sqlalchemy.url", settings.database_url)
    command.upgrade(config, "head")


async def test_upload_status_and_idempotent_replay(settings: Settings) -> None:
    _migrate(settings)
    app = create_app(settings, neo4j_connectivity=AvailableConnectivity())
    content = FIXTURE.read_bytes()
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            first = await client.post(
                "/api/v1/import/fhir",
                files={"file": (FIXTURE.name, content, "application/fhir+json")},
                data={"synthetic_seed": "20261123"},
            )
            assert first.status_code == 201
            payload = first.json()
            assert payload["record_counts"] == {"imported": 7}
            assert payload["profile_conformance"] == "not_evaluated"

            status_response = await client.get(f"/api/v1/imports/{payload['import_id']}")
            assert status_response.status_code == 200
            assert status_response.json()["source_sha256"] == payload["source_sha256"]

            replay = await client.post(
                "/api/v1/import/fhir",
                files={"file": (FIXTURE.name, content, "application/json")},
                data={"synthetic_seed": "20261123"},
            )
            assert replay.status_code == 200
            assert replay.json()["idempotent_replay"] is True
            assert replay.json()["import_id"] == payload["import_id"]


async def test_upload_rejects_traversal_wrong_type_oversize_and_corrupt_json(
    tmp_path: Path,
) -> None:
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'bounded.db'}",
        neo4j_password="test-only-password",
        fhir_max_upload_bytes=1024,
    )
    _migrate(settings)
    app = create_app(settings, neo4j_connectivity=AvailableConnectivity())
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            traversal = await client.post(
                "/api/v1/import/fhir",
                files={"file": ("../patient.json", b"{}", "application/json")},
            )
            assert traversal.status_code == 400

            wrong_type = await client.post(
                "/api/v1/import/fhir",
                files={"file": ("patient.json", b"{}", "text/plain")},
            )
            assert wrong_type.status_code == 415

            oversized = await client.post(
                "/api/v1/import/fhir",
                files={"file": ("large.json", b"x" * 1025, "application/json")},
            )
            assert oversized.status_code == 413

            corrupt = await client.post(
                "/api/v1/import/fhir",
                files={"file": ("broken.json", b"{broken", "application/json")},
            )
            assert corrupt.status_code == 422
            assert corrupt.json()["error"]["code"] == "http_error"


async def test_unknown_import_returns_structured_404(settings: Settings) -> None:
    _migrate(settings)
    app = create_app(settings, neo4j_connectivity=AvailableConnectivity())
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            response = await client.get("/api/v1/imports/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    assert response.status_code == 404
    assert response.json()["error"]["message"] == "FHIR import not found"
