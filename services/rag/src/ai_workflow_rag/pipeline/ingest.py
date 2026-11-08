from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx

from ai_workflow_rag.pipeline.chunk import TextChunk, chunk_text, chunking_config_hash
from ai_workflow_rag.pipeline.extract import extract_text
from ai_workflow_rag.providers.embedding import EmbeddingProvider, EmbeddingRequest
from ai_workflow_rag.security.download_intent import DownloadIntentClient
from ai_workflow_rag.store.store import ChunkWrite, DocumentVersionRecord, RagStore


@dataclass(frozen=True, slots=True)
class IngestCommand:
    workspace_id: UUID
    project_id: UUID
    dataset_id: UUID
    document_id: UUID
    object_key: str
    content_hash: str
    media_type: str
    size_bytes: int
    version: int
    original_name: str | None
    embedding_config: dict[str, Any]


@dataclass(frozen=True, slots=True)
class IngestResult:
    status: str
    chunk_count: int
    content_hash: str
    version: int
    idempotent_hit: bool = False
    error_code: str | None = None
    error_message: str | None = None


class IngestPipeline:
    def __init__(
        self,
        *,
        store: RagStore,
        download_client: DownloadIntentClient,
        embedding_provider: EmbeddingProvider,
        http_client: httpx.AsyncClient | None = None,
        embedding_model: str,
        embedding_dimensions: int,
        chunk_size: int = 1200,
        chunk_overlap: int = 200,
    ) -> None:
        self._store = store
        self._download_client = download_client
        self._embedding_provider = embedding_provider
        self._http = http_client
        self._owns_http = http_client is None
        self._embedding_model = embedding_model
        self._embedding_dimensions = embedding_dimensions
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap

    async def aclose(self) -> None:
        if self._owns_http and self._http is not None:
            await self._http.aclose()

    async def ingest(self, command: IngestCommand) -> IngestResult:
        existing = await self._store.find_ready_version(
            document_id=command.document_id,
            version=command.version,
            content_hash=command.content_hash,
        )
        if existing is not None:
            return IngestResult(
                status="ready",
                chunk_count=existing.chunk_count,
                content_hash=existing.content_hash,
                version=existing.version,
                idempotent_hit=True,
            )

        embedding_config_hash = _hash_json(command.embedding_config)
        model = str(command.embedding_config.get("model") or self._embedding_model)
        chunk_hash = chunking_config_hash(
            chunk_size=self._chunk_size,
            overlap=self._chunk_overlap,
        )

        version_id = await self._store.begin_ingest_version(
            workspace_id=command.workspace_id,
            project_id=command.project_id,
            dataset_id=command.dataset_id,
            document_id=command.document_id,
            version=command.version,
            content_hash=command.content_hash,
            media_type=command.media_type,
            original_name=command.original_name,
            chunking_config_hash=chunk_hash,
            embedding_config_hash=embedding_config_hash,
            embedding_model=model,
            embedding_dimensions=self._embedding_dimensions,
        )

        try:
            intent = await self._download_client.get_download_intent(command.document_id)
            data = await self._download_bytes(intent.url, max_bytes=command.size_bytes)
            digest = hashlib.sha256(data).hexdigest()
            if digest != command.content_hash:
                msg = "Downloaded object content hash mismatch"
                raise RuntimeError(msg)
            if len(data) > command.size_bytes:
                msg = "Downloaded object exceeds declared size_bytes"
                raise RuntimeError(msg)

            text = await extract_text(media_type=command.media_type, data=data)
            chunks = chunk_text(
                text,
                chunk_size=self._chunk_size,
                overlap=self._chunk_overlap,
            )
            vectors = await self._embed_chunks(chunks, model=model)
            writes = [
                ChunkWrite(
                    index=chunk.index,
                    text=chunk.text,
                    token_count=chunk.token_count,
                    metadata=dict(chunk.metadata),
                    embedding=vector,
                )
                for chunk, vector in zip(chunks, vectors, strict=True)
            ]
            await self._store.insert_chunks(
                version_id=version_id,
                workspace_id=command.workspace_id,
                project_id=command.project_id,
                dataset_id=command.dataset_id,
                document_id=command.document_id,
                chunks=writes,
            )
            await self._store.activate_version(
                version_id=version_id,
                document_id=command.document_id,
                chunk_count=len(writes),
            )
            return IngestResult(
                status="ready",
                chunk_count=len(writes),
                content_hash=command.content_hash,
                version=command.version,
            )
        except Exception as exc:
            await self._store.mark_version_failed(
                version_id=version_id,
                error_code=type(exc).__name__,
                error_message=str(exc)[:2048],
            )
            return IngestResult(
                status="failed",
                chunk_count=0,
                content_hash=command.content_hash,
                version=command.version,
                error_code=type(exc).__name__,
                error_message=str(exc)[:2048],
            )

    async def _embed_chunks(self, chunks: list[TextChunk], *, model: str) -> list[list[float]]:
        if not chunks:
            return []
        batch_size = 32
        vectors: list[list[float]] = []
        for start in range(0, len(chunks), batch_size):
            batch = chunks[start : start + batch_size]
            embedded = await self._embedding_provider.embed(
                EmbeddingRequest(
                    texts=[chunk.text for chunk in batch],
                    model=model,
                    dimensions=self._embedding_dimensions,
                    task_type="RETRIEVAL_DOCUMENT",
                )
            )
            vectors.extend(embedded)
        return vectors

    async def _download_bytes(self, url: str, *, max_bytes: int) -> bytes:
        client = self._http or httpx.AsyncClient()
        if self._http is None:
            self._http = client
        async with client.stream("GET", url, timeout=60.0) as response:
            if response.status_code >= 400:
                msg = f"Object download failed: HTTP {response.status_code}"
                raise RuntimeError(msg)
            buffer = bytearray()
            async for part in response.aiter_bytes():
                buffer.extend(part)
                if len(buffer) > max_bytes:
                    msg = "Downloaded object exceeds size limit"
                    raise RuntimeError(msg)
            return bytes(buffer)


def ready_version_as_result(record: DocumentVersionRecord) -> IngestResult:
    return IngestResult(
        status="ready",
        chunk_count=record.chunk_count,
        content_hash=record.content_hash,
        version=record.version,
        idempotent_hit=True,
    )


def _hash_json(value: dict[str, Any]) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
