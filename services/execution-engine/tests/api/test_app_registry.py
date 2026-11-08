from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from ai_workflow.api.app import create_app
from ai_workflow.config.settings import Settings
from ai_workflow.runtime.registry import RuntimeRegistry


def test_app_lifespan_builds_registry(test_settings: Settings) -> None:
    app = create_app(settings=test_settings)

    with TestClient(app) as _client:
        assert isinstance(app.state.registry, RuntimeRegistry)
        assert app.state.registry.contracts_root == test_settings.contracts_root
        assert len(app.state.registry.catalog) == 18


def test_settings_contracts_root_override(tmp_path: Path) -> None:
    custom_root = tmp_path / "contracts"
    custom_root.mkdir()

    settings = Settings(
        AIW_DATABASE_URL="postgresql://aiw:aiw@localhost:5432/aiw",
        AIW_RABBITMQ_URL="amqp://aiw:aiw@localhost:5672/",
        AIW_SERVICE_ROLE="execution-api",
        AIW_CONTRACTS_ROOT=custom_root,
    )

    assert settings.contracts_root == custom_root
