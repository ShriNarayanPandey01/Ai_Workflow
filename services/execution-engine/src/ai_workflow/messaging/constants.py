from __future__ import annotations

COMMANDS_EXCHANGE = "aiw.commands.v1"
EVENTS_EXCHANGE = "aiw.events.v1"
DEAD_LETTER_EXCHANGE = "aiw.dead.v1"

EXECUTION_COMMANDS_QUEUE = "aiw.execution.commands.v1"
CONTROL_EVENTS_QUEUE = "aiw.control.events.v1"

EXECUTION_START_ROUTING_KEY = "execution.start.v1"
EXECUTION_RESUME_ROUTING_KEY = "execution.resume.v1"
EXECUTION_CANCEL_ROUTING_KEY = "execution.cancel.v1"
EXECUTION_STARTED_ROUTING_KEY = "execution.started.v1"
EXECUTION_WAITING_ROUTING_KEY = "execution.waiting.v1"
EXECUTION_COMPLETED_ROUTING_KEY = "execution.completed.v1"
EXECUTION_FAILED_ROUTING_KEY = "execution.failed.v1"
EXECUTION_CANCELLED_ROUTING_KEY = "execution.cancelled.v1"
NODE_STARTED_ROUTING_KEY = "node.started.v1"
NODE_COMPLETED_ROUTING_KEY = "node.completed.v1"
NODE_FAILED_ROUTING_KEY = "node.failed.v1"

TASK_COMMANDS_QUEUE = "aiw.task.commands.v1"
TASK_RESULTS_QUEUE = "aiw.task.results.v1"
DEAD_LETTER_QUEUE = "aiw.dead.q.v1"

TASK_START_ROUTING_KEY = "task.start.v1"
TASK_CANCEL_ROUTING_KEY = "task.cancel.v1"
TASK_COMPLETED_ROUTING_KEY = "task.completed.v1"
TASK_FAILED_ROUTING_KEY = "task.failed.v1"
TASK_PROGRESS_ROUTING_KEY = "task.progress.v1"

EXECUTION_COMMANDS_BINDING = "execution.*.v1"
TASK_COMMANDS_BINDING = "task.*.v1"
CONTROL_EVENTS_BINDING = "#"
DEAD_LETTER_BINDING = "#"
