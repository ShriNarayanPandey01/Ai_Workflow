# Sibling embedding provider for retrieve queries — keep in sync with:
#   services/rag/src/ai_workflow_rag/providers/embedding.py
from __future__ import annotations

import hashlib
import math
import struct
from dataclasses import dataclass
from typing import Protocol

import httpx

from ai_workflow.providers.retry import retry_provider_call
from ai_workflow.security.http_client import create_async_client

EMBEDDING_DIMENSIONS = 1536


@dataclass(frozen=True, slots=True)
class EmbeddingRequest:
    texts: list[str]
    model: str
    dimensions: int = EMBEDDING_DIMENSIONS
    task_type: str = "RETRIEVAL_DOCUMENT"
    timeout_seconds: int = 60


class EmbeddingProvider(Protocol):
    async def embed(self, request: EmbeddingRequest) -> list[list[float]]: ...


class FakeEmbeddingProvider:
    def __init__(self, *, dimensions: int = EMBEDDING_DIMENSIONS) -> None:
        self.dimensions = dimensions
        self.calls: list[EmbeddingRequest] = []

    async def embed(self, request: EmbeddingRequest) -> list[list[float]]:
        self.calls.append(request)
        return [_fake_vector(text, request.dimensions) for text in request.texts]


class TransientEmbeddingError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class GeminiEmbeddingProvider:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://generativelanguage.googleapis.com/v1beta",
        client: httpx.AsyncClient | None = None,
        max_attempts: int = 3,
        initial_backoff_ms: int = 250,
        max_backoff_ms: int = 5000,
        multiplier: float = 2.0,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._client = client
        self._owns_client = client is None
        self._max_attempts = max(1, max_attempts)
        self._initial_backoff_ms = initial_backoff_ms
        self._max_backoff_ms = max_backoff_ms
        self._multiplier = multiplier

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()

    async def embed(self, request: EmbeddingRequest) -> list[list[float]]:
        client = self._client or create_async_client()
        if self._client is None:
            self._client = client

        return await retry_provider_call(
            lambda: self._request_once(client, request),
            max_attempts=self._max_attempts,
            initial_backoff_ms=self._initial_backoff_ms,
            max_backoff_ms=self._max_backoff_ms,
            multiplier=self._multiplier,
            transient_error=TransientEmbeddingError,
        )

    async def _request_once(
        self,
        client: httpx.AsyncClient,
        request: EmbeddingRequest,
    ) -> list[list[float]]:
        model = request.model.removeprefix("models/")
        if model != "gemini-embedding-001":
            msg = f"Unsupported Gemini embedding model: {request.model}"
            raise ValueError(msg)
        body: dict[str, object] = {
            "requests": [
                {
                    "model": f"models/{model}",
                    "content": {"parts": [{"text": text}]},
                    "taskType": request.task_type,
                    "outputDimensionality": request.dimensions,
                }
                for text in request.texts
            ]
        }
        response = await client.post(
            f"{self._base_url}/models/{model}:batchEmbedContents",
            headers={
                "x-goog-api-key": self._api_key,
                "Content-Type": "application/json",
            },
            json=body,
            timeout=request.timeout_seconds,
        )
        if response.status_code == 429 or response.status_code in {500, 502, 503, 504}:
            raise TransientEmbeddingError(
                f"Transient embedding error: HTTP {response.status_code}",
                status_code=response.status_code,
            )
        if response.status_code >= 400:
            msg = f"Embedding provider error: HTTP {response.status_code}: {response.text}"
            raise RuntimeError(msg)

        payload = response.json()
        embeddings = payload.get("embeddings") or []
        if len(embeddings) != len(request.texts):
            msg = "Embedding provider returned unexpected vector count"
            raise RuntimeError(msg)
        vectors: list[list[float]] = []
        for item in embeddings:
            embedding = item.get("values")
            if not isinstance(embedding, list) or not embedding:
                msg = "Embedding provider returned empty embedding"
                raise RuntimeError(msg)
            vector = [float(value) for value in embedding]
            if len(vector) != request.dimensions:
                msg = "Embedding provider returned unexpected dimensions"
                raise RuntimeError(msg)
            vectors.append(vector)
        return vectors


def build_embedding_provider(
    *,
    fake_embeddings: bool = False,
    gemini_api_key: str | None = None,
    dimensions: int = EMBEDDING_DIMENSIONS,
) -> EmbeddingProvider:
    if fake_embeddings or not gemini_api_key:
        return FakeEmbeddingProvider(dimensions=dimensions)
    return GeminiEmbeddingProvider(api_key=gemini_api_key)


def _fake_vector(text: str, dimensions: int) -> list[float]:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    values: list[float] = []
    seed = digest
    while len(values) < dimensions:
        seed = hashlib.sha256(seed).digest()
        for index in range(0, len(seed), 4):
            if len(values) >= dimensions:
                break
            chunk = seed[index : index + 4]
            if len(chunk) < 4:
                break
            (raw,) = struct.unpack("!I", chunk)
            values.append((raw / 0xFFFFFFFF) * 2.0 - 1.0)
    norm = math.sqrt(sum(value * value for value in values)) or 1.0
    return [value / norm for value in values]
