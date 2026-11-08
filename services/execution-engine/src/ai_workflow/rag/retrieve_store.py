# Sibling retrieve/read copy — keep in sync with:
#   services/rag/src/ai_workflow_rag/store/store.py (similarity_search)
#   services/rag/src/ai_workflow_rag/store/retrieve.py
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

import asyncpg


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    chunk_id: UUID
    document_id: UUID
    text: str
    score: float
    metadata: dict[str, Any]


class RetrieveStore(Protocol):
    async def similarity_search(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID,
        dataset_id: UUID,
        query_embedding: list[float],
        top_k: int,
        score_threshold: float | None = None,
    ) -> list[RetrievedChunk]: ...


class PostgresRetrieveStore:
    """Read-only pgvector similarity search with mandatory ownership filters."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

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


class InMemoryRetrieveStore:
    """Hermetic retrieve store for unit tests."""

    def __init__(self) -> None:
        self.chunks: list[dict[str, Any]] = []

    def seed(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID,
        dataset_id: UUID,
        document_id: UUID,
        chunk_id: UUID,
        text: str,
        embedding: list[float],
        metadata: dict[str, Any] | None = None,
        status: str = "ready",
    ) -> None:
        self.chunks.append(
            {
                "workspace_id": workspace_id,
                "project_id": project_id,
                "dataset_id": dataset_id,
                "document_id": document_id,
                "chunk_id": chunk_id,
                "text": text,
                "embedding": embedding,
                "metadata": metadata or {},
                "status": status,
            }
        )

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
        scored: list[RetrievedChunk] = []
        for chunk in self.chunks:
            if chunk["status"] != "ready":
                continue
            if (
                chunk["workspace_id"] != workspace_id
                or chunk["project_id"] != project_id
                or chunk["dataset_id"] != dataset_id
            ):
                continue
            score = _cosine_similarity(query_embedding, chunk["embedding"])
            if score_threshold is not None and score < score_threshold:
                continue
            scored.append(
                RetrievedChunk(
                    chunk_id=chunk["chunk_id"],
                    document_id=chunk["document_id"],
                    text=chunk["text"],
                    score=score,
                    metadata=dict(chunk["metadata"]),
                )
            )
        scored.sort(key=lambda item: item.score, reverse=True)
        return scored[:top_k]


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    length = min(len(left), len(right))
    if length == 0:
        return 0.0
    dot = sum(left[i] * right[i] for i in range(length))
    left_norm = sum(value * value for value in left[:length]) ** 0.5
    right_norm = sum(value * value for value in right[:length]) ** 0.5
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)
