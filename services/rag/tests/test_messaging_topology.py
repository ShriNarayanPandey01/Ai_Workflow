from unittest.mock import AsyncMock

import aio_pika
import pytest

from ai_workflow_rag.messaging import constants as mq
from ai_workflow_rag.messaging.topology import declare_ingestion_queue, declare_topology


@pytest.mark.asyncio
async def test_ingestion_queue_matches_control_plane_dead_letter_arguments() -> None:
    channel = AsyncMock()
    await declare_topology(channel)
    assert channel.declare_queue.await_args.kwargs["arguments"] == {
        "x-dead-letter-exchange": "aiw.dead.v1",
        "x-dead-letter-routing-key": "rejected",
    }


@pytest.mark.asyncio
async def test_declare_ingestion_queue_reuses_existing_queue_on_precondition_failed() -> None:
    existing_queue = AsyncMock()
    channel = AsyncMock()
    channel.declare_queue.side_effect = [
        aio_pika.exceptions.ChannelPreconditionFailed("PRECONDITION_FAILED"),
        existing_queue,
    ]

    result = await declare_ingestion_queue(channel)

    assert result is existing_queue
    channel.reopen.assert_awaited_once()
    assert channel.declare_queue.await_args_list[1].args == (mq.INGESTION_COMMANDS_QUEUE,)
    assert channel.declare_queue.await_args_list[1].kwargs == {"passive": True}
