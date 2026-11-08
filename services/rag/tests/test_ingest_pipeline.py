from __future__ import annotations

import hashlib
from typing import Any
from uuid import UUID, uuid4

import pytest
import respx

from ai_workflow_rag.messaging.envelope import parse_document_ingest
from ai_workflow_rag.pipeline.chunk import chunk_text
from ai_workflow_rag.pipeline.extract import extract_text
from ai_workflow_rag.pipeline.ingest import IngestCommand, IngestPipeline
from ai_workflow_rag.providers.embedding import FakeEmbeddingProvider
from ai_workflow_rag.security.download_intent import DownloadIntent, StaticDownloadIntentClient
from ai_workflow_rag.store.store import (
    ChunkWrite,
    DocumentVersionRecord,
    RetrievedChunk,
)


class FakeRagStore:
    def __init__(self) -> None:
        self.ready: dict[tuple[UUID, int, str], DocumentVersionRecord] = {}
        self.versions: dict[UUID, dict[str, Any]] = {}
        self.chunks: dict[UUID, list[ChunkWrite]] = {}
        self.activated: list[UUID] = []
        self.failed: list[UUID] = []
        self.begin_calls = 0
        self.fail_after_chunks = False

    async def find_ready_version(
        self,
        *,
        document_id: UUID,
        version: int,
        content_hash: str,
    ) -> DocumentVersionRecord | None:
        return self.ready.get((document_id, version, content_hash))

    async def begin_ingest_version(self, **kwargs: Any) -> UUID:
        self.begin_calls += 1
        version_id = uuid4()
        self.versions[version_id] = {"status": "ingesting", **kwargs}
        self.chunks[version_id] = []
        return version_id

    async def insert_chunks(self, *, version_id: UUID, chunks: list[ChunkWrite], **_: Any) -> None:
        self.chunks[version_id] = list(chunks)
        if self.fail_after_chunks:
            raise RuntimeError("forced failure after chunk write")

    async def activate_version(
        self,
        *,
        version_id: UUID,
        document_id: UUID,
        chunk_count: int,
    ) -> None:
        meta = self.versions[version_id]
        meta["status"] = "ready"
        meta["chunk_count"] = chunk_count
        record = DocumentVersionRecord(
            id=version_id,
            workspace_id=meta["workspace_id"],
            project_id=meta["project_id"],
            dataset_id=meta["dataset_id"],
            document_id=document_id,
            version=meta["version"],
            content_hash=meta["content_hash"],
            status="ready",
            chunk_count=chunk_count,
            embedding_model=meta["embedding_model"],
            embedding_dimensions=meta["embedding_dimensions"],
        )
        self.ready[(document_id, meta["version"], meta["content_hash"])] = record
        self.activated.append(version_id)

    async def mark_version_failed(
        self,
        *,
        version_id: UUID,
        error_code: str,
        error_message: str | None,
    ) -> None:
        self.versions[version_id]["status"] = "failed"
        self.versions[version_id]["error_code"] = error_code
        self.failed.append(version_id)

    async def similarity_search(self, **kwargs: Any) -> list[RetrievedChunk]:
        return []


@pytest.mark.asyncio
async def test_extract_and_chunk_plain_text() -> None:
    text = await extract_text(media_type="text/plain", data=b"hello world\n\nmore")
    chunks = chunk_text(text, chunk_size=20, overlap=5)
    assert text.startswith("hello")
    assert chunks


@pytest.mark.asyncio
async def test_ingest_is_idempotent() -> None:
    body = b"hello rag document"
    digest = hashlib.sha256(body).hexdigest()
    document_id = uuid4()
    store = FakeRagStore()
    embedder = FakeEmbeddingProvider(dimensions=8)
    download = StaticDownloadIntentClient(
        DownloadIntent(url="https://objects.example/doc", object_key="k")
    )
    pipeline = IngestPipeline(
        store=store,  # type: ignore[arg-type]
        download_client=download,
        embedding_provider=embedder,
        embedding_model="fake",
        embedding_dimensions=8,
        chunk_size=50,
        chunk_overlap=5,
    )

    with respx.mock:
        respx.get("https://objects.example/doc").respond(200, content=body)
        command = IngestCommand(
            workspace_id=uuid4(),
            project_id=uuid4(),
            dataset_id=uuid4(),
            document_id=document_id,
            object_key="k",
            content_hash=digest,
            media_type="text/plain",
            size_bytes=len(body),
            version=1,
            original_name="doc.txt",
            embedding_config={"model": "fake"},
        )
        first = await pipeline.ingest(command)
        second = await pipeline.ingest(command)

    assert first.status == "ready"
    assert second.status == "ready"
    assert second.idempotent_hit is True
    assert store.begin_calls == 1
    assert len(store.activated) == 1
    assert all(call.task_type == "RETRIEVAL_DOCUMENT" for call in embedder.calls)


@pytest.mark.asyncio
async def test_failed_mid_ingest_never_activates() -> None:
    body = b"partial failure document"
    digest = hashlib.sha256(body).hexdigest()
    store = FakeRagStore()
    store.fail_after_chunks = True
    download = StaticDownloadIntentClient(
        DownloadIntent(url="https://objects.example/doc2", object_key="k2")
    )
    pipeline = IngestPipeline(
        store=store,  # type: ignore[arg-type]
        download_client=download,
        embedding_provider=FakeEmbeddingProvider(dimensions=8),
        embedding_model="fake",
        embedding_dimensions=8,
    )

    with respx.mock:
        respx.get("https://objects.example/doc2").respond(200, content=body)
        result = await pipeline.ingest(
            IngestCommand(
                workspace_id=uuid4(),
                project_id=uuid4(),
                dataset_id=uuid4(),
                document_id=uuid4(),
                object_key="k2",
                content_hash=digest,
                media_type="text/plain",
                size_bytes=len(body),
                version=1,
                original_name=None,
                embedding_config={},
            )
        )

    assert result.status == "failed"
    assert store.activated == []
    assert len(store.failed) == 1
    assert all(meta["status"] != "ready" for meta in store.versions.values())


def test_parse_document_ingest_fixture() -> None:
    import json
    from pathlib import Path

    fixture = (
        Path(__file__).resolve().parents[3]
        / "contracts"
        / "fixtures"
        / "valid"
        / "envelope-document-ingest.json"
    )
    raw = json.loads(fixture.read_text(encoding="utf-8"))
    parsed = parse_document_ingest(raw)
    assert parsed.payload.version == 3
    assert parsed.subject.document_id == parsed.payload.document_id
