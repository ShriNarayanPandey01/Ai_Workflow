#!/usr/bin/env python3
"""Control-plane mimic: exercise implemented engine features except RAG.

Runs shared fixtures plus extra edge-case graphs over real Postgres + RabbitMQ
with a live OpenAI-compatible chat model and live HTTP (httpbin.org):

  F5  field bindings / pass-through
  F6  duplicate execution.start (inbox)
  F7  condition, merge (fan-out), bounded loop
  F8  prompt-template / chat-model; missing required variable
  F9  cancel while waiting; late resume must not continue
  F10 credentials on the live chat path (never appear in events)
  F11 approval approve/reject/review; invalid resume then valid resume
  F12 HTTP + SSRF (loopback blocked)
  F14 for-each/collect, overflow artifact_ref, over-cap rejection
  F15 research.deep-research@1
  F16 cleanup-plan@1 (stub executor)

Excludes: rag.retrieve (owned by services/rag). Market screen/price-history
nodes are unimplemented placeholders and are not started.

Prerequisites (from repo root):
    docker compose up -d postgres rabbitmq
    docker compose stop execution-worker task-worker

Requires OPENAI_API_KEY (or a ZenMux API key) in services/execution-engine/.env
(AIW_FAKE_LLM must not be true).

Usage:
    cd services/execution-engine
    uv run python scripts/trigger_full_features_workflow.py
    uv run python scripts/trigger_full_features_workflow.py --interactive
    uv run python scripts/trigger_full_features_workflow.py --skip-edges
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from typing import Any
from uuid import UUID

from e2e_helpers import (
    WAIT_TIMEOUT_SECONDS,
    E2ERuntime,
    assert_path_invariants,
    build_start_envelope,
    chat_response_from_events,
    collect_result_from_events,
    events_for_run,
    fail,
    load_json,
    mint_cancel_envelope,
    mint_resume_envelope,
    node_completed_ids,
    ok,
    prepare_live_workflow,
    print_llm_response,
    prompt_human_decision,
    prompt_human_review_value,
    publish_command,
    query_interrupt_from_checkpoint,
    setup_runtime,
    teardown_runtime,
    wait_for_terminal,
)

from ai_workflow.config.settings import REPO_ROOT
from ai_workflow.messaging.broker import MessagingNames as mq

logger = logging.getLogger(__name__)

HTTP_NODE_ID = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeee07"
CHAT_NODE_ID = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeee04"
PROMPT_NODE_ID = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeee03"
MERGE_NODE_ID = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeee06"
FOR_EACH_NODE_ID = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeee11"
COLLECT_NODE_ID = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeee08"
APPROVAL_NODE_ID = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeee05"
REVIEW_NODE_ID = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeee12"
LOOP_NODE_ID = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeee13"
LOW_OUTPUT_NODE_ID = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeee10"
LINEAR_APPROVAL_NODE_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaab02"
FOREACH_COLLECT_NODE_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaad04"
FANOUT_MERGE_NODE_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaab04"

FIXTURES_DIR = REPO_ROOT / "contracts" / "fixtures" / "valid"
FULL_FIXTURE = FIXTURES_DIR / "workflow-e2e-full-features.json"
DURABLE_FIXTURE = FIXTURES_DIR / "workflow-e2e-durable-task.json"
BINDINGS_FIXTURE = FIXTURES_DIR / "workflow-field-bindings.json"
LINEAR_FIXTURE = FIXTURES_DIR / "workflow-linear.json"
APPROVAL_FIXTURE = FIXTURES_DIR / "workflow-human-approval.json"
FOREACH_COLLECT_FIXTURE = FIXTURES_DIR / "workflow-for-each-collect.json"
FOREACH_CAP_FIXTURE = (
    REPO_ROOT / "contracts" / "fixtures" / "invalid" / "workflow-for-each-over-cap.json"
)
FANOUT_FIXTURE = FIXTURES_DIR / "workflow-fan-out-fan-in.json"
RESEARCH_NODE_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaae02"
CLEANUP_NODE_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaf02"

_DEFAULT_RETRY = {
    "max_attempts": 2,
    "initial_backoff_ms": 250,
    "max_backoff_ms": 5000,
    "multiplier": 2,
    "jitter": True,
}
DEFAULT_INPUT = {
    "topic": "markets",
    "score": 0.9,
    "items": ["alpha", "beta"],
}


def _prepare_workflow(*, chat_model: str) -> dict[str, Any]:
    return prepare_live_workflow(
        load_json(FULL_FIXTURE),
        http_node_id=HTTP_NODE_ID,
        chat_node_id=CHAT_NODE_ID,
        chat_model=chat_model,
        collect_node_id=COLLECT_NODE_ID,
        artifact_threshold_bytes=256,
    )


async def _resolve_approval_decision(*, interactive: bool) -> dict[str, Any]:
    if interactive:
        return await prompt_human_decision()
    return {"decision": "approved"}


async def _resolve_review_decision(
    collect_result: dict[str, Any],
    *,
    interactive: bool,
) -> dict[str, Any]:
    reviewed = {
        **collect_result,
        "reviewed": True,
        "note": "e2e auto-review",
    }
    if interactive:
        return await prompt_human_review_value(reviewed)
    return {"value": reviewed}


async def _wait_for(
    runtime: E2ERuntime,
    *,
    run_id: str,
    after_index: int,
    allowed: frozenset[str],
    step: str,
) -> dict[str, Any] | int:
    try:
        return await wait_for_terminal(
            runtime.collector,
            run_id=run_id,
            timeout_seconds=WAIT_TIMEOUT_SECONDS,
            allowed=allowed,
            after_index=after_index,
        )
    except TimeoutError:
        types = [
            event.get("message_type")
            for event in events_for_run(runtime.collector.events, run_id)
        ]
        return fail(step, f"timed out; events={types!r}")


async def _invariants(
    runtime: E2ERuntime,
    run_id: str,
    step: str,
    *,
    secret: bool = False,
) -> int:
    err = await assert_path_invariants(
        runtime.pool,
        runtime.collector.events,
        run_id,
        secret=runtime.chat_api_key if secret else None,
    )
    if err:
        return fail(step, err)
    return 0


def _execution_policy() -> dict[str, Any]:
    return {
        "timeout_seconds": 60,
        "max_node_executions": 20,
        "max_parallel_nodes": 4,
        "max_fan_out_items": 10,
        "max_task_seconds": 60,
        "max_provider_calls": 20,
        "max_artifact_bytes": 1_048_576,
        "default_retry": dict(_DEFAULT_RETRY),
    }


def _ssrf_workflow() -> dict[str, Any]:
    http_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaa901"
    return {
        "schema_version": "1.0",
        "workflow_id": "11111111-1111-4111-8111-111111111191",
        "workflow_version_id": "22222222-2222-4222-8222-222222222291",
        "name": "E2E SSRF blocked HTTP",
        "input_schema": {"type": "object", "additionalProperties": True},
        "output_schema": {"type": "object", "additionalProperties": True},
        "nodes": [
            {
                "id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaa900",
                "type": "data.input@1",
                "position": {"x": 0, "y": 80},
                "config": {},
                "credential_refs": {},
                "resource_refs": {},
            },
            {
                "id": http_id,
                "type": "action.http-request@1",
                "position": {"x": 240, "y": 80},
                "config": {
                    "method": "GET",
                    "url_template": "http://127.0.0.1/",
                    "timeout_seconds": 5,
                    "max_response_bytes": 4096,
                    "max_redirects": 0,
                },
                "credential_refs": {},
                "resource_refs": {},
            },
            {
                "id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaa902",
                "type": "data.output@1",
                "position": {"x": 480, "y": 80},
                "config": {},
                "credential_refs": {},
                "resource_refs": {},
            },
        ],
        "edges": [
            {
                "id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbb901",
                "source_node_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaa900",
                "source_port": "value",
                "target_node_id": http_id,
                "target_port": "url_variables",
            },
            {
                "id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbb902",
                "source_node_id": http_id,
                "source_port": "response",
                "target_node_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaa902",
                "target_port": "value",
            },
        ],
        "execution_policy": _execution_policy(),
    }


def _missing_prompt_workflow() -> dict[str, Any]:
    prompt_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaa911"
    return {
        "schema_version": "1.0",
        "workflow_id": "11111111-1111-4111-8111-111111111192",
        "workflow_version_id": "22222222-2222-4222-8222-222222222292",
        "name": "E2E missing prompt variable",
        "input_schema": {"type": "object", "additionalProperties": True},
        "output_schema": {"type": "object", "additionalProperties": True},
        "nodes": [
            {
                "id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaa910",
                "type": "data.input@1",
                "position": {"x": 0, "y": 80},
                "config": {},
                "credential_refs": {},
                "resource_refs": {},
            },
            {
                "id": prompt_id,
                "type": "ai.prompt-template@1",
                "position": {"x": 240, "y": 80},
                "config": {
                    "template": "Hello {{topic}}",
                    "required_variables": ["topic"],
                },
                "credential_refs": {},
                "resource_refs": {},
            },
            {
                "id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaa912",
                "type": "data.output@1",
                "position": {"x": 480, "y": 80},
                "config": {},
                "credential_refs": {},
                "resource_refs": {},
            },
        ],
        "edges": [
            {
                "id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbb911",
                "source_node_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaa910",
                "source_port": "value",
                "target_node_id": prompt_id,
                "target_port": "variables",
            },
            {
                "id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbb912",
                "source_node_id": prompt_id,
                "source_port": "text",
                "target_node_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaa912",
                "target_port": "value",
            },
        ],
        "execution_policy": _execution_policy(),
    }


def _cleanup_plan_workflow() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "workflow_id": "11111111-1111-4111-8111-111111111193",
        "workflow_version_id": "22222222-2222-4222-8222-222222222293",
        "name": "E2E Cleanup Plan Task",
        "input_schema": {"type": "object", "additionalProperties": True},
        "output_schema": {"type": "object", "additionalProperties": True},
        "nodes": [
            {
                "id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaf01",
                "type": "data.input@1",
                "position": {"x": 0, "y": 80},
                "config": {},
                "credential_refs": {},
                "resource_refs": {},
            },
            {
                "id": CLEANUP_NODE_ID,
                "type": "action.cleanup-plan@1",
                "position": {"x": 240, "y": 80},
                "config": {
                    "connector_type": "dataset",
                    "action": "archive",
                    "max_items": 10,
                    "max_bytes": 1024,
                },
                "credential_refs": {},
                "resource_refs": {},
            },
            {
                "id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaf03",
                "type": "data.output@1",
                "position": {"x": 480, "y": 80},
                "config": {},
                "credential_refs": {},
                "resource_refs": {},
            },
        ],
        "edges": [
            {
                "id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbf11",
                "source_node_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaf01",
                "source_port": "value",
                "target_node_id": CLEANUP_NODE_ID,
                "target_port": "scope",
            },
            {
                "id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbf12",
                "source_node_id": CLEANUP_NODE_ID,
                "source_port": "plan",
                "target_node_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaf03",
                "target_port": "value",
            },
        ],
        "execution_policy": _execution_policy(),
    }


async def _run_bindings_path(runtime: E2ERuntime) -> int:
    """F5: explicit field binding maps only order_id through to output."""
    workflow = load_json(BINDINGS_FIXTURE)
    envelope, run_id = build_start_envelope(
        workflow,
        run_input={"order_id": "ord-1", "priority": "high"},
    )
    print(f"\nStarting field-bindings run {run_id}")
    start_index = runtime.collector.event_count()
    await publish_command(runtime.channel, envelope, mq.EXECUTION_START_ROUTING_KEY)
    terminal = await _wait_for(
        runtime,
        run_id=run_id,
        after_index=start_index,
        allowed=frozenset({"execution.completed", "execution.failed"}),
        step="field-bindings path",
    )
    if isinstance(terminal, int):
        return terminal
    if terminal.get("message_type") != "execution.completed":
        err = (terminal.get("payload") or {}).get("error")
        return fail("field-bindings path", f"expected completed, got error={err!r}")
    outputs = (terminal.get("payload") or {}).get("outputs")
    if not isinstance(outputs, dict) or outputs.get("order_id") != "ord-1":
        return fail("field-bindings path", f"expected mapped order_id, got {outputs!r}")
    if "priority" in outputs:
        return fail("field-bindings path", f"priority should not be mapped, got {outputs!r}")
    done = await _invariants(runtime, run_id, "field-bindings path")
    if done:
        return done
    ok("field-bindings path", f"outputs={outputs!r}")
    return 0


async def _run_duplicate_start_path(runtime: E2ERuntime) -> int:
    """F6: the same execution.start message_id must not start a second run."""
    workflow = load_json(LINEAR_FIXTURE)
    envelope, run_id = build_start_envelope(workflow, run_input={"order_id": "dup-1"})
    print(f"\nStarting duplicate-start run {run_id}")
    start_index = runtime.collector.event_count()
    await publish_command(runtime.channel, envelope, mq.EXECUTION_START_ROUTING_KEY)
    await publish_command(runtime.channel, envelope, mq.EXECUTION_START_ROUTING_KEY)
    terminal = await _wait_for(
        runtime,
        run_id=run_id,
        after_index=start_index,
        allowed=frozenset({"execution.completed", "execution.failed"}),
        step="duplicate-start path",
    )
    if isinstance(terminal, int):
        return terminal
    if terminal.get("message_type") != "execution.completed":
        err = (terminal.get("payload") or {}).get("error")
        return fail("duplicate-start path", f"expected completed, got error={err!r}")
    started = [
        event
        for event in events_for_run(runtime.collector.events, run_id)
        if event.get("message_type") == "execution.started"
    ]
    if len(started) != 1:
        return fail("duplicate-start path", f"expected one execution.started, got {len(started)}")
    done = await _invariants(runtime, run_id, "duplicate-start path")
    if done:
        return done
    ok("duplicate-start path", "inbox ignored duplicate message_id")
    return 0


async def _run_fanout_merge_path(runtime: E2ERuntime) -> int:
    """F7: parallel prompt branches merge into one output object."""
    workflow = load_json(FANOUT_FIXTURE)
    envelope, run_id = build_start_envelope(workflow, run_input={"query": "markets"})
    print(f"\nStarting fan-out/merge run {run_id}")
    start_index = runtime.collector.event_count()
    await publish_command(runtime.channel, envelope, mq.EXECUTION_START_ROUTING_KEY)
    terminal = await _wait_for(
        runtime,
        run_id=run_id,
        after_index=start_index,
        allowed=frozenset({"execution.completed", "execution.failed"}),
        step="fan-out/merge path",
    )
    if isinstance(terminal, int):
        return terminal
    if terminal.get("message_type") != "execution.completed":
        err = (terminal.get("payload") or {}).get("error")
        return fail("fan-out/merge path", f"expected completed, got error={err!r}")
    if FANOUT_MERGE_NODE_ID not in node_completed_ids(
        events_for_run(runtime.collector.events, run_id)
    ):
        return fail("fan-out/merge path", "merge node did not complete")
    outputs = (terminal.get("payload") or {}).get("outputs")
    if not isinstance(outputs, dict) or "summary" not in outputs or "keywords" not in outputs:
        return fail("fan-out/merge path", f"expected merged summary+keywords, got {outputs!r}")
    done = await _invariants(runtime, run_id, "fan-out/merge path")
    if done:
        return done
    ok("fan-out/merge path", f"outputs={outputs!r}")
    return 0


async def _run_missing_prompt_path(runtime: E2ERuntime) -> int:
    """F8 edge: required template variable missing → execution.failed."""
    workflow = _missing_prompt_workflow()
    envelope, run_id = build_start_envelope(workflow, run_input={})
    print(f"\nStarting missing-prompt-variable run {run_id}")
    start_index = runtime.collector.event_count()
    await publish_command(runtime.channel, envelope, mq.EXECUTION_START_ROUTING_KEY)
    terminal = await _wait_for(
        runtime,
        run_id=run_id,
        after_index=start_index,
        allowed=frozenset({"execution.completed", "execution.failed"}),
        step="missing-prompt path",
    )
    if isinstance(terminal, int):
        return terminal
    if terminal.get("message_type") != "execution.failed":
        return fail(
            "missing-prompt path",
            f"expected execution.failed, got {terminal.get('message_type')}",
        )
    done = await _invariants(runtime, run_id, "missing-prompt path")
    if done:
        return done
    ok("missing-prompt path", "required variable failure")
    return 0


async def _run_foreach_collect_path(runtime: E2ERuntime) -> int:
    """F14 happy path without HTTP: for-each → prompt → collect counts."""
    workflow = load_json(FOREACH_COLLECT_FIXTURE)
    items = ["alpha", "beta"]
    envelope, run_id = build_start_envelope(workflow, run_input={"items": items})
    print(f"\nStarting for-each/collect run {run_id}")
    start_index = runtime.collector.event_count()
    await publish_command(runtime.channel, envelope, mq.EXECUTION_START_ROUTING_KEY)
    terminal = await _wait_for(
        runtime,
        run_id=run_id,
        after_index=start_index,
        allowed=frozenset({"execution.completed", "execution.failed"}),
        step="for-each/collect path",
    )
    if isinstance(terminal, int):
        return terminal
    if terminal.get("message_type") != "execution.completed":
        err = (terminal.get("payload") or {}).get("error")
        return fail("for-each/collect path", f"expected completed, got error={err!r}")
    collect = collect_result_from_events(
        events_for_run(runtime.collector.events, run_id),
        collect_node_id=FOREACH_COLLECT_NODE_ID,
    )
    if collect is None:
        return fail("for-each/collect path", "collect node did not emit result")
    summary = collect.get("summary")
    if not isinstance(summary, dict) or summary.get("total") != 2 or summary.get("completed") != 2:
        return fail("for-each/collect path", f"unexpected collect summary {summary!r}")
    done = await _invariants(runtime, run_id, "for-each/collect path")
    if done:
        return done
    ok("for-each/collect path", f"summary={summary!r}")
    return 0


async def _run_foreach_over_cap_path(runtime: E2ERuntime) -> int:
    """F14 edge: more items than max_fan_out_items → execution.failed."""
    workflow = load_json(FOREACH_CAP_FIXTURE)
    envelope, run_id = build_start_envelope(
        workflow,
        run_input={"items": ["a", "b", "c"]},
    )
    print(f"\nStarting for-each-over-cap run {run_id}")
    start_index = runtime.collector.event_count()
    await publish_command(runtime.channel, envelope, mq.EXECUTION_START_ROUTING_KEY)
    terminal = await _wait_for(
        runtime,
        run_id=run_id,
        after_index=start_index,
        allowed=frozenset({"execution.completed", "execution.failed"}),
        step="for-each-over-cap path",
    )
    if isinstance(terminal, int):
        return terminal
    if terminal.get("message_type") != "execution.failed":
        return fail(
            "for-each-over-cap path",
            f"expected execution.failed, got {terminal.get('message_type')}",
        )
    done = await _invariants(runtime, run_id, "for-each-over-cap path")
    if done:
        return done
    ok("for-each-over-cap path", "item cap rejected")
    return 0


async def _run_ssrf_path(runtime: E2ERuntime) -> int:
    """F12 edge: HTTP to loopback is blocked."""
    workflow = _ssrf_workflow()
    envelope, run_id = build_start_envelope(workflow, run_input={})
    print(f"\nStarting SSRF-blocked HTTP run {run_id}")
    start_index = runtime.collector.event_count()
    await publish_command(runtime.channel, envelope, mq.EXECUTION_START_ROUTING_KEY)
    terminal = await _wait_for(
        runtime,
        run_id=run_id,
        after_index=start_index,
        allowed=frozenset({"execution.completed", "execution.failed"}),
        step="ssrf path",
    )
    if isinstance(terminal, int):
        return terminal
    if terminal.get("message_type") != "execution.failed":
        return fail(
            "ssrf path",
            f"expected execution.failed for loopback URL, got {terminal.get('message_type')}",
        )
    done = await _invariants(runtime, run_id, "ssrf path")
    if done:
        return done
    ok("ssrf path", "loopback HTTP blocked")
    return 0


async def _wait_human_approval(
    runtime: E2ERuntime,
    *,
    step: str,
) -> tuple[dict[str, Any], str, dict[str, Any]] | int:
    workflow = load_json(APPROVAL_FIXTURE)
    envelope, run_id = build_start_envelope(workflow, run_input={"n": 1})
    print(f"\nStarting {step} run {run_id}")
    start_index = runtime.collector.event_count()
    await publish_command(runtime.channel, envelope, mq.EXECUTION_START_ROUTING_KEY)
    waiting = await _wait_for(
        runtime,
        run_id=run_id,
        after_index=start_index,
        allowed=frozenset({"execution.waiting", "execution.failed", "execution.completed"}),
        step=step,
    )
    if isinstance(waiting, int):
        return waiting
    if waiting.get("message_type") != "execution.waiting":
        return fail(step, f"expected execution.waiting, got {waiting.get('message_type')}")
    interrupt = await query_interrupt_from_checkpoint(runtime.pool, run_id)
    if interrupt is None or str(interrupt.get("node_id")) != LINEAR_APPROVAL_NODE_ID:
        return fail(step, f"expected approval interrupt, got {interrupt!r}")
    return waiting, run_id, interrupt


async def _run_approval_reject_path(runtime: E2ERuntime) -> int:
    """F11: reject is a valid terminal decision, not a failed run."""
    started = await _wait_human_approval(runtime, step="approval-reject path")
    if isinstance(started, int):
        return started
    waiting, run_id, interrupt = started
    workflow = load_json(APPROVAL_FIXTURE)
    after = runtime.collector.event_count()
    await publish_command(
        runtime.channel,
        mint_resume_envelope(
            waiting_event=waiting,
            run_id=run_id,
            workflow_id=workflow["workflow_id"],
            workflow_version_id=workflow["workflow_version_id"],
            interrupt_id=str((waiting.get("payload") or {})["interrupt_id"]),
            approval_id=str(interrupt["approval_id"]),
            decision={"decision": "rejected"},
        ),
        mq.EXECUTION_RESUME_ROUTING_KEY,
    )
    terminal = await _wait_for(
        runtime,
        run_id=run_id,
        after_index=after,
        allowed=frozenset({"execution.completed", "execution.failed"}),
        step="approval-reject path",
    )
    if isinstance(terminal, int):
        return terminal
    if terminal.get("message_type") != "execution.completed":
        err = (terminal.get("payload") or {}).get("error")
        return fail("approval-reject path", f"expected completed, got error={err!r}")
    outputs = (terminal.get("payload") or {}).get("outputs")
    if not isinstance(outputs, dict) or outputs.get("decision") != "rejected":
        return fail("approval-reject path", f"expected rejected decision, got {outputs!r}")
    done = await _invariants(runtime, run_id, "approval-reject path")
    if done:
        return done
    ok("approval-reject path", "decision=rejected")
    return 0


async def _run_bad_then_good_resume_path(runtime: E2ERuntime) -> int:
    """F9/F11 edge: invalid resume fails; matching resume then completes."""
    started = await _wait_human_approval(runtime, step="bad-resume path")
    if isinstance(started, int):
        return started
    waiting, run_id, interrupt = started
    workflow = load_json(APPROVAL_FIXTURE)
    payload = waiting.get("payload") or {}
    after_bad = runtime.collector.event_count()
    await publish_command(
        runtime.channel,
        mint_resume_envelope(
            waiting_event=waiting,
            run_id=run_id,
            workflow_id=workflow["workflow_id"],
            workflow_version_id=workflow["workflow_version_id"],
            interrupt_id=str(payload["interrupt_id"]),
            approval_id=str(interrupt["approval_id"]),
            decision={"decision": "maybe"},
        ),
        mq.EXECUTION_RESUME_ROUTING_KEY,
    )
    failed = await _wait_for(
        runtime,
        run_id=run_id,
        after_index=after_bad,
        allowed=frozenset({"execution.failed", "execution.completed"}),
        step="bad-resume path",
    )
    if isinstance(failed, int):
        return failed
    if failed.get("message_type") != "execution.failed":
        return fail(
            "bad-resume path",
            f"expected execution.failed for invalid decision, got {failed.get('message_type')}",
        )
    still = await query_interrupt_from_checkpoint(runtime.pool, run_id)
    if still is None:
        return fail("bad-resume path", "invalid resume cleared the interrupt")
    after_good = runtime.collector.event_count()
    await publish_command(
        runtime.channel,
        mint_resume_envelope(
            waiting_event=waiting,
            run_id=run_id,
            workflow_id=workflow["workflow_id"],
            workflow_version_id=workflow["workflow_version_id"],
            interrupt_id=str(payload["interrupt_id"]),
            approval_id=str(interrupt["approval_id"]),
            decision={"decision": "approved"},
        ),
        mq.EXECUTION_RESUME_ROUTING_KEY,
    )
    terminal = await _wait_for(
        runtime,
        run_id=run_id,
        after_index=after_good,
        allowed=frozenset({"execution.completed", "execution.failed"}),
        step="bad-resume path",
    )
    if isinstance(terminal, int):
        return terminal
    if terminal.get("message_type") != "execution.completed":
        err = (terminal.get("payload") or {}).get("error")
        return fail("bad-resume path", f"valid resume did not complete: {err!r}")
    done = await _invariants(runtime, run_id, "bad-resume path")
    if done:
        return done
    ok("bad-resume path", "invalid decision rejected, then approved")
    return 0


async def _run_cleanup_plan_path(runtime: E2ERuntime) -> int:
    """F16 stub: cleanup-plan durable task resumes the parent with a plan."""
    workflow = _cleanup_plan_workflow()
    envelope, run_id = build_start_envelope(workflow, run_input={"scope": "datasets"})
    print(f"\nStarting cleanup-plan run {run_id}")
    start_index = runtime.collector.event_count()
    await publish_command(runtime.channel, envelope, mq.EXECUTION_START_ROUTING_KEY)
    first = await _wait_for(
        runtime,
        run_id=run_id,
        after_index=start_index,
        allowed=frozenset({"execution.waiting", "execution.failed", "execution.completed"}),
        step="cleanup-plan path",
    )
    if isinstance(first, int):
        return first
    if first.get("message_type") == "execution.failed":
        err = (first.get("payload") or {}).get("error")
        return fail("cleanup-plan path", f"execution.failed: {err!r}")
    terminal = first
    if terminal.get("message_type") != "execution.completed":
        terminal = await _wait_for(
            runtime,
            run_id=run_id,
            after_index=start_index,
            allowed=frozenset({"execution.completed", "execution.failed"}),
            step="cleanup-plan path",
        )
        if isinstance(terminal, int):
            return terminal
    if terminal.get("message_type") != "execution.completed":
        err = (terminal.get("payload") or {}).get("error")
        return fail("cleanup-plan path", f"expected completed, got error={err!r}")
    outputs = (terminal.get("payload") or {}).get("outputs")
    if not isinstance(outputs, dict) or not outputs.get("plan_hash"):
        return fail("cleanup-plan path", f"expected plan_hash, got {outputs!r}")
    done = await _invariants(runtime, run_id, "cleanup-plan path")
    if done:
        return done
    ok("cleanup-plan path", f"plan_hash={outputs.get('plan_hash')!r}")
    return 0


async def _run_high_score_path(
    runtime: E2ERuntime,
    *,
    score: float,
    topic: str,
    items: list[str],
    interactive: bool,
) -> int:
    workflow = _prepare_workflow(chat_model=runtime.settings.chat_model)
    run_input = {"topic": topic, "score": score, "items": items}
    envelope, run_id = build_start_envelope(workflow, run_input=run_input)
    workflow_id = workflow["workflow_id"]
    workflow_version_id = workflow["workflow_version_id"]

    print(f"\nStarting high-score run {run_id} (topic={topic!r}, score={score})")
    start_index = runtime.collector.event_count()
    await publish_command(runtime.channel, envelope, mq.EXECUTION_START_ROUTING_KEY)

    waiting = await wait_for_terminal(
        runtime.collector,
        run_id=run_id,
        timeout_seconds=WAIT_TIMEOUT_SECONDS,
        allowed=frozenset({"execution.waiting", "execution.failed", "execution.completed"}),
        after_index=start_index,
    )
    if waiting.get("message_type") == "execution.failed":
        err = (waiting.get("payload") or {}).get("error")
        return fail("high-score path", f"execution.failed before approval: {err!r}")
    if waiting.get("message_type") != "execution.waiting":
        got = waiting.get("message_type")
        return fail("high-score path", f"expected execution.waiting (approval), got {got}")

    payload = waiting.get("payload") or {}
    if payload.get("waiting_reason") != "HUMAN":
        return fail(
            "high-score path",
            f"unexpected waiting_reason: {payload.get('waiting_reason')!r}",
        )

    run_events = events_for_run(runtime.collector.events, run_id)
    chat_response = chat_response_from_events(run_events, chat_node_id=CHAT_NODE_ID)
    if chat_response is None:
        return fail("high-score path", "chat node did not produce response text before approval")

    print_llm_response(chat_response, topic=topic)
    chat_text = str(chat_response["text"])

    interrupt = await query_interrupt_from_checkpoint(runtime.pool, run_id)
    if interrupt is None:
        return fail("high-score path", "no interrupt in ee.workflow_checkpoints (approval)")
    if str(interrupt.get("node_id")) != APPROVAL_NODE_ID:
        return fail(
            "high-score path",
            f"expected approval node interrupt, got node_id={interrupt.get('node_id')!r}",
        )

    approval_decision = await _resolve_approval_decision(interactive=interactive)

    resume_approval = mint_resume_envelope(
        waiting_event=waiting,
        run_id=run_id,
        workflow_id=workflow_id,
        workflow_version_id=workflow_version_id,
        interrupt_id=str(payload["interrupt_id"]),
        approval_id=str(interrupt["approval_id"]),
        decision=approval_decision,
    )
    print(f"Resuming approval with decision={approval_decision.get('decision')!r} …")
    after_approval = runtime.collector.event_count()
    await publish_command(runtime.channel, resume_approval, mq.EXECUTION_RESUME_ROUTING_KEY)

    review_waiting = await wait_for_terminal(
        runtime.collector,
        run_id=run_id,
        timeout_seconds=WAIT_TIMEOUT_SECONDS,
        allowed=frozenset({"execution.waiting", "execution.failed", "execution.completed"}),
        after_index=after_approval,
    )
    if review_waiting.get("message_type") == "execution.failed":
        err = (review_waiting.get("payload") or {}).get("error")
        return fail("high-score path", f"execution.failed before review: {err!r}")
    if review_waiting.get("message_type") != "execution.waiting":
        got = review_waiting.get("message_type")
        return fail("high-score path", f"expected execution.waiting (review), got {got}")

    review_payload = review_waiting.get("payload") or {}
    if review_payload.get("waiting_reason") != "HUMAN":
        return fail(
            "high-score path",
            f"unexpected review waiting_reason: {review_payload.get('waiting_reason')!r}",
        )

    run_events = events_for_run(runtime.collector.events, run_id)
    collect_result = collect_result_from_events(run_events, collect_node_id=COLLECT_NODE_ID)
    if collect_result is None:
        return fail("high-score path", "collect node did not produce result before review")

    summary = collect_result.get("summary")
    if not isinstance(summary, dict):
        return fail("high-score path", f"expected collect summary, got {collect_result!r}")
    expected = len(items)
    accounted = int(summary.get("completed") or 0) + int(summary.get("failed") or 0) + int(
        summary.get("skipped") or 0
    )
    if summary.get("total") != expected or accounted != expected:
        return fail("high-score path", f"unexpected collect summary: {summary!r}")

    review_interrupt = await query_interrupt_from_checkpoint(runtime.pool, run_id)
    if review_interrupt is None:
        return fail("high-score path", "no interrupt in ee.workflow_checkpoints (review)")
    if str(review_interrupt.get("node_id")) != REVIEW_NODE_ID:
        return fail(
            "high-score path",
            f"expected review node interrupt, got node_id={review_interrupt.get('node_id')!r}",
        )

    review_decision = await _resolve_review_decision(collect_result, interactive=interactive)
    resume_review = mint_resume_envelope(
        waiting_event=review_waiting,
        run_id=run_id,
        workflow_id=workflow_id,
        workflow_version_id=workflow_version_id,
        interrupt_id=str(review_payload["interrupt_id"]),
        approval_id=str(review_interrupt["approval_id"]),
        decision=review_decision,
    )
    print("Resuming review …")
    after_review = runtime.collector.event_count()
    await publish_command(runtime.channel, resume_review, mq.EXECUTION_RESUME_ROUTING_KEY)

    terminal = await wait_for_terminal(
        runtime.collector,
        run_id=run_id,
        timeout_seconds=WAIT_TIMEOUT_SECONDS,
        allowed=frozenset({"execution.completed", "execution.failed"}),
        after_index=after_review,
    )
    if terminal.get("message_type") != "execution.completed":
        err = (terminal.get("payload") or {}).get("error")
        return fail(
            "high-score path",
            f"review resume did not complete: {terminal.get('message_type')} error={err!r}",
        )

    outputs = (terminal.get("payload") or {}).get("outputs")
    if not isinstance(outputs, dict):
        return fail("high-score path", f"expected object outputs, got {outputs!r}")
    if outputs.get("reviewed") is not True:
        return fail("high-score path", f"expected reviewed output flag, got {outputs!r}")

    artifact_ref = collect_result.get("artifact_ref")
    if not isinstance(artifact_ref, str) or not artifact_ref:
        return fail(
            "high-score path",
            f"expected collect artifact_ref after overflow, got {collect_result!r}",
        )
    if (
        collect_result.get("successes") != []
        or collect_result.get("failures") != []
        or collect_result.get("skipped") != []
    ):
        return fail(
            "high-score path",
            f"overflow collect should empty bulk arrays, got {collect_result!r}",
        )

    leak = await _invariants(runtime, run_id, "high-score path", secret=True)
    if leak:
        return leak

    completed_ids = node_completed_ids(events_for_run(runtime.collector.events, run_id))
    if PROMPT_NODE_ID not in completed_ids:
        return fail("high-score path", "prompt-template node did not complete")
    if MERGE_NODE_ID not in completed_ids:
        return fail("high-score path", "merge node did not complete")

    ok("high-score path", f"summary={summary!r} artifact_ref={artifact_ref} reviewed=True")
    print("\n=== FINAL LLM RESPONSE ===")
    print(chat_text)
    print("==========================\n")
    print(f"Final outputs: {json.dumps(outputs, indent=2, ensure_ascii=False)}")
    return 0


async def _run_low_score_path(
    runtime: E2ERuntime,
    *,
    topic: str,
    items: list[str],
) -> int:
    workflow = _prepare_workflow(chat_model=runtime.settings.chat_model)
    run_input = {"topic": topic, "score": 0.1, "items": items}
    envelope, run_id = build_start_envelope(workflow, run_input=run_input)

    print(f"\nStarting low-score run {run_id} (condition → bounded loop)")
    start_index = runtime.collector.event_count()
    await publish_command(runtime.channel, envelope, mq.EXECUTION_START_ROUTING_KEY)
    terminal = await wait_for_terminal(
        runtime.collector,
        run_id=run_id,
        timeout_seconds=WAIT_TIMEOUT_SECONDS,
        allowed=frozenset({"execution.completed", "execution.failed", "execution.waiting"}),
        after_index=start_index,
    )
    if terminal.get("message_type") == "execution.waiting":
        return fail("low-score path", "should not pause for human approval/review")
    if terminal.get("message_type") != "execution.completed":
        got = terminal.get("message_type")
        err = (terminal.get("payload") or {}).get("error")
        return fail("low-score path", f"expected execution.completed, got {got} error={err!r}")

    run_events = events_for_run(runtime.collector.events, run_id)
    completed_ids = node_completed_ids(run_events)
    if LOW_OUTPUT_NODE_ID not in completed_ids:
        return fail("low-score path", "low-branch output node did not complete")
    if LOOP_NODE_ID not in completed_ids:
        return fail("low-score path", "loop node did not complete on low-score branch")
    if CHAT_NODE_ID in completed_ids:
        return fail("low-score path", "chat node should not run on low-score branch")
    if FOR_EACH_NODE_ID in completed_ids:
        return fail("low-score path", "for-each should not run on low-score branch")

    outputs = (terminal.get("payload") or {}).get("outputs")
    if not isinstance(outputs, dict) or outputs.get("limit_reached") is not True:
        return fail("low-score path", f"expected loop done with limit_reached, got {outputs!r}")

    scale = await _invariants(runtime, run_id, "low-score path")
    if scale:
        return scale

    ok("low-score path", f"output={outputs!r}")
    return 0


async def _run_cancel_path(
    runtime: E2ERuntime,
    *,
    topic: str,
    items: list[str],
) -> int:
    """Hit approval wait, then execution.cancel → immediate execution.cancelled."""
    workflow = _prepare_workflow(chat_model=runtime.settings.chat_model)
    run_input = {"topic": topic, "score": 0.9, "items": items}
    envelope, run_id = build_start_envelope(workflow, run_input=run_input)
    workflow_id = workflow["workflow_id"]
    workflow_version_id = workflow["workflow_version_id"]

    print(f"\nStarting cancel-scenario run {run_id}")
    start_index = runtime.collector.event_count()
    await publish_command(runtime.channel, envelope, mq.EXECUTION_START_ROUTING_KEY)

    waiting = await wait_for_terminal(
        runtime.collector,
        run_id=run_id,
        timeout_seconds=WAIT_TIMEOUT_SECONDS,
        allowed=frozenset({"execution.waiting", "execution.failed", "execution.completed"}),
        after_index=start_index,
    )
    if waiting.get("message_type") != "execution.waiting":
        got = waiting.get("message_type")
        err = (waiting.get("payload") or {}).get("error")
        return fail("cancel path", f"expected execution.waiting, got {got} error={err!r}")

    interrupt = await query_interrupt_from_checkpoint(runtime.pool, run_id)
    if interrupt is None:
        return fail("cancel path", "no interrupt in checkpoint")

    cancel_envelope = mint_cancel_envelope(
        run_id=run_id,
        workflow_id=workflow_id,
        workflow_version_id=workflow_version_id,
        waiting_event=waiting,
    )
    after_waiting = runtime.collector.event_count()
    print("Publishing execution.cancel while waiting at approval …")
    await publish_command(runtime.channel, cancel_envelope, mq.EXECUTION_CANCEL_ROUTING_KEY)

    terminal = await wait_for_terminal(
        runtime.collector,
        run_id=run_id,
        timeout_seconds=WAIT_TIMEOUT_SECONDS,
        allowed=frozenset({"execution.cancelled", "execution.completed", "execution.failed"}),
        after_index=after_waiting,
    )
    if terminal.get("message_type") != "execution.cancelled":
        got = terminal.get("message_type")
        err = (terminal.get("payload") or {}).get("error")
        return fail("cancel path", f"expected execution.cancelled, got {got} error={err!r}")

    after_cancel = runtime.collector.event_count()
    late_resume = mint_resume_envelope(
        waiting_event=waiting,
        run_id=run_id,
        workflow_id=workflow_id,
        workflow_version_id=workflow_version_id,
        interrupt_id=str((waiting.get("payload") or {}).get("interrupt_id")),
        approval_id=str(interrupt.get("approval_id")) if interrupt.get("approval_id") else None,
        decision={"decision": "approved"},
    )
    await publish_command(runtime.channel, late_resume, mq.EXECUTION_RESUME_ROUTING_KEY)
    late = await _wait_for(
        runtime,
        run_id=run_id,
        after_index=after_cancel,
        allowed=frozenset({"execution.failed", "execution.completed", "execution.cancelled"}),
        step="cancel path",
    )
    if isinstance(late, int):
        return late
    if late.get("message_type") == "execution.completed":
        return fail("cancel path", "late resume after cancel continued the graph")

    scale = await _invariants(runtime, run_id, "cancel path")
    if scale:
        return scale

    ok("cancel path", f"reason={(terminal.get('payload') or {}).get('reason')!r}")
    return 0


async def _run_durable_task_path(runtime: E2ERuntime) -> int:
    """Start research.deep-research@1 and let task.completed resume the parent."""
    workflow = load_json(DURABLE_FIXTURE)
    question = "What is a durable workflow task?"
    run_input = {"question": question, "seed_sources": ["https://example.com"]}
    envelope, run_id = build_start_envelope(workflow, run_input=run_input)

    print(f"\nStarting durable-task run {run_id}")
    start_index = runtime.collector.event_count()
    await publish_command(runtime.channel, envelope, mq.EXECUTION_START_ROUTING_KEY)

    first = await wait_for_terminal(
        runtime.collector,
        run_id=run_id,
        timeout_seconds=WAIT_TIMEOUT_SECONDS,
        allowed=frozenset({"execution.waiting", "execution.failed", "execution.completed"}),
        after_index=start_index,
    )
    if first.get("message_type") == "execution.failed":
        err = (first.get("payload") or {}).get("error")
        return fail("durable-task path", f"execution.failed: {err!r}")

    run_events = events_for_run(runtime.collector.events, run_id)
    waiting_events = [
        event
        for event in run_events
        if event.get("message_type") == "execution.waiting"
        and (event.get("payload") or {}).get("waiting_reason") == "TASK"
    ]
    if not waiting_events:
        return fail("durable-task path", "never entered execution.waiting with reason TASK")

    waiting_payload = waiting_events[0].get("payload") or {}
    if str(waiting_payload.get("node_id") or "") not in {"", RESEARCH_NODE_ID}:
        return fail(
            "durable-task path",
            f"waiting event node_id={waiting_payload.get('node_id')!r}",
        )

    interrupt = await query_interrupt_from_checkpoint(runtime.pool, run_id)
    if interrupt is not None:
        if str(interrupt.get("node_id")) != RESEARCH_NODE_ID:
            return fail(
                "durable-task path",
                f"expected research node interrupt, got node_id={interrupt.get('node_id')!r}",
            )
        if interrupt.get("waiting_reason") != "TASK":
            return fail(
                "durable-task path",
                f"unexpected waiting_reason: {interrupt.get('waiting_reason')!r}",
            )

    terminal = first
    if terminal.get("message_type") != "execution.completed":
        try:
            terminal = await wait_for_terminal(
                runtime.collector,
                run_id=run_id,
                timeout_seconds=WAIT_TIMEOUT_SECONDS,
                allowed=frozenset({"execution.completed", "execution.failed"}),
                after_index=start_index,
            )
        except TimeoutError:
            types = [event.get("message_type") for event in events_for_run(
                runtime.collector.events, run_id
            )]
            return fail(
                "durable-task path",
                f"timed out waiting for execution.completed; events={types!r}",
            )
    if terminal.get("message_type") != "execution.completed":
        err = (terminal.get("payload") or {}).get("error")
        return fail(
            "durable-task path",
            f"expected execution.completed after task.completed, got "
            f"{terminal.get('message_type')} error={err!r}",
        )

    outputs = (terminal.get("payload") or {}).get("outputs")
    if not isinstance(outputs, dict):
        return fail("durable-task path", f"expected object outputs, got {outputs!r}")
    if not isinstance(outputs.get("executive_summary"), str):
        return fail("durable-task path", f"missing executive_summary in {outputs!r}")
    if not isinstance(outputs.get("sources"), list):
        return fail("durable-task path", f"missing sources in {outputs!r}")
    if outputs.get("completion_reason") != "completed":
        return fail("durable-task path", f"unexpected completion_reason in {outputs!r}")

    stored = await runtime.pool.fetchrow(
        "SELECT 1 FROM ee.task_checkpoints WHERE run_id = $1::uuid",
        UUID(run_id),
    )
    if stored is None:
        return fail("durable-task path", "no row in ee.task_checkpoints")

    scale = await _invariants(runtime, run_id, "durable-task path")
    if scale:
        return scale

    ok("durable-task path", f"report={outputs.get('executive_summary')!r}")
    return 0


async def main_async(
    *,
    score: float,
    topic: str,
    items: list[str],
    interactive: bool,
    skip_low: bool,
    skip_cancel: bool,
    skip_task: bool,
    skip_edges: bool,
) -> int:
    logging.basicConfig(level=logging.INFO)
    runtime = await setup_runtime(log_label="full-features")
    try:
        if not skip_edges:
            for run_step in (
                _run_bindings_path,
                _run_duplicate_start_path,
                _run_fanout_merge_path,
                _run_missing_prompt_path,
                _run_foreach_collect_path,
                _run_foreach_over_cap_path,
                _run_ssrf_path,
                _run_approval_reject_path,
                _run_bad_then_good_resume_path,
            ):
                result = await run_step(runtime)
                if result != 0:
                    return result

        if not skip_low:
            low = await _run_low_score_path(runtime, topic=topic, items=items)
            if low != 0:
                return low

        if not skip_cancel:
            cancelled = await _run_cancel_path(runtime, topic=topic, items=items)
            if cancelled != 0:
                return cancelled

        if not skip_task:
            durable = await _run_durable_task_path(runtime)
            if durable != 0:
                return durable
            cleanup = await _run_cleanup_plan_path(runtime)
            if cleanup != 0:
                return cleanup

        if score < 0.5:
            return await _run_low_score_path(runtime, topic=topic, items=items)

        return await _run_high_score_path(
            runtime,
            score=score,
            topic=topic,
            items=items,
            interactive=interactive,
        )
    finally:
        await teardown_runtime(runtime)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Full-features e2e (no RAG): bindings, merge, loop, AI, credentials, "
            "approval/review, HTTP/SSRF, for-each/collect, cancel, durable tasks, "
            "and edge cases (duplicate start, bad resume, over-cap, reject)"
        ),
    )
    parser.add_argument(
        "--score",
        type=float,
        default=DEFAULT_INPUT["score"],
        help="Input score (>=0.5 takes AI/human/for-each path; default: 0.9)",
    )
    parser.add_argument(
        "--topic",
        type=str,
        default=DEFAULT_INPUT["topic"],
        help="Topic string for the AI prompt template",
    )
    parser.add_argument(
        "--items",
        type=str,
        nargs="+",
        default=list(DEFAULT_INPUT["items"]),
        help="Items for the for-each loop (default: alpha beta)",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Prompt in the terminal for approval and review (default: auto)",
    )
    parser.add_argument(
        "--skip-low",
        action="store_true",
        help="Skip the low-score loop branch scenario",
    )
    parser.add_argument(
        "--skip-cancel",
        action="store_true",
        help="Skip the cancel-while-waiting scenario",
    )
    parser.add_argument(
        "--skip-task",
        action="store_true",
        help="Skip F15/F16 durable-task scenarios (research + cleanup-plan)",
    )
    parser.add_argument(
        "--skip-edges",
        action="store_true",
        help="Skip extra feature/edge-case paths (bindings, merge, SSRF, bad resume, …)",
    )
    args = parser.parse_args()
    return asyncio.run(
        main_async(
            score=args.score,
            topic=args.topic,
            items=list(args.items),
            interactive=args.interactive,
            skip_low=args.skip_low,
            skip_cancel=args.skip_cancel,
            skip_task=args.skip_task,
            skip_edges=args.skip_edges,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
