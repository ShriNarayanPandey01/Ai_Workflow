from __future__ import annotations

from ai_workflow_rag.config.settings import SettingsLoadError, load_settings


def test_missing_required_env_names_variable(monkeypatch) -> None:
    monkeypatch.delenv("AIW_DATABASE_URL", raising=False)
    monkeypatch.delenv("AIW_RABBITMQ_URL", raising=False)
    monkeypatch.delenv("AIW_SERVICE_ROLE", raising=False)
    try:
        load_settings(env_file=None)
        raise AssertionError("expected SettingsLoadError")
    except SettingsLoadError as exc:
        assert "AIW_DATABASE_URL" in str(exc)
