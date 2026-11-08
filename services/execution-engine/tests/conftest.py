from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_workflow.config.settings import REPO_ROOT, Settings


@pytest.fixture
def valid_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIW_DATABASE_URL", "postgresql://aiw:aiw@localhost:5432/aiw")
    monkeypatch.setenv("AIW_RABBITMQ_URL", "amqp://aiw:aiw@localhost:5672/")
    monkeypatch.setenv("AIW_SERVICE_ROLE", "execution-api")


@pytest.fixture
def test_settings() -> Settings:
    return Settings(
        AIW_DATABASE_URL="postgresql://aiw:aiw@localhost:5432/aiw",
        AIW_RABBITMQ_URL="amqp://aiw:aiw@localhost:5672/",
        AIW_SERVICE_ROLE="execution-api",
    )


@pytest.fixture
def repo_contracts_root() -> Path:
    return REPO_ROOT / "contracts"


@pytest.fixture
def mini_catalog_dir() -> Path:
    return Path(__file__).resolve().parent / "fixtures" / "catalog"


@pytest.fixture
def workflow_linear_path(repo_contracts_root: Path) -> Path:
    return repo_contracts_root / "fixtures" / "valid" / "workflow-linear.json"


@pytest.fixture
def workflow_linear_definition(workflow_linear_path: Path) -> dict:
    return json.loads(workflow_linear_path.read_text(encoding="utf-8"))


@pytest.fixture
def workflow_conditional_definition(repo_contracts_root: Path) -> dict:
    path = repo_contracts_root / "fixtures" / "valid" / "workflow-conditional.json"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def workflow_fan_out_fan_in_definition(repo_contracts_root: Path) -> dict:
    path = repo_contracts_root / "fixtures" / "valid" / "workflow-fan-out-fan-in.json"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def workflow_bounded_loop_definition(repo_contracts_root: Path) -> dict:
    path = repo_contracts_root / "fixtures" / "valid" / "workflow-bounded-loop.json"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def workflow_human_approval_definition(repo_contracts_root: Path) -> dict:
    path = repo_contracts_root / "fixtures" / "valid" / "workflow-human-approval.json"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def workflow_field_bindings_definition(repo_contracts_root: Path) -> dict:
    path = repo_contracts_root / "fixtures" / "valid" / "workflow-field-bindings.json"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def workflow_for_each_collect_definition(repo_contracts_root: Path) -> dict:
    path = repo_contracts_root / "fixtures" / "valid" / "workflow-for-each-collect.json"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def workflow_for_each_over_cap_definition(repo_contracts_root: Path) -> dict:
    path = repo_contracts_root / "fixtures" / "invalid" / "workflow-for-each-over-cap.json"
    return json.loads(path.read_text(encoding="utf-8"))

