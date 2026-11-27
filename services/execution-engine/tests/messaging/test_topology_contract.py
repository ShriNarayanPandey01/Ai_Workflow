from unittest.mock import AsyncMock

import aio_pika
import pytest

from ai_workflow.messaging.broker import MessagingNames, RabbitBroker


@pytest.mark.asyncio
async def test_control_event_queue_matches_control_plane_dead_letter_arguments() -> None:
    channel = AsyncMock()
    await RabbitBroker().declare_topology(channel)
    declaration = next(
        call
        for call in channel.declare_queue.await_args_list
        if call.args[0] == MessagingNames.CONTROL_EVENTS_QUEUE
    )
    assert declaration.kwargs["arguments"] == {
        "x-dead-letter-exchange": MessagingNames.DEAD_LETTER_EXCHANGE,
        "x-dead-letter-routing-key": "rejected",
    }


@pytest.mark.asyncio
async def test_declare_durable_queue_reuses_existing_queue_on_precondition_failed() -> None:
    existing_queue = AsyncMock()
    channel = AsyncMock()
    channel.declare_queue.side_effect = [
        aio_pika.exceptions.ChannelPreconditionFailed("PRECONDITION_FAILED"),
        existing_queue,
    ]

    result = await RabbitBroker().declare_durable_queue(
        channel, MessagingNames.CONTROL_EVENTS_QUEUE
    )

    assert result is existing_queue
    channel.reopen.assert_awaited_once()
    assert channel.declare_queue.await_args_list[1].args == (MessagingNames.CONTROL_EVENTS_QUEUE,)
    assert channel.declare_queue.await_args_list[1].kwargs == {"passive": True}
