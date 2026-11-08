from __future__ import annotations

import json
import logging
from typing import Any

import aio_pika
import asyncpg
import httpx

from ai_workflow_rag.config.settings import Settings
from ai_workflow_rag.messaging import constants as mq
from ai_workflow_rag.messaging.envelope import (
    parse_document_delete,
    parse_document_ingest,
)
from ai_workflow_rag.messaging.inbox import ClaimResult, PostgresInbox
from ai_workflow_rag.messaging.publisher import DocumentEventPublisher
from ai_workflow_rag.messaging.validation import (
    EnvelopeValidationError,
    validate_envelope_document,
)
from ai_workflow_rag.pipeline.ingest import IngestCommand, IngestPipeline
from ai_workflow_rag.providers.embedding import EmbeddingProvider, build_embedding_provider
from ai_workflow_rag.security.download_intent import (
    DownloadIntentClient,
    HttpDownloadIntentClient,
)
from ai_workflow_rag.store.store import RagStore

logger = logging.getLogger(__name__)


class MessageInFlightError(RuntimeError):
    """Raised when a duplicate message is still being processed."""


class IngestionCommandHandler:
    def __init__(
        self,
        *,
        settings: Settings,
        pool: asyncpg.Pool,
        channel: aio_pika.abc.AbstractChannel,
        inbox: PostgresInbox,
        store: RagStore,
        pipeline: IngestPipeline,
    ) -> None:
        self._settings = settings
        self._pool = pool
        self._channel = channel
        self._inbox = inbox
        self._store = store
        self._pipeline = pipeline

    async def handle(self, body: bytes) -> None:
        try:
            document = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise EnvelopeValidationError(f"Invalid JSON body: {exc}") from exc
        if not isinstance(document, dict):
            raise EnvelopeValidationError("Envelope must be a JSON object")

        validate_envelope_document(
            document,
            contracts_root=self._settings.contracts_root,
            source="ingestion",
        )
        message_type = document.get("message_type")
        if message_type == "document.ingest":
            await self._handle_ingest(document)
        elif message_type == "document.delete":
            await self._handle_delete(document)
        else:
            raise EnvelopeValidationError(f"Unsupported message_type: {message_type}")

    async def _handle_ingest(self, document: dict[str, Any]) -> None:
        parsed = parse_document_ingest(document)
        claim = await self._inbox.claim(
            message_id=parsed.envelope.message_id,
            document_id=parsed.subject.document_id,
            message_type=parsed.envelope.message_type,
        )
        if claim is ClaimResult.DUPLICATE_COMPLETED:
            logger.info("Skipping duplicate completed ingest %s", parsed.envelope.message_id)
            return
        if claim is ClaimResult.DUPLICATE_IN_FLIGHT:
            raise MessageInFlightError(str(parsed.envelope.message_id))

        publisher = DocumentEventPublisher(
            channel=self._channel,
            tenant=parsed.envelope.tenant,
            correlation_id=parsed.envelope.correlation_id,
            causation_id=parsed.envelope.message_id,
            document_id=parsed.subject.document_id,
        )

        await publisher.publish(
            message_type="document.ingestion.started",
            routing_key=mq.DOCUMENT_INGESTION_STARTED_ROUTING_KEY,
            payload={
                "document_id": str(parsed.payload.document_id),
                "dataset_id": str(parsed.payload.dataset_id),
                "status": "ingesting",
                "version": parsed.payload.version,
            },
            idempotency_suffix="document.ingestion.started",
        )

        command = IngestCommand(
            workspace_id=parsed.envelope.tenant.workspace_id,
            project_id=parsed.envelope.tenant.project_id,
            dataset_id=parsed.payload.dataset_id,
            document_id=parsed.payload.document_id,
            object_key=parsed.payload.object_key,
            content_hash=parsed.payload.content_hash,
            media_type=parsed.payload.media_type,
            size_bytes=parsed.payload.size_bytes,
            version=parsed.payload.version,
            original_name=parsed.payload.original_name,
            embedding_config=dict(parsed.payload.embedding_config),
        )
        result = await self._pipeline.ingest(command)

        if result.status == "ready":
            await publisher.publish(
                message_type="document.ingestion.completed",
                routing_key=mq.DOCUMENT_INGESTION_COMPLETED_ROUTING_KEY,
                payload={
                    "document_id": str(parsed.payload.document_id),
                    "dataset_id": str(parsed.payload.dataset_id),
                    "status": "ready",
                    "version": result.version,
                    "chunk_count": result.chunk_count,
                    "content_hash": result.content_hash,
                },
                idempotency_suffix="document.ingestion.completed",
            )
            await self._inbox.mark_completed(message_id=parsed.envelope.message_id)
            return

        await publisher.publish(
            message_type="document.ingestion.failed",
            routing_key=mq.DOCUMENT_INGESTION_FAILED_ROUTING_KEY,
            payload={
                "document_id": str(parsed.payload.document_id),
                "dataset_id": str(parsed.payload.dataset_id),
                "status": "failed",
                "error_code": result.error_code or "INGEST_FAILED",
                "message": result.error_message,
            },
            idempotency_suffix="document.ingestion.failed",
        )
        await self._inbox.mark_failed(message_id=parsed.envelope.message_id)

    async def _handle_delete(self, document: dict[str, Any]) -> None:
        parsed = parse_document_delete(document)
        claim = await self._inbox.claim(
            message_id=parsed.envelope.message_id,
            document_id=parsed.subject.document_id,
            message_type=parsed.envelope.message_type,
        )
        if claim is ClaimResult.DUPLICATE_COMPLETED:
            logger.info("Skipping duplicate completed delete %s", parsed.envelope.message_id)
            return
        if claim is ClaimResult.DUPLICATE_IN_FLIGHT:
            raise MessageInFlightError(str(parsed.envelope.message_id))

        if parsed.payload.delete_vectors:
            await self._store.delete_document_vectors(
                workspace_id=parsed.envelope.tenant.workspace_id,
                project_id=parsed.envelope.tenant.project_id,
                dataset_id=parsed.payload.dataset_id,
                document_id=parsed.payload.document_id,
            )
        # Object delete is best-effort and skipped unless MinIO is configured later.
        await self._inbox.mark_completed(message_id=parsed.envelope.message_id)


