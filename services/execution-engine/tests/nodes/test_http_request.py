from __future__ import annotations

from uuid import UUID

import httpx
import pytest
import respx

from ai_workflow.nodes.action.http_request import (
    HttpRequestNodeExecutor,
    _request_fingerprint,
)
from ai_workflow.nodes.base import ExecutionContext
from ai_workflow.runtime.persistence.action_keys import (
    ActionKeyConflictError,
    InMemoryActionKeyStore,
)
from ai_workflow.security.credentials import StaticCredentialResolver
from ai_workflow.security.http_client import SafeHttpClient
from ai_workflow.security.ssrf import fake_resolver

RUN_ID = UUID("44444444-4444-4444-8444-444444444401")
NODE_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1")
WORKFLOW_VERSION_ID = UUID("22222222-2222-4222-8222-222222222201")
ACTION_KEY = f"{RUN_ID}:{NODE_ID}"


def _base_config(**overrides: object) -> dict:
    config = {
        "method": "GET",
        "url_template": "https://api.example.com/items",
        "timeout_seconds": 5,
        "max_response_bytes": 1024,
        "max_redirects": 3,
    }
    config.update(overrides)
    return config


def _context(**overrides: object) -> ExecutionContext:
    values = {
        "run_id": RUN_ID,
        "workspace_id": UUID("11111111-1111-4111-8111-111111111101"),
        "project_id": UUID("66666666-6666-4666-8666-666666666601"),
        "workflow_version_id": WORKFLOW_VERSION_ID,
        "node_id": NODE_ID,
        "attempt": 1,
        "idempotency_key": ACTION_KEY,
    }
    values.update(overrides)
    return ExecutionContext(**values)


def _executor(
    *,
    store: InMemoryActionKeyStore | None = None,
    resolver: StaticCredentialResolver | None = None,
    client: httpx.AsyncClient | None = None,
) -> HttpRequestNodeExecutor:
    http_client = client or httpx.AsyncClient()
    return HttpRequestNodeExecutor(
        http_client=SafeHttpClient(
            http_client,
            resolver=fake_resolver({"api.example.com": ["93.184.216.34"]}),
        ),
        action_key_store=store or InMemoryActionKeyStore(),
        credential_resolver=resolver,
    )


@pytest.mark.asyncio
@respx.mock
async def test_http_get_success() -> None:
    route = respx.get("https://api.example.com/items").respond(200, json={"ok": True})
    executor = _executor()
    result = await executor.execute(_context(), _base_config(), {})
    response = result.outputs["response"]
    assert isinstance(response, dict)
    assert response["status_code"] == 200
    assert response["body"] == {"ok": True}
    assert route.called


@pytest.mark.asyncio
@respx.mock
async def test_http_blocks_localhost() -> None:
    route = respx.get("http://127.0.0.1/").respond(200, json={"ok": True})
    executor = _executor()
    with pytest.raises(ValueError, match="blocked"):
        await executor.execute(
            _context(),
            _base_config(url_template="http://127.0.0.1/"),
            {},
        )
    assert not route.called


@pytest.mark.asyncio
@respx.mock
async def test_http_blocks_redirect_to_private() -> None:
    public_route = respx.get("https://api.example.com/start").respond(
        302,
        headers={"location": "http://10.0.0.1/"},
    )
    private_route = respx.get("http://10.0.0.1/").respond(200, json={"ok": True})
    executor = _executor()
    with pytest.raises(ValueError, match="blocked"):
        await executor.execute(
            _context(),
            _base_config(url_template="https://api.example.com/start"),
            {},
        )
    assert public_route.called
    assert not private_route.called


@pytest.mark.asyncio
@respx.mock
async def test_http_idempotent_replay() -> None:
    route = respx.get("https://api.example.com/items").respond(200, json={"ok": True})
    store = InMemoryActionKeyStore()
    fingerprint = _request_fingerprint(
        method="GET", url="https://api.example.com/items", body=None
    )
    await store.put(
        action_key=ACTION_KEY,
        run_id=RUN_ID,
        node_id=NODE_ID,
        attempt=1,
        fingerprint=fingerprint,
        response={"status_code": 200, "headers": {}, "body": {"cached": True}, "body_text": None},
    )
    executor = _executor(store=store)
    result = await executor.execute(_context(), _base_config(), {})
    response = result.outputs["response"]
    assert isinstance(response, dict)
    assert response["body"] == {"cached": True}
    assert not route.called


