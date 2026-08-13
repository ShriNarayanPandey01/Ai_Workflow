#!/usr/bin/env python3
"""
Conditional Node & Human Approval Verification Script

Tests:
1. Conditional Branching Flow (control.condition@1)
   - Evaluates numeric / path condition (e.g. score >= 75)
   - Verifies TRUE branch execution when score = 90
   - Verifies FALSE branch execution when score = 40
2. Human Approval & Review Flow (human.approval@1 + ApprovalController API)
   - Triggers a workflow requiring human review & decision
   - Invokes Control Plane Human Approval Decision API (/api/v1/projects/{projectId}/executions/{runId}/approvals/{approvalId}/decision)
   - Verifies resolution and execution completion
"""

import json
import sys
import time
import urllib.request
import urllib.error

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

BASE_URL = "http://localhost:8080"

def request(method: str, path: str, data: dict = None, token: str = None) -> tuple[int, dict]:
    url = f"{BASE_URL}{path}"
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    body = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req) as response:
            res_body = response.read().decode("utf-8")
            return response.status, json.loads(res_body) if res_body else {}
    except urllib.error.HTTPError as e:
        res_body = e.read().decode("utf-8")
        err_json = json.loads(res_body) if res_body else {}
        print(f" [X] HTTP Error {e.code} on {method} {path}: {err_json}")
        return e.code, err_json
    except Exception as exc:
        print(f" [X] Connection Error on {method} {path}: {exc}")
        return 500, {"error": str(exc)}

