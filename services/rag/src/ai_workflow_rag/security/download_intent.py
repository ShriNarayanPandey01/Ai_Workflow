from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

import httpx


@dataclass(frozen=True, slots=True)
class DownloadIntent:
    url: str
    object_key: str
    expires_at: str | None = None


class DownloadIntentClient(Protocol):
    async def get_download_intent(self, document_id: UUID) -> DownloadIntent: ...


class HttpDownloadIntentClient:
    def __init__(
        self,
        *,
        base_url: str,
        auth_token: str | None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._auth_token = auth_token
        self._client = client
        self._owns_client = client is None

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()

    async def get_download_intent(self, document_id: UUID) -> DownloadIntent:
        client = self._client or httpx.AsyncClient()
        if self._client is None:
            self._client = client

        headers: dict[str, str] = {}
        if self._auth_token:
            headers["Authorization"] = f"Bearer {self._auth_token}"

        response = await client.post(
            f"{self._base_url}/internal/v1/documents/{document_id}/download-intent",
            headers=headers,
            timeout=30.0,
        )
        if response.status_code >= 400:
            msg = f"download-intent failed: HTTP {response.status_code}"
            raise RuntimeError(msg)
        payload: dict[str, Any] = response.json()
        url = payload.get("url")
        object_key = payload.get("object_key")
        if not isinstance(url, str) or not url:
            msg = "download-intent response missing url"
            raise RuntimeError(msg)
        if not isinstance(object_key, str) or not object_key:
            msg = "download-intent response missing object_key"
            raise RuntimeError(msg)
        expires = payload.get("expires_at")
        return DownloadIntent(
            url=url,
            object_key=object_key,
            expires_at=expires if isinstance(expires, str) else None,
        )


class StaticDownloadIntentClient:
    """Test double that returns a fixed download intent."""

    def __init__(self, intent: DownloadIntent) -> None:
        self._intent = intent
        self.calls: list[UUID] = []

    async def get_download_intent(self, document_id: UUID) -> DownloadIntent:
        self.calls.append(document_id)
        return self._intent
