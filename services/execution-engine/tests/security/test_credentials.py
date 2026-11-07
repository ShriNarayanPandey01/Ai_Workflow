from __future__ import annotations

from uuid import UUID

import httpx
import pytest
import respx

from ai_workflow.nodes.ai.chat_model import ChatModelNodeExecutor
from ai_workflow.nodes.base import ExecutionContext
from ai_workflow.providers.chat import FakeChatProvider
from ai_workflow.security.credentials import (
    EnvCredentialResolver,
    HttpCredentialResolver,
    StaticCredentialResolver,
)


@pytest.mark.asyncio
async def test_static_resolver_returns_slots() -> None:
    resolver = StaticCredentialResolver({"provider": "sk-test"})
    result = await resolver.resolve(
        run_id=UUID("44444444-4444-4444-8444-444444444401"),
        node_id=UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1"),
        workflow_version_id=UUID("22222222-2222-4222-8222-222222222201"),
        slots=["provider"],
    )
    assert result["provider"] == "sk-test"


@pytest.mark.asyncio
async def test_env_resolver_requires_provider_key() -> None:
    resolver = EnvCredentialResolver(None)
    with pytest.raises(ValueError, match="provider"):
        await resolver.resolve(
            run_id=UUID("44444444-4444-4444-8444-444444444401"),
            node_id=UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1"),
            workflow_version_id=None,
            slots=["provider"],
        )


@respx.mock
@pytest.mark.asyncio
async def test_http_resolver_calls_control_plane() -> None:
    run_id = UUID("44444444-4444-4444-8444-444444444401")
    node_id = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1")
    route = respx.post(
        f"http://control-plane/internal/v1/executions/{run_id}/credentials:resolve"
    ).respond(
        200,
        json={"credentials": {"provider": "sk-resolved"}},
    )
    async with httpx.AsyncClient() as client:
        resolver = HttpCredentialResolver(
            base_url="http://control-plane",
            client=client,
        )
        result = await resolver.resolve(
            run_id=run_id,
            node_id=node_id,
            workflow_version_id=UUID("22222222-2222-4222-8222-222222222201"),
            slots=["provider"],
        )
    assert result["provider"] == "sk-resolved"
    assert route.called


@pytest.mark.asyncio
async def test_chat_model_uses_credential_resolver() -> None:
    resolver = StaticCredentialResolver({"provider": "sk-test"})
    executor = ChatModelNodeExecutor(
        provider=FakeChatProvider(),
        credential_resolver=resolver,
    )
    context = ExecutionContext(
        run_id=UUID("44444444-4444-4444-8444-444444444401"),
        workspace_id=UUID("11111111-1111-4111-8111-111111111101"),
        project_id=UUID("66666666-6666-4666-8666-666666666601"),
        workflow_version_id=UUID("22222222-2222-4222-8222-222222222201"),
        node_id=UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1"),
        attempt=1,
        credential_refs={"provider": UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa9")},
        credential_resolver=resolver,
    )
    with respx.mock:
        respx.post("https://inference.baseten.co/v1/chat/completions").respond(
            200,
            json={
                "choices": [{"message": {"content": "hello back"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
            },
        )
        result = await executor.execute(
            context,
            {"model": "meta-models/muse-spark-open-1026"},
            {"prompt": {"text": "hello"}},
        )
    assert "response" in result.outputs
    assert "sk-test" not in str(result.outputs)


@respx.mock
@pytest.mark.asyncio
async def test_http_resolver_error_does_not_include_body() -> None:
    run_id = UUID("44444444-4444-4444-8444-444444444401")
    respx.post(
        f"http://control-plane/internal/v1/executions/{run_id}/credentials:resolve"
    ).respond(403, json={"credentials": {"provider": "sk-should-not-leak"}})
    async with httpx.AsyncClient() as client:
        resolver = HttpCredentialResolver(
            base_url="http://control-plane",
            client=client,
        )
        with pytest.raises(ValueError, match="status 403") as exc_info:
            await resolver.resolve(
                run_id=run_id,
                node_id=UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1"),
                workflow_version_id=None,
                slots=["provider"],
            )
    assert "sk-should-not-leak" not in str(exc_info.value)


@respx.mock
@pytest.mark.asyncio
async def test_http_resolver_rejects_empty_slot() -> None:
    run_id = UUID("44444444-4444-4444-8444-444444444401")
    respx.post(
        f"http://control-plane/internal/v1/executions/{run_id}/credentials:resolve"
    ).respond(200, json={"credentials": {"provider": ""}})
    async with httpx.AsyncClient() as client:
        resolver = HttpCredentialResolver(
            base_url="http://control-plane",
            client=client,
        )
        with pytest.raises(ValueError, match="was not resolved"):
            await resolver.resolve(
                run_id=run_id,
                node_id=UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1"),
                workflow_version_id=None,
                slots=["provider"],
            )


def test_build_resolver_prefers_http_when_control_plane_url_set() -> None:
    from ai_workflow.security.credentials import build_credential_resolver

    resolver = build_credential_resolver(
        control_plane_url="http://control-plane",
        internal_auth_token="tok",
        chat_api_key="baseten-env",
        client=httpx.AsyncClient(),
    )
    assert isinstance(resolver, HttpCredentialResolver)


def test_build_resolver_falls_back_to_env_without_control_plane() -> None:
    from ai_workflow.security.credentials import build_credential_resolver

    resolver = build_credential_resolver(
        control_plane_url=None,
        internal_auth_token=None,
        chat_api_key="baseten-env",
    )
    assert isinstance(resolver, EnvCredentialResolver)


def test_event_payload_redacts_planted_api_key() -> None:
    from ai_workflow.security.redaction import REDACTED, redact_value

    payload = {"outputs": {"api_key": "sk-planted", "text": "ok"}}
    redacted = redact_value(payload)
    assert redacted["outputs"]["api_key"] == REDACTED
    assert redacted["outputs"]["text"] == "ok"
