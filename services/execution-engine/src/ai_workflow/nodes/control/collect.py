from __future__ import annotations

from ai_workflow.contracts.common.types import JsonValue
from ai_workflow.nodes.base import ExecutionContext, NodeResult
from ai_workflow.runtime.persistence.artifact_store import (
    ArtifactStore,
    InMemoryArtifactStore,
    payload_size_bytes,
)


class CollectNodeExecutor:
    node_type = "control.collect@1"

    def __init__(self, *, artifact_store: ArtifactStore | None = None) -> None:
        self._artifact_store = artifact_store or InMemoryArtifactStore()

    async def execute(
        self,
        context: ExecutionContext,
        config: dict[str, JsonValue],
        inputs: dict[str, JsonValue],
    ) -> NodeResult:
        del context
        ordering = config.get("ordering")
        if ordering not in {"preserve_input", "completion_order"}:
            msg = "control.collect@1 requires ordering preserve_input or completion_order"
            raise ValueError(msg)

        threshold = config.get("artifact_threshold_bytes")
        if not isinstance(threshold, int) or threshold < 0:
            msg = "control.collect@1 requires artifact_threshold_bytes >= 0"
            raise ValueError(msg)

        raw_items = inputs.get("items")
        if raw_items is None:
            msg = "control.collect@1 requires input port 'items'"
            raise ValueError(msg)
        if not isinstance(raw_items, list):
            msg = "control.collect@1 items input must be a list"
            raise ValueError(msg)

        entries: list[dict[str, JsonValue]] = []
        for entry in raw_items:
            if not isinstance(entry, dict):
                msg = "Each collect item must be an object"
                raise ValueError(msg)
            entries.append(entry)

        if ordering == "preserve_input":
            entries.sort(key=lambda row: int(row.get("index", 0)))
        else:
            entries.sort(key=lambda row: int(row.get("completion_seq", 0)))

        successes: list[JsonValue] = []
        failures: list[JsonValue] = []
        skipped: list[JsonValue] = []

        for entry in entries:
            status = entry.get("status")
            row = {
                "item_key": entry.get("item_key"),
                "index": entry.get("index"),
            }
            if status == "success":
                if "value" in entry:
                    row["value"] = entry["value"]
                successes.append(row)
            elif status == "failure":
                if "error" in entry:
                    row["error"] = entry["error"]
                failures.append(row)
            elif status == "skipped":
                if "reason" in entry:
                    row["reason"] = entry["reason"]
                skipped.append(row)
            else:
                msg = f"Invalid collect item status: {status!r}"
                raise ValueError(msg)

        summary: dict[str, JsonValue] = {
            "total": len(entries),
            "completed": len(successes),
            "failed": len(failures),
            "skipped": len(skipped),
        }

        result: dict[str, JsonValue] = {
            "summary": summary,
            "successes": successes,
            "failures": failures,
            "skipped": skipped,
            "artifact_ref": None,
        }

        if payload_size_bytes(result) > threshold:
            artifact_ref = self._artifact_store.put(result)
            compact: dict[str, JsonValue] = {
                "summary": summary,
                "successes": [],
                "failures": [],
                "skipped": [],
                "artifact_ref": artifact_ref,
            }
            return NodeResult(outputs={"result": compact})

        return NodeResult(outputs={"result": result})
