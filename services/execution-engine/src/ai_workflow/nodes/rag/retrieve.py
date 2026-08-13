from __future__ import annotations

from typing import Any

from ai_workflow.contracts.common.types import JsonValue
from ai_workflow.nodes.base import ExecutionContext, NodeResult
from ai_workflow.providers.embedding import EmbeddingProvider, EmbeddingRequest
from ai_workflow.rag.retrieve_store import RetrieveStore


class RetrieveNodeExecutor:
    node_type = "rag.retrieve@1"

    def __init__(
        self,
        *,
        store: RetrieveStore,
        embedding_provider: EmbeddingProvider,
        embedding_model: str = "text-embedding-3-small",
        embedding_dimensions: int = 1536,
    ) -> None:
        self._store = store
        self._embedding_provider = embedding_provider
        self._embedding_model = embedding_model
        self._embedding_dimensions = embedding_dimensions

    async def execute(
        self,
        context: ExecutionContext,
        config: dict[str, JsonValue],
        inputs: dict[str, JsonValue],
    ) -> NodeResult:
        dataset_id = context.resource_refs.get("dataset")
        if dataset_id is None:
            msg = "rag.retrieve@1 requires resource_refs.dataset"
            raise ValueError(msg)

        top_k = config.get("top_k")
        if not isinstance(top_k, int) or top_k < 1:
            msg = "rag.retrieve@1 requires config.top_k >= 1"
            raise ValueError(msg)

        score_threshold = config.get("score_threshold")
        threshold: float | None
        if score_threshold is None:
            threshold = None
        elif isinstance(score_threshold, (int, float)):
            threshold = float(score_threshold)
        else:
            msg = "rag.retrieve@1 config.score_threshold must be a number or null"
            raise ValueError(msg)

        query = inputs.get("query")
        if not isinstance(query, dict):
            msg = "rag.retrieve@1 requires input query object"
            raise ValueError(msg)
        text = query.get("text")
        if not isinstance(text, str) or not text.strip():
            msg = "rag.retrieve@1 requires query.text"
            raise ValueError(msg)

        vectors = await self._embedding_provider.embed(
            EmbeddingRequest(
                texts=[text],
                model=self._embedding_model,
                dimensions=self._embedding_dimensions,
            )
        )
        hits = await self._store.similarity_search(
            workspace_id=context.workspace_id,
            project_id=context.project_id,
            dataset_id=dataset_id,
            query_embedding=vectors[0],
            top_k=top_k,
            score_threshold=threshold,
        )
        chunks: list[dict[str, Any]] = [
            {
                "chunk_id": str(hit.chunk_id),
                "document_id": str(hit.document_id),
                "text": hit.text,
                "score": hit.score,
                "metadata": hit.metadata,
            }
            for hit in hits
        ]
        return NodeResult(outputs={"results": {"chunks": chunks}})
