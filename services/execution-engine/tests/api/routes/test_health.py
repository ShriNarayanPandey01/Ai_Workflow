from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from ai_workflow.api.app import create_app
from ai_workflow.config.settings import Settings


async def _always_up(_: Settings) -> tuple[bool, dict[str, str]]:
    return True, {"postgres": "UP", "rabbitmq": "UP"}


async def _always_down(_: Settings) -> tuple[bool, dict[str, str]]:
    return False, {"postgres": "DOWN", "rabbitmq": "DOWN"}


@pytest.fixture
def app_up(test_settings: Settings):
    return create_app(settings=test_settings, readiness_checker=_always_up)


@pytest.fixture
def app_down(test_settings: Settings):
    return create_app(settings=test_settings, readiness_checker=_always_down)


@pytest.mark.asyncio
async def test_liveness_does_not_require_dependencies(app_up) -> None:
    transport = ASGITransport(app=app_up)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/actuator/health/liveness")

    assert response.status_code == 200
    assert response.json() == {"status": "UP"}


@pytest.mark.asyncio
async def test_readiness_up_when_dependencies_healthy(app_up) -> None:
    transport = ASGITransport(app=app_up)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/actuator/health/readiness")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "UP"
    assert body["components"]["postgres"] == "UP"
    assert body["components"]["rabbitmq"] == "UP"


@pytest.mark.asyncio
async def test_readiness_down_when_dependencies_unhealthy(app_down) -> None:
    transport = ASGITransport(app=app_down)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/actuator/health/readiness")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "DOWN"
    assert body["components"]["postgres"] == "DOWN"
    assert body["components"]["rabbitmq"] == "DOWN"
