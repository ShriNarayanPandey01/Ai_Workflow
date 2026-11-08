from __future__ import annotations

from uuid import uuid4

import pytest

from ai_workflow_rag.providers.embedding import EmbeddingRequest, FakeEmbeddingProvider
from ai_workflow_rag.store.retrieve import RetrievedChunk


class LocalRetrieveCopy:
    """Mirrors EE InMemoryRetrieveStore ownership rules for RAG-side copy tests."""

    def __init__(self) -> None:
        self.chunks: list[dict] = []

    def seed(self, **kwargs: object) -> None:
        self.chunks.append(dict(kwargs))

    async def similarity_search(
        self,
        *,
        workspace_id,
        project_id,
        dataset_id,
        query_embedding: list[float],
        top_k: int,
        score_threshold: float | None = None,
    ) -> list[RetrievedChunk]:
        hits: list[RetrievedChunk] = []
        for chunk in self.chunks:
            if chunk.get("status", "ready") != "ready":
                continue
            if (
                chunk["workspace_id"] != workspace_id
                or chunk["project_id"] != project_id
                or chunk["dataset_id"] != dataset_id
            ):
                continue
            hits.append(
                RetrievedChunk(
                    chunk_id=chunk["chunk_id"],
                    document_id=chunk["document_id"],
                    text=chunk["text"],
                    score=1.0,
                    metadata={},
                )
            )
        return hits[:top_k]


@pytest.mark.asyncio
async def test_rag_retrieve_copy_isolates_projects() -> None:
    store = LocalRetrieveCopy()
    workspace_a = uuid4()
    project_a = uuid4()
    dataset_a = uuid4()
    store.seed(
        workspace_id=workspace_a,
        project_id=project_a,
        dataset_id=dataset_a,
        document_id=uuid4(),
        chunk_id=uuid4(),
        text="A only",
        status="ready",
    )
    store.seed(
        workspace_id=uuid4(),
        project_id=uuid4(),
        dataset_id=uuid4(),
        document_id=uuid4(),
        chunk_id=uuid4(),
        text="B only",
        status="ready",
    )
    hits = await store.similarity_search(
        workspace_id=workspace_a,
        project_id=project_a,
        dataset_id=dataset_a,
        query_embedding=[0.1],
        top_k=10,
    )
    assert len(hits) == 1
    assert hits[0].text == "A only"


@pytest.mark.asyncio
async def test_fake_embedding_is_deterministic() -> None:
    provider = FakeEmbeddingProvider(dimensions=16)
    first = await provider.embed(EmbeddingRequest(texts=["same"], model="fake", dimensions=16))
    second = await provider.embed(EmbeddingRequest(texts=["same"], model="fake", dimensions=16))
    assert first == second
