#!/usr/bin/env python3
"""Control-plane mimic: run the combo workflow for real over RabbitMQ.

Uses a live OpenAI-compatible chat model, interactive human approval in the
terminal, and a real for-each loop with live HTTP (httpbin.org).

Triggers workflow-e2e-combo.json:
  control.condition, ai.prompt-template, ai.chat-model,
  human.approval, control.for-each (+ HTTP + collect).

Prerequisites (from repo root):
    docker compose up -d postgres rabbitmq
    docker compose stop execution-worker task-worker

Requires BASETEN_API_KEY in services/execution-engine/.env (AIW_FAKE_LLM must
not be true).

Usage:
    cd services/execution-engine
    uv run python scripts/trigger_combo_workflow.py
    uv run python scripts/trigger_combo_workflow.py --score 0.1
    uv run python scripts/trigger_combo_workflow.py --topic "quarterly results"
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from typing import Any

from e2e_helpers import (
    WAIT_TIMEOUT_SECONDS,
    E2ERuntime,
    build_start_envelope,
    chat_response_from_events,
    events_for_run,
    fail,
    load_json,
    mint_resume_envelope,
    node_completed_ids,
    ok,
    prepare_live_workflow,
    print_llm_response,
    prompt_human_decision,
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
FOR_EACH_NODE_ID = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeee11"
LOW_OUTPUT_NODE_ID = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeee10"

FIXTURES_DIR = REPO_ROOT / "contracts" / "fixtures" / "valid"
COMBO_FIXTURE = FIXTURES_DIR / "workflow-e2e-combo.json"
DEFAULT_INPUT = {
    "topic": "markets",
    "score": 0.9,
    "items": ["alpha", "beta"],
}


def _prepare_combo_workflow(*, chat_model: str) -> dict[str, Any]:
    """Load combo fixture and point HTTP + chat credentials at a live path."""
    return prepare_live_workflow(
        load_json(COMBO_FIXTURE),
        http_node_id=HTTP_NODE_ID,
        chat_node_id=CHAT_NODE_ID,
        chat_model=chat_model,
    )


async def _run_high_score_path(
    runtime: E2ERuntime,
    *,
    score: float,
    topic: str,
    items: list[str],
) -> int:
    workflow = _prepare_combo_workflow(chat_model=runtime.settings.chat_model)
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
        return fail("high-score path", f"execution.failed before human gate: {err!r}")
    if waiting.get("message_type") != "execution.waiting":
        got = waiting.get("message_type")
        return fail("high-score path", f"expected execution.waiting, got {got}")

    payload = waiting.get("payload") or {}
    if payload.get("waiting_reason") != "HUMAN":
        reason = payload.get("waiting_reason")
        return fail("high-score path", f"unexpected waiting_reason: {reason!r}")

    run_events = events_for_run(runtime.collector.events, run_id)
    chat_response = chat_response_from_events(run_events, chat_node_id=CHAT_NODE_ID)
    if chat_response is None:
        return fail("high-score path", "chat node did not produce response text before human gate")

    print_llm_response(chat_response, topic=topic)
    chat_text = str(chat_response["text"])

    interrupt = await query_interrupt_from_checkpoint(runtime.pool, run_id)
    if interrupt is None:
        return fail("high-score path", "no interrupt in ee.workflow_checkpoints")

    decision = await prompt_human_decision()
    resume_envelope = mint_resume_envelope(
        waiting_event=waiting,
        run_id=run_id,
        workflow_id=workflow_id,
        workflow_version_id=workflow_version_id,
        interrupt_id=str(payload["interrupt_id"]),
        approval_id=str(interrupt["approval_id"]),
        decision=decision,
    )
    print(f"Resuming with decision={decision['decision']!r} …")
    after_resume = runtime.collector.event_count()
    await publish_command(runtime.channel, resume_envelope, mq.EXECUTION_RESUME_ROUTING_KEY)

    terminal = await wait_for_terminal(
        runtime.collector,
        run_id=run_id,
        timeout_seconds=WAIT_TIMEOUT_SECONDS,
        allowed=frozenset({"execution.completed", "execution.failed"}),
        after_index=after_resume,
    )
    if terminal.get("message_type") != "execution.completed":
        err = (terminal.get("payload") or {}).get("error")
        return fail(
            "high-score path",
            f"resume did not complete: {terminal.get('message_type')} error={err!r}",
        )

    outputs = (terminal.get("payload") or {}).get("outputs")
    if not isinstance(outputs, dict):
        return fail("high-score path", f"expected object outputs, got {outputs!r}")

    summary = outputs.get("summary")
    if not isinstance(summary, dict):
        return fail("high-score path", f"expected collect summary, got {outputs!r}")
    expected = len(items)
    if summary.get("total") != expected or summary.get("completed") != expected:
        return fail("high-score path", f"unexpected collect summary: {summary!r}")

    successes = outputs.get("successes")
    if not isinstance(successes, list) or len(successes) != expected:
        return fail("high-score path", f"expected {expected} successes, got {successes!r}")

    ok("high-score path", f"decision={decision['decision']!r} summary={summary!r}")
    print("\n=== FINAL LLM RESPONSE ===")
    print(chat_text)
    print("==========================\n")
    print(f"Collect successes: {json.dumps(successes, indent=2, ensure_ascii=False)}")
    return 0


async def _run_low_score_path(
    runtime: E2ERuntime,
    *,
    topic: str,
    items: list[str],
) -> int:
    workflow = _prepare_combo_workflow(chat_model=runtime.settings.chat_model)
    run_input = {"topic": topic, "score": 0.1, "items": items}
    envelope, run_id = build_start_envelope(workflow, run_input=run_input)

    print(f"\nStarting low-score run {run_id} (condition skips AI / human / for-each)")
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
        return fail("low-score path", "should not pause for human approval")
    if terminal.get("message_type") != "execution.completed":
        got = terminal.get("message_type")
        return fail("low-score path", f"expected execution.completed, got {got}")

    run_events = events_for_run(runtime.collector.events, run_id)
    completed_ids = node_completed_ids(run_events)
    if LOW_OUTPUT_NODE_ID not in completed_ids:
        return fail("low-score path", "low-branch output node did not complete")
    if CHAT_NODE_ID in completed_ids:
        return fail("low-score path", "chat node should not run on low-score branch")
    if FOR_EACH_NODE_ID in completed_ids:
        return fail("low-score path", "for-each should not run on low-score branch")

    ok("low-score path", f"output={(terminal.get('payload') or {}).get('outputs')!r}")
    return 0


async def main_async(
    *,
    score: float,
    topic: str,
    items: list[str],
    also_low: bool,
) -> int:
    logging.basicConfig(level=logging.INFO)
    runtime = await setup_runtime(log_label="combo")
    try:
        if also_low:
            low = await _run_low_score_path(runtime, topic=topic, items=items)
            if low != 0:
                return low
        if score < 0.5:
            return await _run_low_score_path(runtime, topic=topic, items=items)
        return await _run_high_score_path(
            runtime,
            score=score,
            topic=topic,
            items=items,
        )
    finally:
        await teardown_runtime(runtime)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Control-plane mimic: real AI + interactive human approval + for-each"
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
        "--also-low",
        action="store_true",
        help="Also run the low-score conditional branch before the high path",
    )
    args = parser.parse_args()
    return asyncio.run(
        main_async(
            score=args.score,
            topic=args.topic,
            items=list(args.items),
            also_low=args.also_low,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
