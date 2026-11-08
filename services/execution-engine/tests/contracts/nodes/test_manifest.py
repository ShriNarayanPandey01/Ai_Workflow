from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from ai_workflow.contracts.nodes.catalog_loader import (
    load_catalog_manifests,
    reset_manifest_schema_cache,
)
from ai_workflow.contracts.nodes.manifest import ManifestValidationError


@pytest.fixture(autouse=True)
def _reset_schema_cache() -> Iterator[None]:
    reset_manifest_schema_cache()
    yield
    reset_manifest_schema_cache()


def test_load_production_catalog(repo_contracts_root: Path) -> None:
    manifests = load_catalog_manifests(repo_contracts_root)

    assert len(manifests) == 18
    assert "data.input@1" in manifests
    assert "ai.chat-model@1" in manifests


def test_default_bindings_parsed_from_chat_model(
    repo_contracts_root: Path,
    mini_catalog_dir: Path,
) -> None:
    manifests = load_catalog_manifests(
        repo_contracts_root,
        catalog_dir=mini_catalog_dir,
    )
    chat = manifests["ai.chat-model@1"]

    bindings = chat.default_bindings_by_port()["prompt"]
    assert len(bindings) == 1
    assert bindings[0].target_path == "/text"
    assert bindings[0].match.source_ports == ["text", "response"]


def test_invalid_manifest_rejected(repo_contracts_root: Path, tmp_path: Path) -> None:
    catalog_dir = tmp_path / "catalog"
    catalog_dir.mkdir()
    (catalog_dir / "bad@1.json").write_text('{"type": "bad"}', encoding="utf-8")

    with pytest.raises(ManifestValidationError):
        load_catalog_manifests(repo_contracts_root, catalog_dir=catalog_dir)