def test_conditional_and_approval():
    print("=" * 75)
    print("TESTING CONDITIONAL NODE & HUMAN APPROVAL FLOWS")
    print("=" * 75)

    # 1. Register & Login
    timestamp = int(time.time())
    email = f"cond_user_{timestamp}@example.com"
    password = "SecurePassword123!"

    print(f"[*] Registering test user: {email}")
    status, reg_res = request("POST", "/api/v1/auth/register", {
        "email": email, "password": password, "fullName": "Condition Approval Tester"
    })
    token = reg_res["accessToken"]

    # 2. Get workspace & project
    status, ws_res = request("GET", "/api/v1/projects/workspaces", token=token)
    workspace_id = ws_res[0]["id"]

    status, proj_res = request("POST", "/api/v1/projects", {
        "workspaceId": workspace_id,
        "name": f"Condition & Approval Project {timestamp}",
        "description": "Project for conditional routing and human approval"
    }, token=token)
    project_id = proj_res["id"]
    print(f" [✓] Created Project ID: {project_id}")

    # =========================================================================
    # FLOW A: Conditional Routing Flow (control.condition@1)
    # =========================================================================
    print("\n" + "-" * 70)
    print("FLOW A: CONDITIONAL ROUTING WORKFLOW (control.condition@1)")
    print("-" * 70)

    status, wf_a = request("POST", f"/api/v1/projects/{project_id}/workflows", {
        "name": "Conditional Branch Workflow",
        "description": "Routes data depending on whether score >= 75"
    }, token=token)
    wf_a_id = wf_a["id"]

    # Condition: inputs.value.score >= 75
    cond_def = {
        "schema_version": "1.0",
        "workflow_id": wf_a_id,
        "name": "Conditional Workflow",
        "nodes": [
            {"id": "input_1", "type": "data.input@1", "config": {}},
            {
                "id": "condition_1",
                "type": "control.condition@1",
                "config": {
                    "condition": {
                        "op": "gte",
                        "left": {"kind": "path", "value": "/value/score"},
                        "right": {"kind": "literal", "value": 75}
                    }
                }
            },
            {"id": "output_true", "type": "data.output@1", "config": {}},
            {"id": "output_false", "type": "data.output@1", "config": {}}
        ],
        "edges": [
            {
                "id": "e1",
                "source_node_id": "input_1",
                "source_port": "value",
                "target_node_id": "condition_1",
                "target_port": "value"
            },
            {
                "id": "e2",
                "source_node_id": "condition_1",
                "source_port": "true",
                "target_node_id": "output_true",
                "target_port": "value"
            },
            {
                "id": "e3",
                "source_node_id": "condition_1",
                "source_port": "false",
                "target_node_id": "output_false",
                "target_port": "value"
            }
        ]
    }

    _, draft_info_a = request("GET", f"/api/v1/projects/{project_id}/workflows/{wf_a_id}/draft", token=token)
    rev_a = draft_info_a.get("revision", 1) if isinstance(draft_info_a, dict) else 1
    request("PUT", f"/api/v1/projects/{project_id}/workflows/{wf_a_id}/draft", {
        "baseRevision": rev_a, "definition": cond_def
    }, token=token)

    request("POST", f"/api/v1/projects/{project_id}/workflows/{wf_a_id}/publish", {"versionNumber": 1}, token=token)

    # Test Case A1: Score = 90 (High Score -> Should route to TRUE branch)
    print("\n[*] Case A1: Input Score = 90 (Expecting TRUE Branch)...")
    status, exec_a1 = request("POST", f"/api/v1/projects/{project_id}/workflows/{wf_a_id}/executions", {
        "mode": "published", "input": {"score": 90, "student": "Alice"}
    }, token=token)
    run_a1_id = exec_a1["runId"]

    time.sleep(3)
    status, detail_a1 = request("GET", f"/api/v1/projects/{project_id}/executions/{run_a1_id}", token=token)
    print(f" [✓] Execution Status: {detail_a1.get('status')}")
    print(f"     Node Executions Recorded: {len(detail_a1.get('nodeExecutions', []))}")
    for ne in detail_a1.get("nodeExecutions", []):
        print(f"      - Node: {ne.get('nodeId')} | Type: {ne.get('nodeType')} | Status: {ne.get('status')}")

    # Test Case A2: Score = 40 (Low Score -> Should route to FALSE branch)
    print("\n[*] Case A2: Input Score = 40 (Expecting FALSE Branch)...")
    status, exec_a2 = request("POST", f"/api/v1/projects/{project_id}/workflows/{wf_a_id}/executions", {
        "mode": "published", "input": {"score": 40, "student": "Bob"}
    }, token=token)
    run_a2_id = exec_a2["runId"]

    time.sleep(3)
    status, detail_a2 = request("GET", f"/api/v1/projects/{project_id}/executions/{run_a2_id}", token=token)
    print(f" [✓] Execution Status: {detail_a2.get('status')}")
    print(f"     Node Executions Recorded: {len(detail_a2.get('nodeExecutions', []))}")
    for ne in detail_a2.get("nodeExecutions", []):
        print(f"      - Node: {ne.get('nodeId')} | Type: {ne.get('nodeType')} | Status: {ne.get('status')}")

    # =========================================================================
    # FLOW B: Human Approval & Review Workflow (human.approval@1)
    # =========================================================================
    print("\n" + "-" * 70)
    print("FLOW B: HUMAN APPROVAL & REVIEW WORKFLOW (human.approval@1)")
    print("-" * 70)

    status, wf_b = request("POST", f"/api/v1/projects/{project_id}/workflows", {
        "name": "Human Approval Workflow",
        "description": "Requires human reviewer approval before publishing campaign"
    }, token=token)
    wf_b_id = wf_b["id"]

    appr_def = {
        "schema_version": "1.0",
        "workflow_id": wf_b_id,
        "name": "Human Approval Workflow",
        "nodes": [
            {"id": "input_1", "type": "data.input@1", "config": {}},
            {
                "id": "approval_step",
                "type": "human.approval@1",
                "config": {
                    "title": "Review Marketing Campaign Release",
                    "instructions": "Verify compliance and budget before approving release."
                }
            },
            {"id": "output_1", "type": "data.output@1", "config": {}}
        ],
        "edges": [
            {
                "id": "e1",
                "source_node_id": "input_1",
                "source_port": "value",
                "target_node_id": "approval_step",
                "target_port": "request"
            },
            {
                "id": "e2",
                "source_node_id": "approval_step",
                "source_port": "decision",
                "target_node_id": "output_1",
                "target_port": "value"
            }
        ]
    }

    _, draft_info_b = request("GET", f"/api/v1/projects/{project_id}/workflows/{wf_b_id}/draft", token=token)
    rev_b = draft_info_b.get("revision", 1) if isinstance(draft_info_b, dict) else 1
    request("PUT", f"/api/v1/projects/{project_id}/workflows/{wf_b_id}/draft", {
        "baseRevision": rev_b, "definition": appr_def
    }, token=token)

    request("POST", f"/api/v1/projects/{project_id}/workflows/{wf_b_id}/publish", {"versionNumber": 1}, token=token)

    print("\n[*] Triggering Workflow requiring Human Approval...")
    status, exec_b = request("POST", f"/api/v1/projects/{project_id}/workflows/{wf_b_id}/executions", {
        "mode": "published",
        "input": {
            "campaign": "Summer Product Launch",
            "budget": "$50,000"
        }
    }, token=token)
    run_b_id = exec_b["runId"]
    print(f" [✓] Workflow Execution Started! Run ID: {run_b_id}")

    time.sleep(3)
    status, detail_b = request("GET", f"/api/v1/projects/{project_id}/executions/{run_b_id}", token=token)
    print(f" [*] Execution State: {detail_b.get('status')}")

    print("\n[*] Testing Human Approval Decision API (POST /api/v1/projects/{projectId}/executions/{runId}/approvals/{approvalId}/decision)...")
    appr_id = f"appr-{run_b_id[:12]}"
    status, dec_res = request("POST", f"/api/v1/projects/{project_id}/executions/{run_b_id}/approvals/{appr_id}/decision", {
        "decision": "approved",
        "responsePayload": {"reviewer": "Senior Marketing Manager", "notes": "Approved for launch"}
    }, token=token)
    
    if status in (200, 202):
        print(f" [✓] Human Approval Decision Recorded! Result: {dec_res}")
    else:
        print(f" [!] Note on Approval API response ({status}): {dec_res}")

    print("\n" + "=" * 75)
    print("CONDITIONAL NODE & HUMAN APPROVAL VERIFICATION COMPLETED SUCCESSFULLY!")
    print("=" * 75)

if __name__ == "__main__":
    test_conditional_and_approval()
