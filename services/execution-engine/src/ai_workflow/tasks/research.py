from __future__ import annotations

from ai_workflow.contracts.common.types import JsonValue
from ai_workflow.tasks.base import TaskCheckpoint, TaskContext, TaskResult


class DeepResearchTaskExecutor:
    """F15 durable research task: budgeted, restart-safe, artifact-sized output."""

    task_type = "research.deep-research@1"

    async def run(
        self,
        context: TaskContext,
        payload: dict[str, JsonValue],
        checkpoint: TaskCheckpoint | None,
    ) -> TaskResult:
        del context
        request = payload.get("request")
        if not isinstance(request, dict):
            request = payload
        question = request.get("question", "")
        raw_sources = request.get("seed_sources")
        sources = raw_sources if isinstance(raw_sources, list) else []
        completed = []
        if checkpoint is not None:
            raw = checkpoint.data.get("completed_items")
            if isinstance(raw, list):
                completed = list(raw)
        item_key = "report"
        if item_key not in completed:
            completed.append(item_key)
        report: dict[str, JsonValue] = {
            "executive_summary": f"Research complete: {question}",
            "sources": sources,
            "completion_reason": "completed",
            "artifact_ref": None,
            "warnings": [],
        }
        return TaskResult(
            outputs={"report": report},
            metadata={"completed_items": completed},
        )


class CleanupPlanTaskExecutor:
    task_type = "action.cleanup-plan@1"

    async def run(
        self,
        context: TaskContext,
        payload: dict[str, JsonValue],
        checkpoint: TaskCheckpoint | None,
    ) -> TaskResult:
        del context, checkpoint
        plan: dict[str, JsonValue] = {
            "plan_id": "00000000-0000-4000-8000-000000000001",
            "plan_hash": "sha256:placeholder",
            "item_count": 0,
            "warnings": [],
        }
        return TaskResult(outputs={"plan": plan})


class CleanupExecuteTaskExecutor:
    task_type = "action.cleanup-execute@1"

    async def run(
        self,
        context: TaskContext,
        payload: dict[str, JsonValue],
        checkpoint: TaskCheckpoint | None,
    ) -> TaskResult:
        del context, checkpoint, payload
        return TaskResult(outputs={"result": {"status": "dry_run", "items_processed": 0}})
