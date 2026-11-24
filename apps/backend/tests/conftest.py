from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx2 import ASGITransport, AsyncClient
from mage_med_backend.config import Settings
from mage_med_backend.health import Connectivity
from mage_med_backend.main import create_app


class AvailableConnectivity:
    def verify(self) -> None:
        return None

    def close(self) -> None:
        return None


class UnavailableConnectivity:
    def verify(self) -> None:
        raise ConnectionError("test-only unavailable component")

    def close(self) -> None:
        return None


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        neo4j_password="test-only-password",
    )


@pytest.fixture
def app_factory(settings: Settings):
    def factory(connectivity: Connectivity | None = None) -> FastAPI:
        return create_app(
            settings,
            neo4j_connectivity=connectivity or AvailableConnectivity(),
        )

    return factory


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def client(app_factory) -> AsyncIterator[AsyncClient]:
    app = app_factory()
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as test_client:
            yield test_client
