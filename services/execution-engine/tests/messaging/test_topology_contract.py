from unittest.mock import AsyncMock

import pytest

from ai_workflow.messaging.broker import MessagingNames, RabbitBroker


@pytest.mark.asyncio
async def test_control_event_queue_matches_control_plane_dead_letter_arguments() -> None:
    channel = AsyncMock()
    await RabbitBroker().declare_topology(channel)
    declaration = next(
        call for call in channel.declare_queue.await_args_list
        if call.args[0] == MessagingNames.CONTROL_EVENTS_QUEUE
    )
    assert declaration.kwargs["arguments"] == {
        "x-dead-letter-exchange": MessagingNames.DEAD_LETTER_EXCHANGE,
        "x-dead-letter-routing-key": "rejected",
    }
