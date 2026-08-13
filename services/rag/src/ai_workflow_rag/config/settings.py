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

EMBEDDING_DIMENSIONS = 1536

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
    contracts_root: Path = Field(default=DEFAULT_CONTRACTS_ROOT, alias="AIW_CONTRACTS_ROOT")

    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    openai_base_url: str = Field(
        default="https://api.openai.com/v1",
        alias="AIW_OPENAI_BASE_URL",
    )
    embedding_model: str = Field(
        default="text-embedding-3-small",
        alias="AIW_EMBEDDING_MODEL",
    )
    embedding_dimensions: int = Field(
        default=EMBEDDING_DIMENSIONS,
        alias="AIW_EMBEDDING_DIMENSIONS",
        ge=8,
        le=4096,
    )
    fake_embeddings: bool = Field(default=False, alias="AIW_FAKE_EMBEDDINGS")

    control_plane_internal_url: str | None = Field(
        default=None,
        alias="AIW_CONTROL_PLANE_INTERNAL_URL",
    )
    internal_auth_token: str | None = Field(default=None, alias="AIW_INTERNAL_AUTH_TOKEN")

    minio_endpoint: str | None = Field(default=None, alias="AIW_MINIO_ENDPOINT")
    minio_access_key: str | None = Field(default=None, alias="AIW_MINIO_ACCESS_KEY")
    minio_secret_key: str | None = Field(default=None, alias="AIW_MINIO_SECRET_KEY")
    minio_bucket: str = Field(default="aiw-documents", alias="AIW_MINIO_BUCKET")

    chunk_size_chars: int = Field(default=1200, alias="AIW_RAG_CHUNK_SIZE", ge=100)
    chunk_overlap_chars: int = Field(default=200, alias="AIW_RAG_CHUNK_OVERLAP", ge=0)

    @field_validator("contracts_root", mode="before")
    @classmethod
    def _coerce_contracts_root(cls, value: object) -> Path:
        if isinstance(value, Path):
            return value
        return Path(str(value))

    @field_validator(
        "openai_api_key",
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

    @field_validator("fake_embeddings", mode="before")
    @classmethod
    def _coerce_bool(cls, value: object) -> object:
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