@pytest.mark.asyncio
@respx.mock
async def test_http_persists_key() -> None:
    route = respx.get("https://api.example.com/items").respond(200, json={"ok": True})
    store = InMemoryActionKeyStore()
    executor = _executor(store=store)
    await executor.execute(_context(), _base_config(), {})
    cached = await store.get(action_key=ACTION_KEY)
    assert cached is not None
    assert cached.response["status_code"] == 200
    assert route.call_count == 1

    route.reset()
    route = respx.get("https://api.example.com/items").respond(200, json={"ok": False})
    result = await executor.execute(_context(), _base_config(), {})
    response = result.outputs["response"]
    assert isinstance(response, dict)
    assert response["body"] == {"ok": True}
    assert route.call_count == 0


@pytest.mark.asyncio
@respx.mock
async def test_http_redacts_sensitive_response_headers() -> None:
    respx.get("https://api.example.com/items").respond(
        200,
        headers={"authorization": "secret-token", "content-type": "application/json"},
        json={"ok": True},
    )
    executor = _executor()
    result = await executor.execute(_context(), _base_config(), {})
    response = result.outputs["response"]
    assert isinstance(response, dict)
    headers = response.get("headers")
    assert isinstance(headers, dict)
    assert "authorization" not in {key.lower() for key in headers}
    assert "secret-token" not in str(response)


@pytest.mark.asyncio
@respx.mock
async def test_http_resolves_header_auth_credential() -> None:
    route = respx.get("https://api.example.com/items").respond(200, json={"ok": True})
    resolver = StaticCredentialResolver({"header_auth": "Bearer sk-test"})
    executor = _executor(
        resolver=resolver,
        store=InMemoryActionKeyStore(),
    )
    context = _context(
        credential_refs={"header_auth": UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb1")},
    )
    await executor.execute(context, _base_config(), {})
    assert route.called
    assert route.calls.last.request.headers["Authorization"] == "Bearer sk-test"


@pytest.mark.asyncio
async def test_http_respects_timeout() -> None:
    executor = _executor()

    async def raise_timeout(*_args: object, **_kwargs: object) -> object:
        msg = "HTTP request timed out"
        raise ValueError(msg)

    executor._http_client.request = raise_timeout  # type: ignore[method-assign]
    with pytest.raises(ValueError, match="timed out"):
        await executor.execute(_context(), _base_config(timeout_seconds=1), {})


@pytest.mark.asyncio
@respx.mock
async def test_http_rejects_disallowed_method() -> None:
    route = respx.route(method="TRACE", url="https://api.example.com/items").respond(200)
    executor = _executor()
    with pytest.raises(ValueError, match="not allowed"):
        await executor.execute(_context(), _base_config(method="TRACE"), {})
    assert not route.called


@pytest.mark.asyncio
@respx.mock
async def test_http_replay_with_changed_fingerprint_conflicts() -> None:
    respx.post("https://api.example.com/items").respond(200, json={"ok": True})
    store = InMemoryActionKeyStore()
    await store.put(
        action_key=ACTION_KEY,
        run_id=RUN_ID,
        node_id=NODE_ID,
        attempt=1,
        fingerprint="stale-fingerprint",
        response={"status_code": 200, "headers": {}, "body": {"cached": True}, "body_text": None},
    )
    executor = _executor(store=store)
    with pytest.raises(ActionKeyConflictError, match="different request"):
        await executor.execute(
            _context(),
            _base_config(method="POST"),
            {"body": {"changed": "input"}},
        )


@pytest.mark.asyncio
@respx.mock
async def test_http_action_keys_scoped_per_foreach_item() -> None:
    route = respx.get("https://api.example.com/items").respond(200, json={"ok": True})
    store = InMemoryActionKeyStore()
    executor = _executor(store=store)

    # Two for-each items reuse the same run/node but distinct item-scoped keys.
    key_a = f"{RUN_ID}:{NODE_ID}:item-a"
    key_b = f"{RUN_ID}:{NODE_ID}:item-b"
    await executor.execute(_context(idempotency_key=key_a), _base_config(), {})
    await executor.execute(_context(idempotency_key=key_b), _base_config(), {})

    # Each item issued its own request and cached under its own key.
    assert route.call_count == 2
    assert await store.get(action_key=key_a) is not None
    assert await store.get(action_key=key_b) is not None
