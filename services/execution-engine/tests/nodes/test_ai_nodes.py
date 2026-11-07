from __future__ import annotations

from uuid import uuid4

import httpx
import pytest
import respx

from ai_workflow.nodes.ai.chat_model import ChatModelNodeExecutor
from ai_workflow.nodes.ai.prompt_template import PromptTemplateNodeExecutor
from ai_workflow.nodes.base import ExecutionContext
from ai_workflow.providers.chat import (
    ChatMessage,
    ChatRequest,
    FakeChatProvider,
    OpenAICompatibleChatProvider,
    is_retryable_status,
)


def _context() -> ExecutionContext:
    return ExecutionContext(
        run_id=uuid4(),
        workspace_id=uuid4(),
        project_id=uuid4(),
        workflow_version_id=uuid4(),
        node_id=uuid4(),
        attempt=1,
    )


@pytest.mark.asyncio
async def test_prompt_template_renders_variables() -> None:
    executor = PromptTemplateNodeExecutor()
    result = await executor.execute(
        _context(),
        {"template": "Hello {{name}}", "required_variables": ["name"]},
        {"variables": {"name": "Ada"}},
    )
    assert result.outputs["text"]["text"] == "Hello Ada"


@pytest.mark.asyncio
async def test_prompt_template_missing_required_variable() -> None:
    executor = PromptTemplateNodeExecutor()
    with pytest.raises(ValueError, match="Missing required template variables"):
        await executor.execute(
            _context(),
            {"template": "Hello {{name}}", "required_variables": ["name"]},
            {"variables": {}},
        )


@pytest.mark.asyncio
async def test_chat_model_with_fake_provider() -> None:
    provider = FakeChatProvider(response_text="ok")
    executor = ChatModelNodeExecutor(provider=provider)
    result = await executor.execute(
        _context(),
        {"model": "gpt-test"},
        {"prompt": {"text": "hi"}},
    )
    assert result.outputs["response"]["text"] == "ok"
    assert "usage" in result.outputs["response"]
    assert provider.calls[0].model == "gpt-test"


def test_retryable_status_classification() -> None:
    assert is_retryable_status(429)
    assert is_retryable_status(503)
    assert not is_retryable_status(400)


@pytest.mark.asyncio
@respx.mock
async def test_baseten_compatible_retries_429_then_succeeds() -> None:
    route = respx.post("https://inference.baseten.co/v1/chat/completions").mock(
        side_effect=[
            httpx.Response(429, json={"error": "rate limit"}),
            httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": "hello"}}],
                    "usage": {
                        "prompt_tokens": 1,
                        "completion_tokens": 1,
                        "total_tokens": 2,
                    },
                },
            ),
        ]
    )
    provider = OpenAICompatibleChatProvider(
        api_key="test-key",
        base_url="https://inference.baseten.co/v1",
        max_attempts=3,
        initial_backoff_ms=1,
        max_backoff_ms=2,
    )
    completion = await provider.complete(
        ChatRequest(
            model="gpt-test",
            messages=[ChatMessage(role="user", content="hi")],
            timeout_seconds=5,
        )
    )
    assert completion.text == "hello"
    assert route.call_count == 2
    await provider.aclose()
