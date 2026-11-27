import json
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from ai_workflow.messaging.envelope import EnvelopeValidator, ExecutionSubject, MessageEnvelope
from ai_workflow.messaging.publisher import EventPublisher
from ai_workflow.runtime.engine.engine import WorkflowRunWaiting, run_workflow
from ai_workflow.runtime.registry.bootstrap import build_runner_registry
from ai_workflow.worker.handler import _publish_outcome


@pytest.mark.asyncio
async def test_emitted_lifecycle_events_match_consumer_contract(repo_contracts_root):
    fixtures = repo_contracts_root / 'fixtures' / 'valid'
    source = MessageEnvelope.model_validate_json(
        (fixtures / 'envelope-execution-start.json').read_bytes()
    )
    subject = ExecutionSubject.model_validate(source.subject)
    channel = AsyncMock()
    exchange = channel.get_exchange.return_value
    publisher = EventPublisher(
        pool=MagicMock(), channel=channel, source_envelope=source, subject=subject
    )
    publisher.allocate_sequence = AsyncMock(side_effect=range(1, 5))
    validator = EnvelopeValidator(repo_contracts_root)
    node_id = uuid4()
    await publisher.publish_node_started(node_id=node_id, node_type='data.input@1')
    await publisher.publish_node_completed(node_id=node_id, node_type='data.input@1', outputs={})
    await publisher.publish_node_failed(node_id=node_id, node_type='data.input@1', message='error')

    definition = json.loads((fixtures / 'workflow-e2e-durable-task.json').read_bytes())
    dispatcher = AsyncMock()
    outcome = await run_workflow(definition, {'question': 'test'}, run_id=subject.run_id,
                                 registry=build_runner_registry(repo_contracts_root),
                                 contracts_root=repo_contracts_root, task_dispatcher=dispatcher)
    assert isinstance(outcome, WorkflowRunWaiting)
    await _publish_outcome(publisher, outcome)
    events = [json.loads(call.args[0].body) for call in exchange.publish.await_args_list]
    assert len(events) == 4
    for event in events:
        validator.validate(event)
    for event in events[:3]:
        assert event['subject']['node_id'] == event['payload']['node_id'] == str(node_id)
    assert events[-1]['subject']['node_id'] is None
    task = dispatcher.start_task.await_args.kwargs
    assert events[-1]['payload']['task_ref'] == {
        'task_id': str(task['task_id']), 'task_type': task['task_type']
    }
    assert events[-1]['payload'].get('approval_request') is None
