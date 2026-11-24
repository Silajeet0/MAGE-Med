import re

import pytest
from conftest import UnavailableConnectivity
from httpx2 import ASGITransport, AsyncClient

pytestmark = pytest.mark.anyio


async def test_liveness_returns_request_id(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health/live")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "healthy"
    assert payload["components"] == []
    assert response.headers["X-Request-ID"] == payload["request_id"]
    assert re.fullmatch(r"[0-9a-f-]{36}", payload["request_id"])


async def test_liveness_preserves_safe_caller_request_id(client: AsyncClient) -> None:
    response = await client.get(
        "/api/v1/health/live",
        headers={"X-Request-ID": "smoke-request-001"},
    )

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "smoke-request-001"
    assert response.json()["request_id"] == "smoke-request-001"


async def test_readiness_checks_real_sqlite_and_injected_graph(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health/ready")

    assert response.status_code == 200
    assert response.json()["components"] == [
        {"name": "sqlite", "status": "available", "detail": "connectivity verified"},
        {"name": "neo4j", "status": "available", "detail": "connectivity verified"},
    ]


async def test_readiness_reports_graph_failure_without_leaking_error(app_factory) -> None:
    app = app_factory(UnavailableConnectivity())
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            response = await client.get("/api/v1/health/ready")

    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "not_ready"
    assert payload["components"][1] == {
        "name": "neo4j",
        "status": "unavailable",
        "detail": "connectivity check failed",
    }
    assert "test-only" not in response.text


async def test_unknown_route_uses_structured_error(client: AsyncClient) -> None:
    response = await client.get("/missing")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "http_error"
    assert response.json()["error"]["request_id"] == response.headers["X-Request-ID"]
