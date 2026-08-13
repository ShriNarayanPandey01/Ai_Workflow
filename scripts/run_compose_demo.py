#!/usr/bin/env python3
"""Bring up docker compose, then run a no-RAG control-plane demo.

Sequence (no workspace API; drafts belong to a workflow):
  register + login
  POST /projects
  POST /workflows  (creates empty draft)
  PUT  /draft
  validate + publish
  start published run
  wait for HUMAN approval, decide via control-plane API
  print run output

Usage (from repo root):
  python scripts/run_compose_demo.py
  python scripts/run_compose_demo.py --skip-compose
  python scripts/run_compose_demo.py --reject
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from uuid import uuid4

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = REPO_ROOT / "contracts" / "fixtures" / "valid" / "workflow-compose-demo.json"
TERMINAL = frozenset({"SUCCEEDED", "FAILED", "CANCELLED", "TIMED_OUT"})
RUN_INPUT = {"topic": "widgets", "score": 0.9, "items": ["alpha", "beta"]}


class ApiError(RuntimeError):
    def __init__(self, method: str, path: str, status: int, body: object) -> None:
        super().__init__(f"{method} {path} -> {status}: {body}")
        self.status = status
        self.body = body


def log(step: str, detail: str = "") -> None:
    suffix = f" — {detail}" if detail else ""
    print(f"[OK] {step}{suffix}", flush=True)


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
) -> tuple[int, object]:
    url = base_url.rstrip("/") + path
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            parsed: object = json.loads(raw) if raw else {}
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
        print(f"  run status={status} waitingReason={waiting}", flush=True)
        if body.get("errorCode"):
            raise RuntimeError(
                f"run {run_id} errorCode={body.get('errorCode')} last={body}"
            )
        if status == "WAITING" and waiting == "HUMAN":
            interrupt_id = body.get("interruptId")
            if ignore_interrupt_id and interrupt_id == ignore_interrupt_id:
                time.sleep(2)
                continue
            return last
        if status in TERMINAL:
            return last
        time.sleep(2)
    raise TimeoutError(f"run {run_id} did not reach WAITING/HUMAN or terminal; last={last}")


def decide_approval(
    base_url: str,
    token: str,
    project_id: str,
    run_id: str,
    decision: str,
) -> None:
    _, rows = request(
        base_url,
        "GET",
        f"/api/v1/approvals?projectId={project_id}",
        token=token,
        expected=200,
    )
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("no pending approvals")
    approval_id = rows[0]["approvalId"]
    payload = {"data": {"note": "compose-demo"}}
    _, body = request(
        base_url,
        "POST",
        f"/api/v1/projects/{project_id}/executions/{run_id}/approvals/{approval_id}/decision",
        token=token,
        data={"decision": decision, "payload": payload},
        expected=200,
    )
    log("approval decision", f"{decision} approvalId={approval_id} status={body.get('status')}")


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
        data={"email": email, "password": password, "displayName": "Compose Demo"},
        expected=201,
    )
    workspace_id = registered["user"]["workspaceId"]
    log("register", f"email={email} workspaceId={workspace_id} (implicit PERSONAL workspace)")

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
        data={"name": "Compose Demo"},
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
    log("create workflow", f"{workflow_id} (empty draft revision 1)")

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
    log("validate")
    _, published = request(
        args.base_url,
        "POST",
        f"/api/v1/projects/{project_id}/workflows/{workflow_id}/publish",
        token=token,
        expected=201,
    )
    log("publish", f"versionId={published.get('versionId')}")

    _, started = request(
        args.base_url,
        "POST",
        f"/api/v1/projects/{project_id}/workflows/{workflow_id}/executions",
        token=token,
        data={
            "mode": "published",
            "input": RUN_INPUT,
            "idempotencyKey": f"compose-demo-{uuid4()}",
        },
        expected=202,
    )
    run_id = started["runId"]
    log("start run", run_id)

    try:
        snapshot = poll_run(args.base_url, token, project_id, run_id, args.run_timeout)
        if snapshot.get("status") == "WAITING" and snapshot.get("waitingReason") == "HUMAN":
            approved_interrupt = snapshot.get("interruptId")
            decide_approval(args.base_url, token, project_id, run_id, args.decision)
            snapshot = poll_run(
                args.base_url,
                token,
                project_id,
                run_id,
                args.run_timeout,
                ignore_interrupt_id=str(approved_interrupt) if approved_interrupt else None,
            )
    except (TimeoutError, ApiError, RuntimeError) as exc:
        return fail("run", str(exc))

    print("\n=== workflow result ===", flush=True)
    print(json.dumps(snapshot, indent=2), flush=True)
    status = str(snapshot.get("status") or "")
    if status != "SUCCEEDED":
        return fail("run", f"terminal status {status} errorCode={snapshot.get('errorCode')}")
    log("completed", "SUCCEEDED")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Docker compose + control-plane demo (no RAG)")
    parser.add_argument("--base-url", default="http://localhost:8080")
    parser.add_argument("--skip-compose", action="store_true")
    parser.add_argument("--ready-timeout", type=float, default=180)
    parser.add_argument("--run-timeout", type=float, default=180)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--approve", dest="decision", action="store_const", const="APPROVE")
    group.add_argument("--reject", dest="decision", action="store_const", const="REJECT")
    parser.set_defaults(decision="APPROVE")
    args = parser.parse_args()
    try:
        return run(args)
    except ApiError as exc:
        return fail("http", str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
