from __future__ import annotations

from pathlib import Path

import pytest

from ai_workflow.config.settings import Settings, SettingsLoadError, load_settings


def test_load_settings_success(valid_env: None) -> None:
    settings = load_settings(env_file=None)

    assert settings.database_url == "postgresql://aiw:aiw@localhost:5432/aiw"
    assert settings.rabbitmq_url == "amqp://aiw:aiw@localhost:5672/"
    assert settings.service_role == "execution-api"
    assert settings.max_graph_nodes == 500
    assert settings.max_loop_iterations == 100
    assert settings.max_run_seconds == 300
    assert settings.max_payload_bytes == 1_048_576


def test_load_settings_from_dotenv_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "AIW_DATABASE_URL=postgresql://aiw:aiw@postgres:5432/aiw",
                "AIW_RABBITMQ_URL=amqp://aiw:aiw@rabbitmq:5672/",
                "AIW_SERVICE_ROLE=execution-worker",
            ]
        ),
        encoding="utf-8",
    )
    for name in ("AIW_DATABASE_URL", "AIW_RABBITMQ_URL", "AIW_SERVICE_ROLE"):
        monkeypatch.delenv(name, raising=False)

    settings = load_settings(env_file=env_file)

    assert settings.database_url == "postgresql://aiw:aiw@postgres:5432/aiw"
    assert settings.service_role == "execution-worker"


def test_load_settings_custom_limits(valid_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIW_MAX_GRAPH_NODES", "42")
    monkeypatch.setenv("AIW_MAX_TASK_SECONDS", "120")

    settings = load_settings(env_file=None)

    assert settings.max_graph_nodes == 42
    assert settings.max_task_seconds == 120


def test_missing_database_url_names_variable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "AIW_RABBITMQ_URL=amqp://aiw:aiw@localhost:5672/",
                "AIW_SERVICE_ROLE=execution-api",
            ]
        ),
        encoding="utf-8",
    )
    for name in ("AIW_DATABASE_URL", "AIW_RABBITMQ_URL", "AIW_SERVICE_ROLE"):
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(SettingsLoadError) as exc_info:
        load_settings(env_file=env_file)

    message = str(exc_info.value)
    assert "AIW_DATABASE_URL" in message
    assert "postgresql://" not in message


def test_missing_multiple_vars_names_variables_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("", encoding="utf-8")
    for name in ("AIW_DATABASE_URL", "AIW_RABBITMQ_URL", "AIW_SERVICE_ROLE"):
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(SettingsLoadError) as exc_info:
        load_settings(env_file=env_file)

    message = str(exc_info.value)
    assert "AIW_DATABASE_URL" in message
    assert "AIW_RABBITMQ_URL" in message
    assert "AIW_SERVICE_ROLE" in message


def test_settings_can_be_constructed_with_overrides() -> None:
    settings = Settings(
        AIW_DATABASE_URL="postgresql://aiw:aiw@localhost:5432/aiw",
        AIW_RABBITMQ_URL="amqp://aiw:aiw@localhost:5672/",
        AIW_SERVICE_ROLE="execution-worker",
    )

    assert settings.service_role == "execution-worker"


def test_require_service_role_rejects_mismatch() -> None:
    from ai_workflow.config.settings import require_service_role

    settings = Settings(
        AIW_DATABASE_URL="postgresql://aiw:aiw@localhost:5432/aiw",
        AIW_RABBITMQ_URL="amqp://aiw:aiw@localhost:5672/",
        AIW_SERVICE_ROLE="execution-api",
    )
    with pytest.raises(SettingsLoadError, match="execution-worker"):
        require_service_role(settings, "execution-worker")


def test_zenmux_and_gemini_settings_and_fake_llm_coercion(
    valid_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for variable in ("ZENMUX_API_KEY", "AIW_DEEPSEEK_API_KEY"):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("ZENMUSK_API_KEY", "zenmux-compatible-test")
    monkeypatch.setenv("AIW_CHAT_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("AIW_CHAT_ROUTING_PROVIDER", "example-provider")
    monkeypatch.setenv("AIW_CHAT_MODEL", "deepseek-v4-pro")
    monkeypatch.setenv("AIW_IMAGE_GENERATION_MODEL", "example/image-model")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-test")
    monkeypatch.setenv("AIW_FAKE_LLM", "false")

    settings = load_settings(env_file=None)

    assert settings.chat_api_key == "zenmux-compatible-test"
    assert settings.chat_base_url == "https://example.test/v1"
    assert settings.chat_model == "deepseek/deepseek-v4-pro:example-provider"
    assert settings.image_generation_model == "example/image-model"
    assert settings.gemini_api_key == "gemini-test"
    assert settings.embedding_model == "gemini-embedding-001"
    assert settings.embedding_dimensions == 1536
    assert settings.fake_llm is False


def test_openai_chat_settings_select_openai_key_and_model(
    valid_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "openai-test-key")
    monkeypatch.setenv("ZENMUX_API_KEY", "zenmux-test-key")
    monkeypatch.setenv("AIW_CHAT_ROUTING_PROVIDER", "openai")
    monkeypatch.setenv("AIW_CHAT_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("AIW_CHAT_MODEL", "gpt-6-astra")

    settings = load_settings(env_file=None)

    assert settings.chat_api_key == "openai-test-key"
    assert settings.chat_base_url == "https://api.openai.com/v1"
    assert settings.chat_model == "gpt-6-astra"


def test_build_chat_provider_selection() -> None:
    from ai_workflow.providers.chat import (
        FakeChatProvider,
        OpenAICompatibleChatProvider,
        build_chat_provider,
    )

    assert isinstance(build_chat_provider(fake_llm=True, api_key="sk"), FakeChatProvider)
    assert isinstance(build_chat_provider(fake_llm=False, api_key=None), FakeChatProvider)
    provider = build_chat_provider(
        fake_llm=False,
        api_key="sk-test",
        base_url="https://example.test/v1",
    )
    assert isinstance(provider, OpenAICompatibleChatProvider)
