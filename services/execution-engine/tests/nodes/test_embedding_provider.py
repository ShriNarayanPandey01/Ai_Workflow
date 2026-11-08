from __future__ import annotations

import json

import httpx
import pytest
import respx

from ai_workflow.providers.embedding import EmbeddingRequest, GeminiEmbeddingProvider


@pytest.mark.asyncio
@respx.mock
async def test_gemini_embedding_uses_retrieval_task_and_dimensions() -> None:
    route = respx.post(
        "https://generativelanguage.googleapis.com/v1beta/models/"
        "gemini-embedding-001:batchEmbedContents"
    ).mock(
        return_value=httpx.Response(
            200,
            json={"embeddings": [{"values": [0.1, 0.2, 0.3]}]},
        )
    )
    provider = GeminiEmbeddingProvider(api_key="gemini-test", max_attempts=1)

    vectors = await provider.embed(
        EmbeddingRequest(
            texts=["query"],
            model="gemini-embedding-001",
            dimensions=3,
            task_type="RETRIEVAL_QUERY",
        )
    )

    request = route.calls[0].request
    body = json.loads(request.content)
    assert request.headers["x-goog-api-key"] == "gemini-test"
    assert body["requests"][0]["taskType"] == "RETRIEVAL_QUERY"
    assert body["requests"][0]["outputDimensionality"] == 3
    assert vectors == [[0.1, 0.2, 0.3]]
    await provider.aclose()


@pytest.mark.asyncio
async def test_gemini_provider_rejects_openai_embedding_models() -> None:
    provider = GeminiEmbeddingProvider(api_key="gemini-test")
    with pytest.raises(ValueError, match="Unsupported Gemini embedding model"):
        await provider.embed(
            EmbeddingRequest(texts=["text"], model="text-embedding-3-small")
        )
    await provider.aclose()
