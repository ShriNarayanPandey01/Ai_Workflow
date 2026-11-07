from __future__ import annotations

from pathlib import Path

import asyncpg

from ai_workflow.config.settings import Settings
from ai_workflow.nodes.action.http_request import HttpRequestNodeExecutor
from ai_workflow.nodes.ai.chat_model import ChatModelNodeExecutor
from ai_workflow.nodes.ai.prompt_template import PromptTemplateNodeExecutor
from ai_workflow.nodes.base import UnimplementedNodeExecutor
from ai_workflow.nodes.control.collect import CollectNodeExecutor
from ai_workflow.nodes.control.condition import ConditionNodeExecutor
from ai_workflow.nodes.control.for_each import ForEachNodeExecutor
from ai_workflow.nodes.control.loop import LoopNodeExecutor
from ai_workflow.nodes.control.merge import MergeNodeExecutor
from ai_workflow.nodes.data.input import InputNodeExecutor
from ai_workflow.nodes.data.output import OutputNodeExecutor
from ai_workflow.nodes.human.approval import HumanApprovalNodeExecutor
from ai_workflow.nodes.human.review import HumanReviewNodeExecutor
from ai_workflow.nodes.rag.retrieve import RetrieveNodeExecutor
from ai_workflow.providers.chat import ChatProvider, FakeChatProvider, build_chat_provider
from ai_workflow.providers.embedding import EmbeddingProvider, build_embedding_provider
from ai_workflow.rag.retrieve_store import (
    InMemoryRetrieveStore,
    PostgresRetrieveStore,
    RetrieveStore,
)
from ai_workflow.runtime.persistence.action_keys import ActionKeyStore
from ai_workflow.runtime.persistence.artifact_store import (
    FilesystemArtifactStore,
    InMemoryArtifactStore,
)
from ai_workflow.runtime.registry.registry import RuntimeRegistry
from ai_workflow.security.credentials import (
    CredentialResolver,
    StaticCredentialResolver,
    build_credential_resolver,
)
from ai_workflow.security.http_client import SafeHttpClient, create_async_client
from ai_workflow.tasks.research import (
    CleanupExecuteTaskExecutor,
    CleanupPlanTaskExecutor,
    DeepResearchTaskExecutor,
)


def build_runner_registry(
    contracts_root: Path,
    *,
    chat_provider: ChatProvider | None = None,
    credential_resolver: CredentialResolver | None = None,
    safe_http_client: SafeHttpClient | None = None,
    action_key_store: ActionKeyStore | None = None,
    retrieve_store: RetrieveStore | None = None,
    embedding_provider: EmbeddingProvider | None = None,
    pool: asyncpg.Pool | None = None,
    max_loop_iterations: int = 100,
    max_fan_out_items: int = 1000,
    settings: Settings | None = None,
) -> RuntimeRegistry:
    """Register all built-in node executors for the workflow runtime."""
    if chat_provider is not None:
        provider = chat_provider
    elif settings is not None:
        provider = build_chat_provider(
            fake_llm=settings.fake_llm,
            api_key=settings.baseten_api_key,
            base_url=settings.chat_base_url,
        )
    else:
        provider = FakeChatProvider()

    resolver = credential_resolver
    if resolver is None and settings is not None:
        resolver = build_credential_resolver(
            control_plane_url=settings.control_plane_internal_url,
            internal_auth_token=settings.internal_auth_token,
            chat_api_key=settings.baseten_api_key,
        )
    if resolver is None:
        resolver = StaticCredentialResolver({})

    http_client = safe_http_client or SafeHttpClient(create_async_client())

    if embedding_provider is not None:
        embedder = embedding_provider
    elif settings is not None:
        embedder = build_embedding_provider(
            fake_embeddings=settings.fake_embeddings,
            gemini_api_key=settings.gemini_api_key,
            dimensions=settings.embedding_dimensions,
        )
    else:
        embedder = build_embedding_provider(fake_embeddings=True)

    if retrieve_store is not None:
        store = retrieve_store
    elif pool is not None:
        store = PostgresRetrieveStore(pool)
    else:
        store = InMemoryRetrieveStore()

    embedding_model = (
        settings.embedding_model if settings is not None else "gemini-embedding-001"
    )
    embedding_dimensions = settings.embedding_dimensions if settings is not None else 1536

    registry = RuntimeRegistry(contracts_root=contracts_root)
    registry.register_node(lambda: InputNodeExecutor(), node_type="data.input@1")
    registry.register_node(lambda: OutputNodeExecutor(), node_type="data.output@1")
    registry.register_node(lambda: ConditionNodeExecutor(), node_type="control.condition@1")
    registry.register_node(lambda: MergeNodeExecutor(), node_type="control.merge@1")
    registry.register_node(
        lambda: LoopNodeExecutor(platform_max_iterations=max_loop_iterations),
        node_type="control.loop@1",
    )
    artifact_store = (
        FilesystemArtifactStore(settings.artifact_dir)
        if settings is not None
        else InMemoryArtifactStore()
    )
    registry.register_node(
        lambda: ForEachNodeExecutor(platform_max_fan_out_items=max_fan_out_items),
        node_type="control.for-each@1",
    )
    registry.register_node(
        lambda: CollectNodeExecutor(artifact_store=artifact_store),
        node_type="control.collect@1",
    )
    registry.register_node(
        lambda: PromptTemplateNodeExecutor(),
        node_type="ai.prompt-template@1",
    )
    registry.register_node(
        lambda: ChatModelNodeExecutor(
            provider=provider,
            credential_resolver=resolver,
            default_base_url=settings.chat_base_url
            if settings is not None
            else "https://inference.baseten.co/v1",
        ),
        node_type="ai.chat-model@1",
    )
    registry.register_node(lambda: HumanApprovalNodeExecutor(), node_type="human.approval@1")
    registry.register_node(lambda: HumanReviewNodeExecutor(), node_type="human.review@1")
    registry.register_node(
        lambda: HttpRequestNodeExecutor(
            http_client=http_client,
            action_key_store=action_key_store,
            credential_resolver=resolver,
        ),
        node_type="action.http-request@1",
    )
    registry.register_node(
        lambda: RetrieveNodeExecutor(
            store=store,
            embedding_provider=embedder,
            embedding_model=embedding_model,
            embedding_dimensions=embedding_dimensions,
        ),
        node_type="rag.retrieve@1",
    )
    # F16 domain nodes that are catalogued as inline but not yet implemented in
    # this engine build. Register loud placeholders so strict_catalog can stay on
    # (guarding every in-scope inline node) without failing startup; executing one
    # raises NotImplementedError rather than a bare registry KeyError.
    for unbuilt_node_type in ("market.momentum-screen@1", "market.price-history@1"):
        registry.register_node(
            lambda node_type=unbuilt_node_type: UnimplementedNodeExecutor(node_type),
            node_type=unbuilt_node_type,
        )
    registry.register_task(lambda: DeepResearchTaskExecutor(), task_type="research.deep-research@1")
    registry.register_task(lambda: CleanupPlanTaskExecutor(), task_type="action.cleanup-plan@1")
    registry.register_task(
        lambda: CleanupExecuteTaskExecutor(),
        task_type="action.cleanup-execute@1",
    )
    # strict_catalog=True: refuse startup if any inline execution-engine node in
    # the catalog lacks an executor. Durable-task nodes are exempt (see registry).
    return registry.build(strict_catalog=True)
