from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

import asyncpg

# Sibling retrieve/read copy: services/execution-engine/src/ai_workflow/rag/retrieve_store.py


@dataclass(frozen=True, slots=True)
class DocumentVersionRecord:
    id: UUID
    workspace_id: UUID
    project_id: UUID
    dataset_id: UUID
    document_id: UUID
    version: int
    content_hash: str
    status: str
    chunk_count: int
    embedding_model: str
    embedding_dimensions: int


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    chunk_id: UUID
    document_id: UUID
    text: str
    score: float
    metadata: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ChunkWrite:
    index: int
    text: str
    token_count: int
    metadata: dict[str, Any]
    embedding: list[float]


class RagStore:
    """Write + read access to rag.* tables."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def find_ready_version(
        self,
        *,
        document_id: UUID,
        version: int,
        content_hash: str,
    ) -> DocumentVersionRecord | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, workspace_id, project_id, dataset_id, document_id, version,
                       content_hash, status, chunk_count, embedding_model, embedding_dimensions
                FROM rag.rag_document_versions
                WHERE document_id = $1
                  AND version = $2
                  AND content_hash = $3
                  AND status = 'ready'
                """,
                document_id,
                version,
                content_hash,
            )
        if row is None:
            return None
        return _version_from_row(row)

    async def begin_ingest_version(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID,
        dataset_id: UUID,
        document_id: UUID,
        version: int,
        content_hash: str,
        media_type: str,
        original_name: str | None,
        chunking_config_hash: str,
        embedding_config_hash: str,
        embedding_model: str,
        embedding_dimensions: int,
    ) -> UUID:
        version_id = uuid4()
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO rag.rag_document_versions (
                    id, workspace_id, project_id, dataset_id, document_id, version,
                    content_hash, status, media_type, original_name,
                    chunking_config_hash, embedding_config_hash,
                    embedding_model, embedding_dimensions
                ) VALUES (
                    $1, $2, $3, $4, $5, $6,
                    $7, 'ingesting', $8, $9,
                    $10, $11, $12, $13
                )
                ON CONFLICT (document_id, version) DO UPDATE
                SET content_hash = EXCLUDED.content_hash,
                    status = 'ingesting',
                    media_type = EXCLUDED.media_type,
                    original_name = EXCLUDED.original_name,
                    chunking_config_hash = EXCLUDED.chunking_config_hash,
                    embedding_config_hash = EXCLUDED.embedding_config_hash,
                    embedding_model = EXCLUDED.embedding_model,
                    embedding_dimensions = EXCLUDED.embedding_dimensions,
                    chunk_count = 0,
                    error_code = NULL,
                    error_message = NULL,
                    updated_at = NOW()
                RETURNING id
                """,
                version_id,
                workspace_id,
                project_id,
                dataset_id,
                document_id,
                version,
                content_hash,
                media_type,
                original_name,
                chunking_config_hash,
                embedding_config_hash,
                embedding_model,
                embedding_dimensions,
            )
            assert row is not None
            resolved_id = row["id"]
            await conn.execute(
                "DELETE FROM rag.rag_chunks WHERE document_version_id = $1",
                resolved_id,
            )
            return resolved_id

    async def insert_chunks(
        self,
        *,
        version_id: UUID,
        workspace_id: UUID,
        project_id: UUID,
        dataset_id: UUID,
        document_id: UUID,
        chunks: list[ChunkWrite],
    ) -> None:
        if not chunks:
            return
        async with self._pool.acquire() as conn:
            await conn.executemany(
                """
                INSERT INTO rag.rag_chunks (
                    id, document_version_id, workspace_id, project_id, dataset_id, document_id,
                    chunk_index, text, token_count, metadata, embedding
                ) VALUES (
                    $1, $2, $3, $4, $5, $6,
                    $7, $8, $9, $10::jsonb, $11
                )
                """,
                [
                    (
                        uuid4(),
                        version_id,
                        workspace_id,
                        project_id,
                        dataset_id,
                        document_id,
                        chunk.index,
                        chunk.text,
                        chunk.token_count,
                        json.dumps(chunk.metadata),
                        chunk.embedding,
                    )
                    for chunk in chunks
                ],
            )

    async def activate_version(
        self,
        *,
        version_id: UUID,
        document_id: UUID,
        chunk_count: int,
    ) -> None:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """
                    UPDATE rag.rag_document_versions
                    SET status = 'inactive', updated_at = NOW()
                    WHERE document_id = $1
                      AND status = 'ready'
                      AND id <> $2
                    """,
                    document_id,
                    version_id,
                )
                updated = await conn.fetchrow(
                    """
                    UPDATE rag.rag_document_versions
                    SET status = 'ready',
                        chunk_count = $2,
                        error_code = NULL,
                        error_message = NULL,
                        updated_at = NOW()
                    WHERE id = $1
                      AND status = 'ingesting'
                    RETURNING id
                    """,
                    version_id,
                    chunk_count,
                )
                if updated is None:
                    msg = "Cannot activate version that is not ingesting"
                    raise RuntimeError(msg)

    async def mark_version_failed(
        self,
        *,
        version_id: UUID,
        error_code: str,
        error_message: str | None,
    ) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE rag.rag_document_versions
                SET status = 'failed',
                    error_code = $2,
                    error_message = $3,
                    updated_at = NOW()
                WHERE id = $1
                  AND status = 'ingesting'
                """,
                version_id,
                error_code,
                error_message,
            )

    async def delete_document_vectors(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID,
        dataset_id: UUID,
        document_id: UUID,
    ) -> int:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                result = await conn.execute(
                    """
                    DELETE FROM rag.rag_document_versions
                    WHERE workspace_id = $1
                      AND project_id = $2
                      AND dataset_id = $3
                      AND document_id = $4
                    """,
                    workspace_id,
                    project_id,
                    dataset_id,
                    document_id,
                )
        # asyncpg returns e.g. "DELETE 3"
        try:
            return int(str(result).split()[-1])
        except (ValueError, IndexError):
            return 0

    async def similarity_search(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID,
        dataset_id: UUID,
        query_embedding: list[float],
        top_k: int,
        score_threshold: float | None = None,
    ) -> list[RetrievedChunk]:
        """Mandatory ownership + ready-version filters. Keep in sync with EE copy."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT
                    c.id AS chunk_id,
                    c.document_id,
                    c.text,
                    c.metadata,
                    1 - (c.embedding <=> $5::vector) AS score
                FROM rag.rag_chunks c
                INNER JOIN rag.rag_document_versions v
                    ON v.id = c.document_version_id
                WHERE c.workspace_id = $1
                  AND c.project_id = $2
                  AND c.dataset_id = $3
                  AND v.status = 'ready'
                  AND v.dataset_id = $3
                  AND v.workspace_id = $1
                  AND v.project_id = $2
                  AND ($6::float8 IS NULL OR (1 - (c.embedding <=> $5::vector)) >= $6)
                ORDER BY c.embedding <=> $5::vector
                LIMIT $4
                """,
                workspace_id,
                project_id,
                dataset_id,
                top_k,
                query_embedding,
                score_threshold,
            )

        results: list[RetrievedChunk] = []
        for row in rows:
            score = float(row["score"])
            metadata = row["metadata"]
            if isinstance(metadata, str):
                metadata = json.loads(metadata)
            if not isinstance(metadata, dict):
                metadata = {}
            results.append(
                RetrievedChunk(
                    chunk_id=row["chunk_id"],
                    document_id=row["document_id"],
                    text=row["text"],
                    score=score,
                    metadata=dict(metadata),
                )
            )
        return results


def _version_from_row(row: asyncpg.Record) -> DocumentVersionRecord:
    return DocumentVersionRecord(
        id=row["id"],
        workspace_id=row["workspace_id"],
        project_id=row["project_id"],
        dataset_id=row["dataset_id"],
        document_id=row["document_id"],
        version=int(row["version"]),
        content_hash=row["content_hash"],
        status=row["status"],
        chunk_count=int(row["chunk_count"]),
        embedding_model=row["embedding_model"],
        embedding_dimensions=int(row["embedding_dimensions"]),
    )
