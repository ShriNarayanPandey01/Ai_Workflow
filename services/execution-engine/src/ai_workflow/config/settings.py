from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from pydantic import Field, field_validator
from pydantic import ValidationError as PydanticValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

SERVICE_ROOT = Path(__file__).resolve().parents[3]
REPO_ROOT = SERVICE_ROOT.parent.parent
DEFAULT_ENV_FILE = SERVICE_ROOT / ".env"
DEFAULT_CONTRACTS_ROOT = REPO_ROOT / "contracts"

REQUIRED_ENV_VARS = (
    "AIW_DATABASE_URL",
    "AIW_RABBITMQ_URL",
    "AIW_SERVICE_ROLE",
)

_REQUIRED_FIELDS: tuple[tuple[str, str], ...] = (
    ("database_url", "AIW_DATABASE_URL"),
    ("rabbitmq_url", "AIW_RABBITMQ_URL"),
    ("service_role", "AIW_SERVICE_ROLE"),
)


class SettingsLoadError(RuntimeError):
    """Raised when required settings are missing or invalid."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        extra="ignore",
        populate_by_name=True,
    )

    database_url: str = Field(alias="AIW_DATABASE_URL")
    rabbitmq_url: str = Field(alias="AIW_RABBITMQ_URL")
    service_role: str = Field(alias="AIW_SERVICE_ROLE")
    log_level: str = Field(default="INFO", alias="AIW_LOG_LEVEL")

    max_graph_nodes: int = Field(default=500, alias="AIW_MAX_GRAPH_NODES", ge=1)
    max_loop_iterations: int = Field(default=100, alias="AIW_MAX_LOOP_ITERATIONS", ge=1)
    max_run_seconds: int = Field(default=300, alias="AIW_MAX_RUN_SECONDS", ge=1)
    max_payload_bytes: int = Field(default=1_048_576, alias="AIW_MAX_PAYLOAD_BYTES", ge=1)
    max_fan_out_items: int = Field(default=1000, alias="AIW_MAX_FAN_OUT_ITEMS", ge=1)
    max_node_executions: int = Field(default=10_000, alias="AIW_MAX_NODE_EXECUTIONS", ge=1)
    max_parallel_nodes: int = Field(default=32, alias="AIW_MAX_PARALLEL_NODES", ge=1)
    max_task_seconds: int = Field(default=3600, alias="AIW_MAX_TASK_SECONDS", ge=1)
    max_task_provider_calls: int = Field(
        default=500,
        alias="AIW_MAX_TASK_PROVIDER_CALLS",
        ge=1,
    )
    max_task_artifact_bytes: int = Field(
        default=52_428_800,
        alias="AIW_MAX_TASK_ARTIFACT_BYTES",
        ge=1,
    )
    max_task_estimated_cost: float | None = Field(
        default=None,
        alias="AIW_MAX_TASK_ESTIMATED_COST",
        ge=0,
    )
    contracts_root: Path = Field(default=DEFAULT_CONTRACTS_ROOT, alias="AIW_CONTRACTS_ROOT")

    baseten_api_key: str | None = Field(default=None, alias="BASETEN_API_KEY")
    chat_base_url: str = Field(
        default="https://inference.baseten.co/v1",
        alias="AIW_CHAT_BASE_URL",
    )
    chat_model: str = Field(
        default="meta-models/muse-spark-open-1026",
        alias="AIW_CHAT_MODEL",
    )
    gemini_api_key: str | None = Field(default=None, alias="GEMINI_API_KEY")
    fake_llm: bool = Field(default=False, alias="AIW_FAKE_LLM")
    fake_embeddings: bool = Field(default=False, alias="AIW_FAKE_EMBEDDINGS")
    embedding_model: str = Field(
        default="gemini-embedding-001",
        alias="AIW_EMBEDDING_MODEL",
    )
    embedding_dimensions: int = Field(default=1536, alias="AIW_EMBEDDING_DIMENSIONS", ge=8)

    control_plane_internal_url: str | None = Field(
        default=None,
        alias="AIW_CONTROL_PLANE_INTERNAL_URL",
    )
    internal_auth_token: str | None = Field(default=None, alias="AIW_INTERNAL_AUTH_TOKEN")
    artifact_dir: Path = Field(
        default=SERVICE_ROOT / "artifacts",
        alias="AIW_ARTIFACT_DIR",
    )
    minio_endpoint: str | None = Field(default=None, alias="AIW_MINIO_ENDPOINT")
    minio_access_key: str | None = Field(default=None, alias="AIW_MINIO_ACCESS_KEY")
    minio_secret_key: str | None = Field(default=None, alias="AIW_MINIO_SECRET_KEY")
    minio_bucket: str = Field(default="aiw-artifacts", alias="AIW_MINIO_BUCKET")
    worker_prefetch: int = Field(default=10, alias="AIW_WORKER_PREFETCH", ge=1)

    @field_validator("contracts_root", "artifact_dir", mode="before")
    @classmethod
    def _coerce_contracts_root(cls, value: object) -> Path:
        if isinstance(value, Path):
            return value
        return Path(str(value))

    @field_validator("baseten_api_key", "gemini_api_key", mode="before")
    @classmethod
    def _empty_key_to_none(cls, value: object) -> object:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @field_validator(
        "control_plane_internal_url",
        "internal_auth_token",
        "minio_endpoint",
        "minio_access_key",
        "minio_secret_key",
        mode="before",
    )
    @classmethod
    def _empty_optional_to_none(cls, value: object) -> object:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @field_validator("fake_llm", "fake_embeddings", mode="before")
    @classmethod
    def _coerce_fake_llm(cls, value: object) -> object:
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"1", "true", "yes", "on"}:
                return True
            if lowered in {"0", "false", "no", "off", ""}:
                return False
        return value


def _load_dotenv(env_file: Path | None) -> None:
    if env_file is None:
        return
    if env_file.is_file():
        load_dotenv(env_file, override=False)


def _missing_required_env_vars(overrides: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    for field_name, env_var in _REQUIRED_FIELDS:
        if field_name in overrides or env_var in overrides:
            continue
        if not os.environ.get(env_var):
            missing.append(env_var)
    return missing


def load_settings(*, env_file: Path | None = DEFAULT_ENV_FILE, **overrides: Any) -> Settings:
    _load_dotenv(env_file)

    missing = _missing_required_env_vars(overrides)
    if missing:
        joined = ", ".join(sorted(set(missing)))
        raise SettingsLoadError(f"Missing required environment variable(s): {joined}")

    try:
        return Settings(**overrides)
    except PydanticValidationError as exc:
        raise SettingsLoadError("Invalid settings configuration") from exc


def require_service_role(settings: Settings, expected: str) -> None:
    """Refuse to boot when AIW_SERVICE_ROLE does not match this entrypoint."""
    if settings.service_role != expected:
        msg = (
            f"AIW_SERVICE_ROLE={settings.service_role!r} does not match "
            f"this process ({expected})"
        )
        raise SettingsLoadError(msg)
