from __future__ import annotations

from ai_workflow.runtime.persistence.database import sql_is_placeholder


def test_sql_is_placeholder_comment_only() -> None:
    assert sql_is_placeholder("-- Placeholder schema file.\n")
    assert sql_is_placeholder("")


def test_sql_is_placeholder_false_when_comment_then_ddl() -> None:
    assert not sql_is_placeholder(
        "-- Durable definition store.\n\nCREATE TABLE IF NOT EXISTS ee.workflow_definitions (\n"
        "    definition_hash TEXT PRIMARY KEY\n);\n"
    )
