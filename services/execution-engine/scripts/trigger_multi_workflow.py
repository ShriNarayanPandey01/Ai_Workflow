#!/usr/bin/env python3
"""Control-plane mimic: run checkpoint-retry, human-review loop, and full-features.

Prerequisites (from repo root):
    docker compose up -d postgres rabbitmq
    docker compose stop execution-worker task-worker

Requires OPENAI_API_KEY in services/execution-engine/.env (AIW_FAKE_LLM must
not be true).

Usage:
    cd services/execution-engine
    uv run python scripts/trigger_multi_workflow.py
    uv run python scripts/trigger_multi_workflow.py --auto-loop --skip-full
    uv run python scripts/trigger_multi_workflow.py --interactive
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from typing import Any

from e2e_helpers import (
    WAIT_TIMEOUT_SECONDS,
    E2ERuntime,
    assert_path_invariants,
    build_start_envelope,
    events_for_run,
    fail,
    install_crash_once_node,
    latest_chat_response_from_events,
    load_json,
    mint_resume_envelope,
    node_completed_count,
    node_completed_ids,
    ok,
    prepare_live_workflow,
    print_llm_response,
    prompt_review_correctness,
    publish_command,
    query_checkpoint_envelope,
    query_interrupt_from_checkpoint,
    setup_runtime,
    teardown_runtime,
    wait_for_terminal,
)
from trigger_full_features_workflow import (
    DEFAULT_INPUT as FULL_DEFAULT_INPUT,
)
from trigger_full_features_workflow import (
    _run_cleanup_plan_path,
    _run_durable_task_path,
    _run_high_score_path,
)

from ai_workflow.config.settings import REPO_ROOT
from ai_workflow.messaging.broker import MessagingNames as mq

FIXTURES_DIR = REPO_ROOT / "contracts" / "fixtures" / "valid"
CHECKPOINT_FIXTURE = FIXTURES_DIR / "workflow-e2e-checkpoint-retry.json"
REVIEW_LOOP_FIXTURE = FIXTURES_DIR / "workflow-e2e-human-review-loop.json"

CHECKPOINT_INPUT_NODE_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaac51"
CHECKPOINT_HTTP_NODE_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaac52"
CHECKPOINT_OUTPUT_NODE_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaac53"

REVIEW_CHAT_NODE_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaac64"
REVIEW_NODE_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaac65"

DEFAULT_REVIEW_PROMPT = "Explain workflow checkpoint resume in one short sentence."


def _prepare_checkpoint_workflow() -> dict[str, Any]:
    return prepare_live_workflow(
        load_json(CHECKPOINT_FIXTURE),
        http_node_id=CHECKPOINT_HTTP_NODE_ID,
        chat_node_id="",
    )


def _prepare_review_loop_workflow() -> dict[str, Any]:
    return prepare_live_workflow(
        load_json(REVIEW_LOOP_FIXTURE),
        http_node_id="",
        chat_node_id=REVIEW_CHAT_NODE_ID,
    )


def _scheduler_pending(envelope: dict[str, Any]) -> list[str]:
    scheduler = envelope.get("scheduler")
    if not isinstance(scheduler, dict):
        runtime = envelope.get("runtime")
        if isinstance(runtime, dict):
            scheduler = runtime.get("_scheduler")
    if not isinstance(scheduler, dict):
        return []
    pending = scheduler.get("pending")
    if not isinstance(pending, list):
        return []
    return [str(item) for item in pending]


async def _invariants(runtime: E2ERuntime, run_id: str, step: str) -> int:
    error = await assert_path_invariants(
        runtime.pool,
        runtime.collector.events,
        run_id,
        secret=runtime.provider_api_key,
    )
    if error:
        return fail(step, error)
    return 0


async def _run_checkpoint_retry_path(runtime: E2ERuntime) -> int:
    workflow = _prepare_checkpoint_workflow()
    install_crash_once_node(
        runtime.handler._registry,  # noqa: SLF001 - e2e crash-injection seam
        node_type="action.http-request@1",
        crash_node_id=CHECKPOINT_HTTP_NODE_ID,
    )
    run_input = {"item": "checkpoint-retry"}
    envelope, run_id = build_start_envelope(workflow, run_input=run_input)

    print(f"\nStarting checkpoint-retry run {run_id} (first pass should fail)")
    start_index = runtime.collector.event_count()
    await publish_command(runtime.channel, envelope, mq.EXECUTION_START_ROUTING_KEY)
    failed = await wait_for_terminal(
        runtime.collector,
        run_id=run_id,
        timeout_seconds=WAIT_TIMEOUT_SECONDS,
        allowed=frozenset({"execution.failed", "execution.completed", "execution.waiting"}),
        after_index=start_index,
    )
    if failed.get("message_type") != "execution.failed":
        got = failed.get("message_type")
        return fail("checkpoint retry", f"expected execution.failed on first pass, got {got}")

    run_events = events_for_run(runtime.collector.events, run_id)
    completed = node_completed_ids(run_events)
    if CHECKPOINT_INPUT_NODE_ID not in completed:
        return fail("checkpoint retry", "input node did not complete before crash")
    if CHECKPOINT_HTTP_NODE_ID in completed:
        return fail(
            "checkpoint retry",
            "HTTP node completed before crash; checkpoint resume unprovable",
        )
    if CHECKPOINT_OUTPUT_NODE_ID in completed:
        return fail("checkpoint retry", "output node completed before crash")

    checkpoint = await query_checkpoint_envelope(runtime.pool, run_id)
    if checkpoint is None:
        return fail("checkpoint retry", "no row in ee.workflow_checkpoints after crash")
    outputs = checkpoint.get("node_outputs")
    if not isinstance(outputs, dict) or CHECKPOINT_INPUT_NODE_ID not in outputs:
        return fail("checkpoint retry", "checkpoint missing saved input node outputs")
    pending = _scheduler_pending(checkpoint)
    if CHECKPOINT_HTTP_NODE_ID not in pending:
        return fail(
            "checkpoint retry",
            f"expected HTTP node in checkpoint pending, got {pending!r}",
        )

    input_completed_before = node_completed_count(run_events, CHECKPOINT_INPUT_NODE_ID)
    retry_envelope, retry_run_id = build_start_envelope(
        workflow,
        run_input=run_input,
        run_id=run_id,
        idempotency_key=f"start:{run_id}:retry",
    )
    if retry_run_id != run_id:
        return fail("checkpoint retry", "retry envelope changed run_id")

    print(f"Retrying run {run_id} from saved checkpoint …")
    after_retry = runtime.collector.event_count()
    await publish_command(runtime.channel, retry_envelope, mq.EXECUTION_START_ROUTING_KEY)
    terminal = await wait_for_terminal(
        runtime.collector,
        run_id=run_id,
        timeout_seconds=WAIT_TIMEOUT_SECONDS,
        allowed=frozenset({"execution.completed", "execution.failed", "execution.waiting"}),
        after_index=after_retry,
    )
    if terminal.get("message_type") != "execution.completed":
        err = (terminal.get("payload") or {}).get("error")
        return fail(
            "checkpoint retry",
            f"retry did not complete: {terminal.get('message_type')} error={err!r}",
        )

    run_events = events_for_run(runtime.collector.events, run_id)
    if node_completed_count(run_events, CHECKPOINT_INPUT_NODE_ID) != input_completed_before:
        return fail("checkpoint retry", "input node was re-executed after checkpoint resume")
    if CHECKPOINT_HTTP_NODE_ID not in node_completed_ids(run_events):
        return fail("checkpoint retry", "HTTP node did not complete after checkpoint resume")
    if CHECKPOINT_OUTPUT_NODE_ID not in node_completed_ids(run_events):
        return fail("checkpoint retry", "output node did not complete after checkpoint resume")

    done = await _invariants(runtime, run_id, "checkpoint retry")
    if done:
        return done
    ok("checkpoint retry", "failed once, resumed from checkpoint, completed")
    return 0


async def _resume_review(
    runtime: E2ERuntime,
    *,
    waiting: dict[str, Any],
    run_id: str,
    workflow_id: str,
    workflow_version_id: str,
    prompt: str,
    correct: bool,
    answer: str | None,
) -> int | dict[str, Any]:
    interrupt = await query_interrupt_from_checkpoint(runtime.pool, run_id)
    if interrupt is None:
        return fail("human review loop", "no interrupt in ee.workflow_checkpoints")
    if str(interrupt.get("node_id")) != REVIEW_NODE_ID:
        return fail(
            "human review loop",
            f"expected review node interrupt, got node_id={interrupt.get('node_id')!r}",
        )
    payload = waiting.get("payload") or {}
    value: dict[str, Any] = {"prompt": prompt, "correct": correct}
    if correct and answer is not None:
        value["answer"] = answer
    resume_envelope = mint_resume_envelope(
        waiting_event=waiting,
        run_id=run_id,
        workflow_id=workflow_id,
        workflow_version_id=workflow_version_id,
        interrupt_id=str(payload["interrupt_id"]),
        approval_id=str(interrupt["approval_id"]),
        decision={"value": value},
    )
    print(f"Resuming review with correct={correct!r} …")
    after = runtime.collector.event_count()
    await publish_command(runtime.channel, resume_envelope, mq.EXECUTION_RESUME_ROUTING_KEY)
    terminal = await wait_for_terminal(
        runtime.collector,
        run_id=run_id,
        timeout_seconds=WAIT_TIMEOUT_SECONDS,
        allowed=frozenset({"execution.waiting", "execution.completed", "execution.failed"}),
        after_index=after,
    )
    return terminal


async def _run_human_review_loop_path(
    runtime: E2ERuntime,
    *,
    prompt: str,
    auto_loop: bool,
) -> int:
    workflow = _prepare_review_loop_workflow()
    run_input = {"prompt": prompt}
    envelope, run_id = build_start_envelope(workflow, run_input=run_input)
    workflow_id = workflow["workflow_id"]
    workflow_version_id = workflow["workflow_version_id"]

    print(f"\nStarting human-review loop run {run_id}")
    start_index = runtime.collector.event_count()
    await publish_command(runtime.channel, envelope, mq.EXECUTION_START_ROUTING_KEY)

    regenerations = 0
    event = await wait_for_terminal(
        runtime.collector,
        run_id=run_id,
        timeout_seconds=WAIT_TIMEOUT_SECONDS,
        allowed=frozenset({"execution.waiting", "execution.failed", "execution.completed"}),
        after_index=start_index,
    )
    while True:
        if event.get("message_type") == "execution.failed":
            err = (event.get("payload") or {}).get("error")
            return fail("human review loop", f"execution.failed: {err!r}")
        if event.get("message_type") == "execution.completed":
            if auto_loop and regenerations < 1:
                return fail("human review loop", "completed before regenerate cycle")
            break
        if event.get("message_type") != "execution.waiting":
            got = event.get("message_type")
            return fail("human review loop", f"expected execution.waiting, got {got}")

        payload = event.get("payload") or {}
        if payload.get("waiting_reason") != "HUMAN":
            return fail(
                "human review loop",
                f"unexpected waiting_reason: {payload.get('waiting_reason')!r}",
            )

        run_events = events_for_run(runtime.collector.events, run_id)
        chat_response = latest_chat_response_from_events(
            run_events,
            chat_node_id=REVIEW_CHAT_NODE_ID,
        )
        if chat_response is None:
            return fail("human review loop", "chat node did not produce response text")
        print_llm_response(chat_response, topic=prompt)
        answer = str(chat_response["text"])

        if auto_loop:
            correct = regenerations >= 1
        else:
            correct = await prompt_review_correctness()

        if not correct:
            regenerations += 1

        nxt = await _resume_review(
            runtime,
            waiting=event,
            run_id=run_id,
            workflow_id=workflow_id,
            workflow_version_id=workflow_version_id,
            prompt=prompt,
            correct=correct,
            answer=answer if correct else None,
        )
        if isinstance(nxt, int):
            return nxt
        event = nxt
        if event.get("message_type") == "execution.completed" and not correct:
            return fail("human review loop", "completed after incorrect review")

    run_events = events_for_run(runtime.collector.events, run_id)
    chat_runs = node_completed_count(run_events, REVIEW_CHAT_NODE_ID)
    if auto_loop and chat_runs < 2:
        return fail("human review loop", f"expected regenerate (2 chat runs), got {chat_runs}")

    done = await _invariants(runtime, run_id, "human review loop")
    if done:
        return done
    ok("human review loop", f"chat_runs={chat_runs} regenerations={regenerations}")
    return 0


async def _run_full_features_path(
    runtime: E2ERuntime,
    *,
    score: float,
    topic: str,
    items: list[str],
    interactive: bool,
    skip_task: bool,
) -> int:
    if not skip_task:
        durable = await _run_durable_task_path(runtime)
        if durable != 0:
            return durable
        cleanup = await _run_cleanup_plan_path(runtime)
        if cleanup != 0:
            return cleanup
    return await _run_high_score_path(
        runtime,
        score=score,
        topic=topic,
        items=items,
        interactive=interactive,
    )


async def main_async(
    *,
    skip_checkpoint: bool,
    skip_review_loop: bool,
    skip_full: bool,
    auto_loop: bool,
    interactive: bool,
    skip_task: bool,
    prompt: str,
    score: float,
    topic: str,
    items: list[str],
) -> int:
    logging.basicConfig(level=logging.INFO)
    runtime = await setup_runtime(log_label="multi-workflow")
    try:
        if not skip_checkpoint:
            result = await _run_checkpoint_retry_path(runtime)
            if result != 0:
                return result
        if not skip_review_loop:
            result = await _run_human_review_loop_path(
                runtime,
                prompt=prompt,
                auto_loop=auto_loop,
            )
            if result != 0:
                return result
        if not skip_full:
            result = await _run_full_features_path(
                runtime,
                score=score,
                topic=topic,
                items=items,
                interactive=interactive,
                skip_task=skip_task,
            )
            if result != 0:
                return result
        ok("multi-workflow", "all selected paths finished")
        return 0
    finally:
        await teardown_runtime(runtime)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run checkpoint-retry, human-review regenerate loop, and full-features "
            "workflows on one in-process worker"
        ),
    )
    parser.add_argument("--skip-checkpoint", action="store_true")
    parser.add_argument("--skip-review-loop", action="store_true")
    parser.add_argument("--skip-full", action="store_true")
    parser.add_argument(
        "--auto-loop",
        action="store_true",
        help="Reject the first review, then accept (no stdin)",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Prompt for full-features approval/review (default: auto)",
    )
    parser.add_argument(
        "--skip-task",
        action="store_true",
        help="Skip durable research/cleanup when running full-features",
    )
    parser.add_argument(
        "--prompt",
        type=str,
        default=DEFAULT_REVIEW_PROMPT,
        help="Input prompt for the human-review loop",
    )
    parser.add_argument("--score", type=float, default=FULL_DEFAULT_INPUT["score"])
    parser.add_argument("--topic", type=str, default=FULL_DEFAULT_INPUT["topic"])
    parser.add_argument(
        "--items",
        type=str,
        nargs="+",
        default=list(FULL_DEFAULT_INPUT["items"]),
    )
    args = parser.parse_args()
    return asyncio.run(
        main_async(
            skip_checkpoint=args.skip_checkpoint,
            skip_review_loop=args.skip_review_loop,
            skip_full=args.skip_full,
            auto_loop=args.auto_loop,
            interactive=args.interactive,
            skip_task=args.skip_task,
            prompt=args.prompt,
            score=args.score,
            topic=args.topic,
            items=list(args.items),
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