def build_ingestion_handler(
    *,
    settings: Settings,
    pool: asyncpg.Pool,
    channel: aio_pika.abc.AbstractChannel,
    download_client: DownloadIntentClient | None = None,
    embedding_provider: EmbeddingProvider | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> IngestionCommandHandler:
    store = RagStore(pool)
    inbox = PostgresInbox(pool)
    provider = embedding_provider or build_embedding_provider(
        fake_embeddings=settings.fake_embeddings,
        gemini_api_key=settings.gemini_api_key,
        dimensions=settings.embedding_dimensions,
    )
    resolved_download = download_client
    if resolved_download is None:
        if not settings.control_plane_internal_url:
            msg = "AIW_CONTROL_PLANE_INTERNAL_URL is required for ingest"
            raise RuntimeError(msg)
        resolved_download = HttpDownloadIntentClient(
            base_url=settings.control_plane_internal_url,
            auth_token=settings.internal_auth_token,
            client=http_client,
        )
    pipeline = IngestPipeline(
        store=store,
        download_client=resolved_download,
        embedding_provider=provider,
        http_client=http_client,
        embedding_model=settings.embedding_model,
        embedding_dimensions=settings.embedding_dimensions,
        chunk_size=settings.chunk_size_chars,
        chunk_overlap=settings.chunk_overlap_chars,
    )
    return IngestionCommandHandler(
        settings=settings,
        pool=pool,
        channel=channel,
        inbox=inbox,
        store=store,
        pipeline=pipeline,
    )
