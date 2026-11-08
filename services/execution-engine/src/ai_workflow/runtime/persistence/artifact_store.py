from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from ai_workflow.contracts.common.types import JsonValue


class ArtifactStore(Protocol):
    """Store oversized workflow payloads and return stable references."""

    def put(self, payload: JsonValue) -> str: ...


class InMemoryArtifactStore:
    """Process-local artifact store for collect overflow payloads."""

    def __init__(self) -> None:
        self._artifacts: dict[str, JsonValue] = {}

    def put(self, payload: JsonValue) -> str:
        ref = str(uuid4())
        self._artifacts[ref] = payload
        return ref

    def get(self, ref: str) -> JsonValue | None:
        return self._artifacts.get(ref)


class FilesystemArtifactStore:
    """Durable artifact store on a local/volume path (MinIO stand-in for tests/dev)."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)

    def put(self, payload: JsonValue) -> str:
        ref = str(uuid4())
        path = self._root / f"{ref}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return ref

    def get(self, ref: str) -> JsonValue | None:
        path = self._root / f"{ref}.json"
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))


def payload_size_bytes(payload: JsonValue) -> int:
    """Return UTF-8 byte length of canonical JSON serialization."""
    return len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
