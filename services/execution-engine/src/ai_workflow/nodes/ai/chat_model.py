from __future__ import annotations

from ai_workflow.contracts.common.types import JsonValue
from ai_workflow.nodes.base import ExecutionContext, NodeResult, TransientNodeError
from ai_workflow.providers.chat import (
    ChatMessage,
    ChatProvider,
    ChatRequest,
    FakeChatProvider,
    OpenAICompatibleChatProvider,
    TransientChatError,
)
from ai_workflow.security.credentials import CredentialResolver


class ChatModelNodeExecutor:
    node_type = "ai.chat-model@1"

    def __init__(
        self,
        provider: ChatProvider | None = None,
        credential_resolver: CredentialResolver | None = None,
        default_base_url: str = "https://api.openai.com/v1",
    ) -> None:
        self._default_provider = provider or FakeChatProvider()
        self._credential_resolver = credential_resolver
        self._default_base_url = default_base_url.rstrip("/")

    async def execute(
        self,
        context: ExecutionContext,
        config: dict[str, JsonValue],
        inputs: dict[str, JsonValue],
    ) -> NodeResult:
        model = config.get("model")
        if not isinstance(model, str) or not model:
            msg = "ai.chat-model@1 requires config.model"
            raise ValueError(msg)

        prompt = inputs.get("prompt")
        if not isinstance(prompt, dict):
            msg = "ai.chat-model@1 requires object input port 'prompt'"
            raise ValueError(msg)

        provider = self._default_provider
        resolver = context.credential_resolver or self._credential_resolver
        if resolver is not None and context.credential_refs:
            slots = list(context.credential_refs.keys()) or ["provider"]
            resolved = await resolver.resolve(
                run_id=context.run_id,
                node_id=context.node_id,
                workflow_version_id=context.workflow_version_id,
                slots=slots,
            )
            api_key = resolved.get("provider")
            if not api_key:
                msg = "Credential slot 'provider' was not resolved"
                raise ValueError(msg)
            base_url = str(config.get("base_url", self._default_base_url))
            provider = OpenAICompatibleChatProvider(api_key=api_key, base_url=base_url)

        messages = _build_messages(prompt)
        temperature = config.get("temperature")
        max_output_tokens = config.get("max_output_tokens")
        timeout_seconds = config.get("timeout_seconds", 60)
        response_format = config.get("response_format", "text")

        request = ChatRequest(
            model=model,
            messages=messages,
            temperature=float(temperature) if isinstance(temperature, (int, float)) else None,
            max_output_tokens=int(max_output_tokens)
            if isinstance(max_output_tokens, int)
            else None,
            response_format=str(response_format) if response_format else "text",
            timeout_seconds=int(timeout_seconds) if isinstance(timeout_seconds, int) else 60,
        )
        try:
            completion = await provider.complete(request)
        except TransientChatError as exc:
            # Surface as a runner-recognized transient failure so the
            # workflow's RetryPolicy governs node-level retries.
            msg = f"Chat provider transient failure: {exc}"
            raise TransientNodeError(msg) from exc
        return NodeResult(
            outputs={
                "response": {
                    "text": completion.text,
                    "usage": completion.usage.as_dict(),
                }
            }
        )

def _build_messages(prompt: dict[str, JsonValue]) -> list[ChatMessage]:
    raw_messages = prompt.get("messages")
    if isinstance(raw_messages, list) and raw_messages:
        messages: list[ChatMessage] = []
        for item in raw_messages:
            if not isinstance(item, dict):
                continue
            role = item.get("role", "user")
            content = item.get("content")
            if isinstance(role, str) and isinstance(content, str):
                messages.append(ChatMessage(role=role, content=content))
        if messages:
            return messages

    text = prompt.get("text")
    if isinstance(text, str) and text:
        return [ChatMessage(role="user", content=text)]

    msg = "Chat prompt must include text or messages"
    raise ValueError(msg)
