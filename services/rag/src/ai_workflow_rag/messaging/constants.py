from __future__ import annotations

COMMANDS_EXCHANGE = "aiw.commands.v1"
EVENTS_EXCHANGE = "aiw.events.v1"
DEAD_LETTER_EXCHANGE = "aiw.dead.v1"

INGESTION_COMMANDS_QUEUE = "aiw.ingestion.commands.v1"

DOCUMENT_INGEST_ROUTING_KEY = "document.ingest.v1"
DOCUMENT_DELETE_ROUTING_KEY = "document.delete.v1"
DOCUMENT_INGESTION_STARTED_ROUTING_KEY = "document.ingestion.started.v1"
DOCUMENT_INGESTION_COMPLETED_ROUTING_KEY = "document.ingestion.completed.v1"
DOCUMENT_INGESTION_FAILED_ROUTING_KEY = "document.ingestion.failed.v1"

INGESTION_COMMANDS_BINDING = "document.*.v1"
