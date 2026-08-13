from __future__ import annotations

from pathlib import Path

import asyncpg
from pgvector.asyncpg import register_vector

MIGRATIONS_SCHEMA = "ee"
MIGRATIONS_TABLE = "schema_migrations"

# Recorded as applied by the old "file starts with --" skipper, but may never
# have executed. Re-open them when the expected object is missing.
_REPAIR_IF_MISSING: tuple[tuple[str, str], ...] = (
    (
        "004_action_key_scope.sql",
        """
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'ee'
          AND table_name = 'action_execution_keys'
          AND column_name = 'action_key'
        """,
    ),
    (
        "006_definitions_leases_tasks.sql",
        "SELECT to_regclass('ee.workflow_definitions')",
    ),
)


def normalize_database_url(database_url: str) -> str:
    """Convert SQLAlchemy-style asyncpg URLs to plain PostgreSQL URLs."""
    if database_url.startswith("postgresql+asyncpg://"):
        return "postgresql://" + database_url.removeprefix("postgresql+asyncpg://")
    return database_url


def sql_is_placeholder(sql: str) -> bool:
    """True when the file has no executable SQL (empty or comment-only)."""
    for line in sql.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("--"):
            return False
    return True


async def _init_connection(conn: asyncpg.Connection) -> None:
    try:
        await register_vector(conn)
    except Exception:  # noqa: BLE001 - vector extension may be absent in some test DBs
        return


async def create_pool(database_url: str, *, min_size: int = 1, max_size: int = 10) -> asyncpg.Pool:
    """Create an asyncpg connection pool for the execution engine database."""
    return await asyncpg.create_pool(
        normalize_database_url(database_url),
        min_size=min_size,
        max_size=max_size,
        init=_init_connection,
    )


async def ensure_migrations_table(conn: asyncpg.connection.Connection) -> None:
    """Ensure the schema migrations tracking table exists."""
    await conn.execute(f"CREATE SCHEMA IF NOT EXISTS {MIGRATIONS_SCHEMA}")
    await conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {MIGRATIONS_SCHEMA}.{MIGRATIONS_TABLE} (
            filename TEXT PRIMARY KEY,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )


async def _unrecord_skipped_comment_prefix_migrations(
    conn: asyncpg.connection.Connection,
    existing: set[str],
) -> None:
    """Drop bogus schema_migrations rows left by the comment-prefix skipper."""
    for filename, probe in _REPAIR_IF_MISSING:
        if filename not in existing:
            continue
        present = await conn.fetchval(probe)
        if present is not None:
            continue
        await conn.execute(
            f"DELETE FROM {MIGRATIONS_SCHEMA}.{MIGRATIONS_TABLE} WHERE filename = $1",
            filename,
        )
        existing.discard(filename)


async def run_migrations(pool: asyncpg.Pool, sql_dir: Path) -> list[str]:
    """Apply any pending SQL migration files and return the filenames applied."""
    if not sql_dir.is_dir():
        msg = f"SQL directory does not exist: {sql_dir}"
        raise FileNotFoundError(msg)

    applied: list[str] = []
    sql_files = sorted(path for path in sql_dir.glob("*.sql") if path.is_file())

    async with pool.acquire() as conn:
        await ensure_migrations_table(conn)  # type: ignore[arg-type]
        existing = {
            row["filename"]
            for row in await conn.fetch(
                f"SELECT filename FROM {MIGRATIONS_SCHEMA}.{MIGRATIONS_TABLE}"
            )
        }
        await _unrecord_skipped_comment_prefix_migrations(conn, existing)

        for sql_file in sql_files:
            if sql_file.name in existing:
                continue
            sql = sql_file.read_text(encoding="utf-8").strip()
            if sql_is_placeholder(sql):
                await conn.execute(
                    f"INSERT INTO {MIGRATIONS_SCHEMA}.{MIGRATIONS_TABLE} (filename) VALUES ($1)",
                    sql_file.name,
                )
                applied.append(sql_file.name)
                continue
            async with conn.transaction():
                await conn.execute(sql)
                await conn.execute(
                    f"INSERT INTO {MIGRATIONS_SCHEMA}.{MIGRATIONS_TABLE} (filename) VALUES ($1)",
                    sql_file.name,
                )
            applied.append(sql_file.name)

    return applied
