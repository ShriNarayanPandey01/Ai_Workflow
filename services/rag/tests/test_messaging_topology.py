from unittest.mock import AsyncMock

import pytest

from ai_workflow_rag.messaging.topology import declare_topology


@pytest.mark.asyncio
async def test_ingestion_queue_matches_control_plane_dead_letter_arguments() -> None:
    channel = AsyncMock()
    await declare_topology(channel)
    assert channel.declare_queue.await_args.kwargs["arguments"] == {
        "x-dead-letter-exchange": "aiw.dead.v1",
        "x-dead-letter-routing-key": "rejected",
    }
