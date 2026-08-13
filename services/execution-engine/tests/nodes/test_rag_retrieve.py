from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from ai_workflow.nodes.base import ExecutionContext
from ai_workflow.nodes.rag.retrieve import RetrieveNodeExecutor
from ai_workflow.providers.embedding import EmbeddingRequest, FakeEmbeddingProvider
from ai_workflow.rag.retrieve_store import InMemoryRetrieveStore


def _context(*, workspace_id: UUID, project_id: UUID, dataset_id: UUID) -> ExecutionContext:
    return ExecutionContext(
        run_id=uuid4(),
        workspace_id=workspace_id,
        project_id=project_id,
        workflow_version_id=None,
        node_id=uuid4(),
        attempt=1,
        resource_refs={"dataset": dataset_id},
    )


@pytest.mark.asyncio
async def test_retrieve_isolates_projects() -> None:
    workspace_a = uuid4()
    workspace_b = uuid4()
    project_a = uuid4()
    project_b = uuid4()
    dataset_a = uuid4()
    dataset_b = uuid4()

    store = InMemoryRetrieveStore()
    embedder = FakeEmbeddingProvider(dimensions=8)
    query_vector = await embedder.embed(
        EmbeddingRequest(texts=["alpha docs"], model="fake", dimensions=8)
    )
    other_vector = await embedder.embed(
        EmbeddingRequest(texts=["beta docs"], model="fake", dimensions=8)
    )

    store.seed(
        workspace_id=workspace_a,
        project_id=project_a,
        dataset_id=dataset_a,
        document_id=uuid4(),
        chunk_id=uuid4(),
        text="project A secret",
        embedding=query_vector[0],
    )
    store.seed(
        workspace_id=workspace_b,
        project_id=project_b,
        dataset_id=dataset_b,
        document_id=uuid4(),
        chunk_id=uuid4(),
        text="project B secret",
        embedding=other_vector[0],
    )

    executor = RetrieveNodeExecutor(
        store=store,
        embedding_provider=embedder,
        embedding_dimensions=8,
    )
    result = await executor.execute(
        _context(workspace_id=workspace_a, project_id=project_a, dataset_id=dataset_a),
        {"top_k": 5},
        {"query": {"text": "alpha docs"}},
    )
    chunks = result.outputs["results"]["chunks"]  # type: ignore[index]
    assert isinstance(chunks, list)
    assert len(chunks) == 1
    assert chunks[0]["text"] == "project A secret"


@pytest.mark.asyncio
async def test_retrieve_skips_non_ready_chunks() -> None:
    workspace_id = uuid4()
    project_id = uuid4()
    dataset_id = uuid4()
    store = InMemoryRetrieveStore()
    embedder = FakeEmbeddingProvider(dimensions=8)
    vector = await embedder.embed(
        EmbeddingRequest(texts=["pending"], model="fake", dimensions=8)
    )
    store.seed(
        workspace_id=workspace_id,
        project_id=project_id,
        dataset_id=dataset_id,
        document_id=uuid4(),
        chunk_id=uuid4(),
        text="not active",
        embedding=vector[0],
        status="ingesting",
    )
    executor = RetrieveNodeExecutor(
        store=store,
        embedding_provider=embedder,
        embedding_dimensions=8,
    )
    result = await executor.execute(
        _context(workspace_id=workspace_id, project_id=project_id, dataset_id=dataset_id),
        {"top_k": 5},
        {"query": {"text": "pending"}},
    )
    chunks = result.outputs["results"]["chunks"]  # type: ignore[index]
    assert chunks == []


def test_postgres_retrieve_sql_filters_ownership_and_threshold() -> None:
    import inspect

    from ai_workflow.rag.retrieve_store import PostgresRetrieveStore

    source = inspect.getsource(PostgresRetrieveStore.similarity_search)
    assert "c.workspace_id = $1" in source
    assert "c.project_id = $2" in source
    assert "c.dataset_id = $3" in source
    assert "v.status = 'ready'" in source
    assert "$6::float8" in source
