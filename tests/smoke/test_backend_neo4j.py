import os

import pytest
from httpx2 import ASGITransport, AsyncClient
from mage_med_backend.config import Settings
from mage_med_backend.main import create_app


@pytest.mark.neo4j_smoke
@pytest.mark.anyio
async def test_backend_readiness_queries_real_neo4j() -> None:
    if os.getenv("MAGE_MED_RUN_NEO4J_SMOKE") != "1":
        pytest.skip("set MAGE_MED_RUN_NEO4J_SMOKE=1 to run against real Neo4j")

    app = create_app(Settings())
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            response = await client.get(
                "/api/v1/health/ready",
                headers={"X-Request-ID": "backend-neo4j-smoke"},
            )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "healthy"
    assert {
        component["name"]: component["status"] for component in response.json()["components"]
    } == {
        "sqlite": "available",
        "neo4j": "available",
    }
