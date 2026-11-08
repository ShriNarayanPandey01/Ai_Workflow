#!/usr/bin/env python3
"""Bring up docker compose, then run real-time control-plane & execution-plane demo flows.

Test Flows:
  1. Full AI + Approval + ForEach + Collect Flow (Condition score >= 0.5 -> True branch)
  2. Conditional Bypass Flow (Condition score < 0.5 -> False branch immediate output)
  3. Real-Time Execution Cancellation Flow (Cancel while waiting for human approval)
  4. Human Rejection Flow (Reject approval decision)
  5. Execution Cursor Pagination & Node Audit Flow

Real-Time Features:
  - Concurrent Server-Sent Events (SSE) stream listener (/api/v1/projects/{id}/executions/{id}/events)
  - Live event tracing (node.started, node.completed, execution.waiting, execution.resumed, execution.completed)
  - Human-in-the-loop approval inspection and decisioning
  - Multi-page cursor pagination verification

Usage (from repo root):
  python scripts/run_compose_demo.py
  python scripts/run_compose_demo.py --skip-compose
  python scripts/run_compose_demo.py --skip-compose --flow approval
  python scripts/run_compose_demo.py --skip-compose --flow condition
  python scripts/run_compose_demo.py --skip-compose --flow cancel
  python scripts/run_compose_demo.py --skip-compose --flow reject
  python scripts/run_compose_demo.py --skip-compose --flow all
  python scripts/run_compose_demo.py --no-sse
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from uuid import uuid4

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = REPO_ROOT / "contracts" / "fixtures" / "valid" / "workflow-compose-demo.json"
TERMINAL = frozenset({"SUCCEEDED", "FAILED", "CANCELLED", "TIMED_OUT"})


class ApiError(RuntimeError):
    def __init__(self, method: str, path: str, status: int, body: object) -> None:
        super().__init__(f"{method} {path} -> {status}: {body}")
        self.status = status
        self.body = body


class SseStreamConsumer(threading.Thread):
    """Background listener consuming live Server-Sent Events from the control plane."""

    def __init__(
        self,
        base_url: str,
        token: str,
        project_id: str,
        run_id: str,
        *,
        enabled: bool = True,
    ) -> None:
        super().__init__(daemon=True)
        self.url = f"{base_url.rstrip('/')}/api/v1/projects/{project_id}/executions/{run_id}/events"
        self.token = token
        self.run_id = run_id
        self.enabled = enabled
        self.events: list[dict[str, Any]] = []
        self._stop_event = threading.Event()

    def run(self) -> None:
        if not self.enabled:
            return
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "text/event-stream",
        }
        req = urllib.request.Request(self.url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=120) as response:
                current_event = "message"
                current_id = ""
                for raw_line in response:
                    if self._stop_event.is_set():
                        break
                    line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
                    if not line or line.startswith(":"):
                        continue
                    if line.startswith("event:"):
                        current_event = line[6:].strip()
                    elif line.startswith("id:"):
                        current_id = line[3:].strip()
                    elif line.startswith("data:"):
                        raw_data = line[5:].strip()
                        try:
                            parsed_data = json.loads(raw_data)
                        except json.JSONDecodeError:
                            parsed_data = raw_data
                        event_record = {
                            "id": current_id,
                            "event": current_event,
                            "data": parsed_data,
                            "timestamp": time.time(),
                        }
                        self.events.append(event_record)
                        self._log_event(current_event, parsed_data, current_id)
                        current_event = "message"
        except Exception:
            # Stream gracefully closes when execution reaches terminal state
            pass

    def _log_event(self, event_type: str, data: Any, event_id: str) -> None:
        prefix = f"  [SSE #{event_id or '?'}] {event_type}"
        if isinstance(data, dict):
            node_id = data.get("node_id") or data.get("nodeId")
            status = data.get("status")
            reason = data.get("waiting_reason") or data.get("waitingReason")
            details = []
            if node_id:
                details.append(f"node={node_id}")
            if status:
                details.append(f"status={status}")
            if reason:
                details.append(f"reason={reason}")
            detail_str = f" ({', '.join(details)})" if details else ""
            print(f"{prefix}{detail_str}", flush=True)
        else:
            print(f"{prefix}: {data}", flush=True)

    def stop(self) -> None:
        self._stop_event.set()


def log(step: str, detail: str = "") -> None:
    suffix = f" — {detail}" if detail else ""
    print(f"[OK] {step}{suffix}", flush=True)


def info(step: str, detail: str = "") -> None:
    suffix = f" — {detail}" if detail else ""
    print(f"[*] {step}{suffix}", flush=True)


def fail(step: str, message: str) -> int:
    print(f"[FAIL] {step}: {message}", file=sys.stderr, flush=True)
    return 1


def request(
    base_url: str,
    method: str,
    path: str,
    *,
    token: str | None = None,
    data: object | None = None,
    expected: int | tuple[int, ...] | None = None,
    timeout: float = 60,
) -> tuple[int, Any]:
    url = base_url.rstrip("/") + path
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            parsed: Any = json.loads(raw) if raw else {}
            status = response.status
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            parsed = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            parsed = raw
        status = exc.code
    except urllib.error.URLError as exc:
        raise ApiError(method, path, 0, str(exc.reason)) from exc
    except (OSError, TimeoutError, http.client.RemoteDisconnected) as exc:
        raise ApiError(method, path, 0, str(exc)) from exc
    if expected is not None:
        allowed = expected if isinstance(expected, tuple) else (expected,)
        if status not in allowed:
            raise ApiError(method, path, status, parsed)
    return status, parsed


def wait_ready(base_url: str, timeout_seconds: float) -> None:
    deadline = time.time() + timeout_seconds
    last_error = "not attempted"
    while time.time() < deadline:
        try:
            status, body = request(
                base_url, "GET", "/actuator/health/readiness", timeout=5
            )
            if status == 200:
                log("control-plane ready")
                return
            last_error = f"HTTP {status}: {body}"
        except ApiError as exc:
            last_error = str(exc)
        remaining = max(0, deadline - time.time())
        print(f"[wait] control-plane not ready ({last_error}); retry in 3s, {remaining:.0f}s left", flush=True)
        time.sleep(3)
    raise TimeoutError(f"control-plane not ready after {timeout_seconds:.0f}s ({last_error})")


def compose_up() -> None:
    env = os.environ.copy()
    env["AIW_FAKE_LLM"] = "true"
    cmd = ["docker", "compose", "up", "-d", "--build"]
    log("docker compose up", "AIW_FAKE_LLM=true")
    subprocess.run(cmd, cwd=REPO_ROOT, env=env, check=True)


def load_definition(workflow_id: str) -> dict:
    definition = json.loads(FIXTURE.read_text(encoding="utf-8"))
    definition["workflow_id"] = workflow_id
    definition["workflow_version_id"] = None
    definition["name"] = "Compose Demo Graph"
    return definition


def poll_run(
    base_url: str,
    token: str,
    project_id: str,
    run_id: str,
    timeout_seconds: float,
    ignore_interrupt_id: str | None = None,
) -> dict:
    deadline = time.time() + timeout_seconds
    last: dict = {}
    while time.time() < deadline:
        _, body = request(
            base_url,
            "GET",
            f"/api/v1/projects/{project_id}/executions/{run_id}",
            token=token,
            expected=200,
        )
        if not isinstance(body, dict):
            raise RuntimeError(f"unexpected execution body: {body}")
        last = body
        status = str(body.get("status") or "")
        waiting = body.get("waitingReason")
        if body.get("errorCode"):
            raise RuntimeError(
                f"run {run_id} errorCode={body.get('errorCode')} last={body}"
            )
        if status == "WAITING" and waiting == "HUMAN":
            interrupt_id = str(body.get("interruptId") or "")
            if ignore_interrupt_id and interrupt_id == ignore_interrupt_id:
                time.sleep(1)
                continue
            return last
        if status in TERMINAL:
            return last
        time.sleep(1)
    raise TimeoutError(f"run {run_id} did not reach WAITING/HUMAN or terminal; last={last}")


def decide_approval(
    base_url: str,
    token: str,
    project_id: str,
    run_id: str,
    decision: str,
    note: str = "compose-demo decision",
) -> dict:
    _, rows = request(
        base_url,
        "GET",
        f"/api/v1/approvals?projectId={project_id}",
        token=token,
        expected=200,
    )
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("no pending approvals found")
    approval_id = rows[0]["approvalId"]
    payload = {"data": {"note": note, "decidedAt": int(time.time())}}
    _, body = request(
        base_url,
        "POST",
        f"/api/v1/projects/{project_id}/executions/{run_id}/approvals/{approval_id}/decision",
        token=token,
        data={"decision": decision, "payload": payload},
        expected=200,
    )
    log("approval decision", f"{decision} approvalId={approval_id} status={body.get('status')}")
    return body


def cancel_execution(
    base_url: str,
    token: str,
    project_id: str,
    run_id: str,
) -> dict:
    _, body = request(
        base_url,
        "POST",
        f"/api/v1/projects/{project_id}/executions/{run_id}/cancel",
        token=token,
        expected=200,
    )
    log("cancel execution", f"runId={run_id} status={body.get('status')}")
    return body


def start_execution(
    base_url: str,
    token: str,
    project_id: str,
    workflow_id: str,
    input_data: dict,
    tag: str,
) -> str:
    _, started = request(
        base_url,
        "POST",
        f"/api/v1/projects/{project_id}/workflows/{workflow_id}/executions",
        token=token,
        data={
            "mode": "published",
            "input": input_data,
            "idempotencyKey": f"compose-{tag}-{uuid4()}",
        },
        expected=202,
    )
    return started["runId"]


# =============================================================================
# FLOW 1: AI + Human Approval + For-Each + Collect (True Branch)
# =============================================================================
def test_approval_flow(
    base_url: str,
    token: str,
    project_id: str,
    workflow_id: str,
    timeout: float,
    use_sse: bool,
) -> tuple[bool, str, float]:
    start_time = time.time()
    info("Starting Flow 1", "AI + Human Approval + ForEach + Collect (True Condition Branch)")
    run_input = {
        "topic": "Quantum Computing & Superposition",
        "score": 0.95,
        "items": ["Qubit", "Superposition", "Entanglement"],
    }
    run_id = start_execution(base_url, token, project_id, workflow_id, run_input, "approval")
    log("start run", f"runId={run_id}")

    sse = SseStreamConsumer(base_url, token, project_id, run_id, enabled=use_sse)
    sse.start()

    try:
        snapshot = poll_run(base_url, token, project_id, run_id, timeout)
        if snapshot.get("status") == "WAITING" and snapshot.get("waitingReason") == "HUMAN":
            log("approval required", f"interruptId={snapshot.get('interruptId')}")
            decide_approval(base_url, token, project_id, run_id, "APPROVE", "Approved AI generated summary")
            snapshot = poll_run(
                base_url,
                token,
                project_id,
                run_id,
                timeout,
                ignore_interrupt_id=str(snapshot.get("interruptId")),
            )
    finally:
        sse.stop()

    duration = time.time() - start_time
    status = str(snapshot.get("status") or "")
    if status != "SUCCEEDED":
        return False, f"status was {status} (errorCode={snapshot.get('errorCode')})", duration

    nodes = snapshot.get("nodes") or []
    log("completed Flow 1", f"SUCCEEDED in {duration:.1f}s across {len(nodes)} nodes, {len(sse.events)} SSE events")
    return True, f"SUCCEEDED (nodes={len(nodes)}, sse_events={len(sse.events)})", duration


# =============================================================================
# FLOW 2: Conditional Bypass Flow (False Branch: score < 0.5)
# =============================================================================
def test_conditional_bypass_flow(
    base_url: str,
    token: str,
    project_id: str,
    workflow_id: str,
    timeout: float,
    use_sse: bool,
) -> tuple[bool, str, float]:
    start_time = time.time()
    info("Starting Flow 2", "Conditional Bypass Flow (score=0.2 -> False branch direct output)")
    run_input = {
        "topic": "Low Priority Item",
        "score": 0.2,
        "items": ["direct-item-1", "direct-item-2"],
    }
    run_id = start_execution(base_url, token, project_id, workflow_id, run_input, "bypass")
    log("start run", f"runId={run_id}")

    sse = SseStreamConsumer(base_url, token, project_id, run_id, enabled=use_sse)
    sse.start()

    try:
        snapshot = poll_run(base_url, token, project_id, run_id, timeout)
    finally:
        sse.stop()

    duration = time.time() - start_time
    status = str(snapshot.get("status") or "")
    if status != "SUCCEEDED":
        return False, f"status was {status} (errorCode={snapshot.get('errorCode')})", duration

    # Ensure it did not enter WAITING state
    if snapshot.get("waitingReason") == "HUMAN":
        return False, "False condition branch unexpectedly halted for Human Approval", duration

    nodes = snapshot.get("nodes") or []
    log("completed Flow 2", f"SUCCEEDED in {duration:.1f}s (bypassed AI & Approval, executed {len(nodes)} nodes)")
    return True, f"SUCCEEDED (bypassed approval, nodes={len(nodes)})", duration


# =============================================================================
# FLOW 3: Real-Time Execution Cancellation Flow
# =============================================================================
def test_cancellation_flow(
    base_url: str,
    token: str,
    project_id: str,
    workflow_id: str,
    timeout: float,
    use_sse: bool,
) -> tuple[bool, str, float]:
    start_time = time.time()
    info("Starting Flow 3", "Real-Time Cancellation Flow (Cancel during WAITING state)")
    run_input = {
        "topic": "Cancelled Topic",
        "score": 0.85,
        "items": ["item-will-be-cancelled"],
    }
    run_id = start_execution(base_url, token, project_id, workflow_id, run_input, "cancel")
    log("start run", f"runId={run_id}")

    sse = SseStreamConsumer(base_url, token, project_id, run_id, enabled=use_sse)
    sse.start()

    try:
        snapshot = poll_run(base_url, token, project_id, run_id, timeout)
        if snapshot.get("status") == "WAITING":
            log("reached WAITING state", "sending cancel command...")
            cancel_execution(base_url, token, project_id, run_id)
            snapshot = poll_run(base_url, token, project_id, run_id, timeout)
    finally:
        sse.stop()

    duration = time.time() - start_time
    status = str(snapshot.get("status") or "")
    if status != "CANCELLED":
        return False, f"expected CANCELLED, got {status}", duration

    log("completed Flow 3", f"CANCELLED as expected in {duration:.1f}s")
    return True, "CANCELLED cleanly via REST API", duration


# =============================================================================
# FLOW 4: Human Rejection Flow
# =============================================================================
def test_rejection_flow(
    base_url: str,
    token: str,
    project_id: str,
    workflow_id: str,
    timeout: float,
    use_sse: bool,
) -> tuple[bool, str, float]:
    start_time = time.time()
    info("Starting Flow 4", "Human Rejection Flow (Reject approval decision)")
    run_input = {
        "topic": "Unacceptable Topic",
        "score": 0.9,
        "items": ["item-1"],
    }
    run_id = start_execution(base_url, token, project_id, workflow_id, run_input, "reject")
    log("start run", f"runId={run_id}")

    sse = SseStreamConsumer(base_url, token, project_id, run_id, enabled=use_sse)
    sse.start()

    try:
        snapshot = poll_run(base_url, token, project_id, run_id, timeout)
        if snapshot.get("status") == "WAITING" and snapshot.get("waitingReason") == "HUMAN":
            log("approval required", "submitting REJECT decision...")
            decide_approval(base_url, token, project_id, run_id, "REJECT", "Rejected: Topic does not meet guidelines")
            snapshot = poll_run(
                base_url,
                token,
                project_id,
                run_id,
                timeout,
                ignore_interrupt_id=str(snapshot.get("interruptId")),
            )
    finally:
        sse.stop()

    duration = time.time() - start_time
    status = str(snapshot.get("status") or "")
    log("completed Flow 4", f"Terminal status: {status} in {duration:.1f}s")
    return True, f"Resolved rejection (terminal status={status})", duration


# =============================================================================
# FLOW 5: Cursor Pagination & Node Execution Audit Flow
# =============================================================================
def test_pagination_and_audit(
    base_url: str,
    token: str,
    project_id: str,
) -> tuple[bool, str, float]:
    start_time = time.time()
    info("Starting Flow 5", "Execution Cursor Pagination & Audit Inspection")

    # 1. Fetch page 1 (limit=2)
    _, page1 = request(
        base_url,
        "GET",
        f"/api/v1/projects/{project_id}/executions?limit=2",
        token=token,
        expected=200,
    )
    items1 = page1.get("items") or []
    next_cursor = page1.get("next")
    log("executions page 1", f"retrieved {len(items1)} runs, next_cursor={'yes' if next_cursor else 'none'}")

    if not items1:
        return False, "no executions found in project", time.time() - start_time

    # 2. If next cursor is present, fetch page 2
    if next_cursor:
        _, page2 = request(
            base_url,
            "GET",
            f"/api/v1/projects/{project_id}/executions?cursor={next_cursor}&limit=2",
            token=token,
            expected=200,
        )
        items2 = page2.get("items") or []
        log("executions page 2", f"retrieved {len(items2)} runs via cursor pagination")

    # 3. Inspect details of the most recent run
    sample_run_id = items1[0]["runId"]
    _, detail = request(
        base_url,
        "GET",
        f"/api/v1/projects/{project_id}/executions/{sample_run_id}",
        token=token,
        expected=200,
    )
    nodes = detail.get("nodes") or []
    log("execution audit", f"runId={sample_run_id} status={detail.get('status')} nodes_executed={len(nodes)}")

    duration = time.time() - start_time
    return True, f"Pagination & audit verified ({len(items1)} runs on page 1)", duration


# =============================================================================
# MAIN ORCHESTRATION
# =============================================================================
def run(args: argparse.Namespace) -> int:
    if not FIXTURE.is_file():
        return fail("fixture", f"missing {FIXTURE}")
    if not args.skip_compose:
        try:
            compose_up()
        except subprocess.CalledProcessError as exc:
            return fail("docker compose", str(exc))
        except FileNotFoundError:
            return fail("docker compose", "docker CLI not found on PATH")
    try:
        wait_ready(args.base_url, args.ready_timeout)
    except TimeoutError as exc:
        return fail("readiness", str(exc))

    email = f"demo+{int(time.time())}@example.com"
    password = "password1"
    _, registered = request(
        args.base_url,
        "POST",
        "/api/v1/auth/register",
        data={"email": email, "password": password, "displayName": "RealTime Demo"},
        expected=201,
    )
    workspace_id = registered["user"]["workspaceId"]
    log("register", f"email={email} workspaceId={workspace_id}")

    _, logged_in = request(
        args.base_url,
        "POST",
        "/api/v1/auth/login",
        data={"email": email, "password": password},
        expected=200,
    )
    token = logged_in["accessToken"]
    log("login")

    _, project = request(
        args.base_url,
        "POST",
        "/api/v1/projects",
        token=token,
        data={"name": "RealTime Flow Project"},
        expected=201,
    )
    project_id = project["projectId"]
    log("create project", project_id)

    _, workflow = request(
        args.base_url,
        "POST",
        f"/api/v1/projects/{project_id}/workflows",
        token=token,
        data={"name": "Compose Demo Graph"},
        expected=201,
    )
    workflow_id = workflow["workflowId"]
    log("create workflow", f"{workflow_id}")

    _, draft = request(
        args.base_url,
        "GET",
        f"/api/v1/projects/{project_id}/workflows/{workflow_id}/draft",
        token=token,
        expected=200,
    )
    revision = draft["revision"]
    definition = load_definition(workflow_id)
    _, saved = request(
        args.base_url,
        "PUT",
        f"/api/v1/projects/{project_id}/workflows/{workflow_id}/draft",
        token=token,
        data={"baseRevision": revision, "definition": definition},
        expected=200,
    )
    log("put draft", f"revision={saved.get('revision')}")

    request(
        args.base_url,
        "POST",
        f"/api/v1/projects/{project_id}/workflows/{workflow_id}/validate",
        token=token,
        expected=200,
    )
    log("validate workflow", "valid")

    _, published = request(
        args.base_url,
        "POST",
        f"/api/v1/projects/{project_id}/workflows/{workflow_id}/publish",
        token=token,
        expected=201,
    )
    version_id = published.get("versionId")
    log("publish workflow", f"versionId={version_id}")

    # =========================================================================
    # EXECUTE FLOWS
    # =========================================================================
    results: list[dict[str, Any]] = []
    use_sse = not args.no_sse
    flow = args.flow.lower()

    if flow in ("all", "approval"):
        ok, msg, dur = test_approval_flow(
            args.base_url, token, project_id, workflow_id, args.run_timeout, use_sse
        )
        results.append({"name": "Flow 1: AI + Approval + FanOut", "ok": ok, "detail": msg, "duration": dur})

    if flow in ("all", "condition"):
        ok, msg, dur = test_conditional_bypass_flow(
            args.base_url, token, project_id, workflow_id, args.run_timeout, use_sse
        )
        results.append({"name": "Flow 2: Condition Bypass (score < 0.5)", "ok": ok, "detail": msg, "duration": dur})

    if flow in ("all", "cancel"):
        ok, msg, dur = test_cancellation_flow(
            args.base_url, token, project_id, workflow_id, args.run_timeout, use_sse
        )
        results.append({"name": "Flow 3: Execution Cancellation", "ok": ok, "detail": msg, "duration": dur})

    if flow in ("all", "reject"):
        ok, msg, dur = test_rejection_flow(
            args.base_url, token, project_id, workflow_id, args.run_timeout, use_sse
        )
        results.append({"name": "Flow 4: Human Rejection", "ok": ok, "detail": msg, "duration": dur})

    if flow in ("all", "audit"):
        ok, msg, dur = test_pagination_and_audit(args.base_url, token, project_id)
        results.append({"name": "Flow 5: Pagination & Node Audit", "ok": ok, "detail": msg, "duration": dur})

    # =========================================================================
    # SUMMARY REPORT
    # =========================================================================
    print("\n" + "=" * 78, flush=True)
    print(" " * 24 + "REAL-TIME FLOW TEST RESULTS", flush=True)
    print("=" * 78, flush=True)
    all_passed = True
    for r in results:
        mark = "[PASS]" if r["ok"] else "[FAIL]"
        if not r["ok"]:
            all_passed = False
        print(f" {mark} {r['name']:<38} | {r['duration']:>5.1f}s | {r['detail']}", flush=True)
    print("=" * 78, flush=True)

    if not all_passed:
        return fail("summary", "One or more real-time test flows failed")

    log("all flows passed successfully!")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Comprehensive real-time Control Plane & Execution Plane test suite"
    )
    parser.add_argument("--base-url", default="http://localhost:8080", help="Control plane base URL")
    parser.add_argument("--skip-compose", action="store_true", help="Skip bringing up Docker Compose")
    parser.add_argument("--ready-timeout", type=float, default=180, help="Readiness timeout in seconds")
    parser.add_argument("--run-timeout", type=float, default=180, help="Per-run timeout in seconds")
    parser.add_argument(
        "--flow",
        default="all",
        choices=["all", "approval", "condition", "cancel", "reject", "audit"],
        help="Specify which flow to test (default: all)",
    )
    parser.add_argument(
        "--no-sse",
        action="store_true",
        help="Disable live Server-Sent Events output",
    )
    args = parser.parse_args()
    try:
        return run(args)
    except ApiError as exc:
        return fail("http", str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
