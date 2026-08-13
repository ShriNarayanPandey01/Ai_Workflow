from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from ai_workflow.providers.retry import retry_provider_call
from ai_workflow.security.http_client import create_async_client


@dataclass(frozen=True, slots=True)
class ChatMessage:
    role: str
    content: str


@dataclass(frozen=True, slots=True)
class ChatUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
        }


@dataclass(frozen=True, slots=True)
class ChatCompletion:
    text: str
    usage: ChatUsage


@dataclass(frozen=True, slots=True)
class ChatRequest:
    model: str
    messages: list[ChatMessage]
    temperature: float | None = None
    max_output_tokens: int | None = None
    response_format: str = "text"
    timeout_seconds: int = 60


class ChatProvider(Protocol):
    async def complete(self, request: ChatRequest) -> ChatCompletion: ...


class FakeChatProvider:
    """Deterministic provider for hermetic tests."""

    def __init__(self, *, response_text: str = "fake-response") -> None:
        self.response_text = response_text
        self.calls: list[ChatRequest] = []

    async def complete(self, request: ChatRequest) -> ChatCompletion:
        self.calls.append(request)
        prompt_tokens = sum(len(message.content) for message in request.messages)
        completion_tokens = len(self.response_text)
        return ChatCompletion(
            text=self.response_text,
            usage=ChatUsage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
            ),
        )


class TransientChatError(RuntimeError):
    """Provider error that may be retried."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class OpenAICompatibleChatProvider:
    """OpenAI-compatible chat completions client with bounded retries."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
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

    async def complete(self, request: ChatRequest) -> ChatCompletion:
        client = self._client or create_async_client()
        if self._client is None:
            self._client = client

        return await retry_provider_call(
            lambda: self._request_once(client, request),
            max_attempts=self._max_attempts,
            initial_backoff_ms=self._initial_backoff_ms,
            max_backoff_ms=self._max_backoff_ms,
            multiplier=self._multiplier,
            transient_error=TransientChatError,
        )

    async def _request_once(
        self,
        client: httpx.AsyncClient,
        request: ChatRequest,
    ) -> ChatCompletion:
        body: dict[str, Any] = {
            "model": request.model,
            "messages": [
                {"role": message.role, "content": message.content}
                for message in request.messages
            ],
        }
        if request.temperature is not None:
            body["temperature"] = request.temperature
        if request.max_output_tokens is not None:
            body["max_tokens"] = request.max_output_tokens
        if request.response_format == "json_object":
            body["response_format"] = {"type": "json_object"}

        response = await client.post(
            f"{self._base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            json=body,
            timeout=request.timeout_seconds,
        )

        if response.status_code == 429 or response.status_code in {500, 502, 503, 504}:
            raise TransientChatError(
                f"Transient provider error: HTTP {response.status_code}",
                status_code=response.status_code,
            )
        if response.status_code >= 400:
            msg = f"Chat provider error: HTTP {response.status_code}: {response.text}"
            raise RuntimeError(msg)

        payload = response.json()
        choices = payload.get("choices") or []
        if not choices:
            msg = "Chat provider returned no choices"
            raise RuntimeError(msg)
        message = choices[0].get("message") or {}
        text = message.get("content")
        if not isinstance(text, str):
            msg = "Chat provider returned empty content"
            raise RuntimeError(msg)

        usage_raw = payload.get("usage") or {}
        usage = ChatUsage(
            prompt_tokens=int(usage_raw.get("prompt_tokens") or 0),
            completion_tokens=int(usage_raw.get("completion_tokens") or 0),
            total_tokens=int(usage_raw.get("total_tokens") or 0),
        )
        return ChatCompletion(text=text, usage=usage)


def is_retryable_status(status_code: int) -> bool:
    return status_code == 429 or status_code in {500, 502, 503, 504}


def build_chat_provider(
    *,
    fake_llm: bool = False,
    api_key: str | None = None,
    base_url: str = "https://api.openai.com/v1",
) -> ChatProvider:
    """Select Fake or OpenAI-compatible provider from runtime flags."""
    if fake_llm or not api_key:
        return FakeChatProvider()
    return OpenAICompatibleChatProvider(api_key=api_key, base_url=base_url)
