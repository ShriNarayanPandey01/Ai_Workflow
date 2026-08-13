from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

import httpx

from ai_workflow.contracts.common.types import JsonValue
from ai_workflow.security.ssrf import Resolver, SsrfError, validate_url

_REDIRECT_STATUS_CODES = frozenset({301, 302, 303, 307, 308})

_DEFAULT_RESPONSE_HEADER_ALLOWLIST = frozenset(
    {
        "content-type",
        "content-length",
        "cache-control",
        "etag",
        "last-modified",
        "location",
        "x-request-id",
        "retry-after",
    }
)


class ResponseTooLargeError(ValueError):
    """Raised when an HTTP response exceeds the configured byte limit."""


@dataclass(frozen=True, slots=True)
class SafeHttpResponse:
    status_code: int
    headers: dict[str, str]
    body_bytes: bytes


def filter_response_headers(
    headers: httpx.Headers,
    *,
    header_allowlist: list[str] | None = None,
) -> dict[str, str]:
    """Retain only safe response headers."""
    if header_allowlist:
        allowed = {name.lower() for name in header_allowlist}
    else:
        allowed = _DEFAULT_RESPONSE_HEADER_ALLOWLIST
    result: dict[str, str] = {}
    for key, value in headers.items():
        if key.lower() in allowed:
            result[key] = value
    return result


async def _read_bounded_body(
    response: httpx.Response,
    *,
    max_response_bytes: int,
) -> bytes:
    chunks: list[bytes] = []
    total = 0
    async for chunk in response.aiter_bytes():
        total += len(chunk)
        if total > max_response_bytes:
            msg = f"Response exceeded max_response_bytes ({max_response_bytes})"
            raise ResponseTooLargeError(msg)
        chunks.append(chunk)
    return b"".join(chunks)


class SafeHttpClient:
    """Outbound HTTP client with SSRF checks, manual redirects, and size limits."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        resolver: Resolver | None = None,
    ) -> None:
        self._client = client
        self._resolver = resolver

    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
        json_body: JsonValue | None = None,
        timeout_seconds: float = 30.0,
        max_response_bytes: int = 1_048_576,
        max_redirects: int = 0,
        header_allowlist: list[str] | None = None,
    ) -> SafeHttpResponse:
        current_url = url
        current_method = method.upper()
        redirects_remaining = max_redirects
        request_headers = dict(headers or {})
        request_params = dict(params or {}) if params else None
        request_json: Any = json_body
        timeout = httpx.Timeout(timeout_seconds)

        while True:
            try:
                await validate_url(current_url, resolver=self._resolver)
            except SsrfError as exc:
                msg = f"Outbound request blocked: {exc}"
                raise ValueError(msg) from exc

            try:
                response = await self._client.request(
                    current_method,
                    current_url,
                    headers=request_headers or None,
                    params=request_params,
                    json=request_json,
                    timeout=timeout,
                    follow_redirects=False,
                )
            except httpx.TimeoutException as exc:
                msg = "HTTP request timed out"
                raise ValueError(msg) from exc

            if (
                response.status_code in _REDIRECT_STATUS_CODES
                and redirects_remaining > 0
            ):
                location = response.headers.get("location")
                if not location:
                    msg = "Redirect response missing Location header"
                    raise ValueError(msg)
                current_url = urljoin(str(response.url), location)
                redirects_remaining -= 1
                if response.status_code == 303:
                    current_method = "GET"
                    request_json = None
                await response.aclose()
                continue

            body_bytes = await _read_bounded_body(
                response,
                max_response_bytes=max_response_bytes,
            )
            filtered = filter_response_headers(
                response.headers,
                header_allowlist=header_allowlist,
            )
            status_code = response.status_code
            await response.aclose()
            return SafeHttpResponse(
                status_code=status_code,
                headers=filtered,
                body_bytes=body_bytes,
            )
