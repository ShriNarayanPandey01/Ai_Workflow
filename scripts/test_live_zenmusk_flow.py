#!/usr/bin/env python3
import json
import sys
import time
import urllib.request
import urllib.error

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

BASE_URL = "http://localhost:8080"

def make_request(method, path, data=None, token=None):
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
        print(f"[X] HTTP Error {e.code} on {method} {path}: {err_json}")
        return e.code, err_json

def test_zenmusk_image_flow():
    print("=== Testing Live ZenMusk Image Generation Workflow ===")
    email = f"user_{int(time.time())}@example.com"
    password = "SecretPassword123!"

    status, reg_res = make_request("POST", "/api/v1/auth/register", {
        "email": email, "password": password, "fullName": "ZenMusk Tester"
    })
    token = reg_res["accessToken"]

    status, ws_res = make_request("GET", "/api/v1/projects/workspaces", token=token)
    workspace_id = ws_res[0]["id"]

    status, proj_res = make_request("GET", f"/api/v1/projects?workspaceId={workspace_id}", token=token)
    if status == 200 and proj_res:
        project_id = proj_res[0]["id"]
    else:
        status, new_proj = make_request("POST", "/api/v1/projects", {
            "workspaceId": workspace_id, "name": "Image Project", "description": "Image Gen"
        }, token=token)
        project_id = new_proj["id"]

    status, wf_res = make_request("POST", f"/api/v1/projects/{project_id}/workflows", {
        "name": "Live ZenMusk Workflow", "description": "ZenMusk test"
    }, token=token)
    workflow_id = wf_res["id"]

    draft_def = {
        "schema_version": "1.0",
        "workflow_id": workflow_id,
        "name": "Live ZenMusk Workflow",
        "nodes": [
            {"id": "input_1", "type": "data.input@1", "config": {"message": "A futuristic neon cyberpunk lion"}},
            {"id": "image_gen_1", "type": "ai.image-generator@1", "config": {"provider": "zenmusk", "model": "google/gemini-3.1-flash-image"}},
            {"id": "output_1", "type": "data.output@1", "config": {}}
        ],
        "edges": [
            {"id": "e1", "source_node_id": "input_1", "source_port": "value", "target_node_id": "image_gen_1", "target_port": "prompt"},
            {"id": "e2", "source_node_id": "image_gen_1", "source_port": "image_url", "target_node_id": "output_1", "target_port": "value"}
        ]
    }

    make_request("PUT", f"/api/v1/projects/{project_id}/workflows/{workflow_id}/draft", {
        "baseRevision": 1, "definition": draft_def
    }, token=token)

    status, exec_res = make_request("POST", f"/api/v1/projects/{project_id}/workflows/{workflow_id}/executions?workflowId={workflow_id}", {
        "mode": "draft",
        "input": {"message": "A futuristic neon cyberpunk lion", "prompt": "A futuristic neon cyberpunk lion"}
    }, token=token)

    run_id = exec_res["runId"]
    print(f"Triggered Execution! Run ID: {run_id}")

    print("Polling execution status...")
    for _ in range(25):
        time.sleep(1.5)
        status, detail = make_request("GET", f"/api/v1/projects/{project_id}/executions/{run_id}", token=token)
        exec_status = detail.get("status")
        print(f"Current Run Status: {exec_status}")
        if exec_status in ("SUCCEEDED", "FAILED"):
            print(f"Final Status: {exec_status}")
            print(f"Output: {json.dumps(detail.get('output'), indent=2)}")
            if detail.get("error"):
                print(f"Error: {json.dumps(detail.get('error'), indent=2)}")
            break

if __name__ == "__main__":
    test_zenmusk_image_flow()
