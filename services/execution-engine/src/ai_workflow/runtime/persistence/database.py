from __future__ import annotations

from pathlib import Path

import asyncpg
from pgvector.asyncpg import register_vector

_MIGRATIONS_SCHEMA = "ee"
_MIGRATIONS_TABLE = "schema_migrations"

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


class DatabaseUrl:
    """Normalizes SQLAlchemy-style asyncpg URLs for the asyncpg driver."""

    def __init__(self, url: str) -> None:
        self._url = url

    def as_asyncpg(self) -> str:
        if self._url.startswith("postgresql+asyncpg://"):
            return "postgresql://" + self._url.removeprefix("postgresql+asyncpg://")
        return self._url


class SqlScript:
    """One SQL migration file body."""

    def __init__(self, *, name: str, body: str) -> None:
        self.name = name
        self.body = body

    def is_placeholder(self) -> bool:
        for line in self.body.splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("--"):
                return False
        return True


class ConnectionPool:
    """Creates asyncpg pools with optional pgvector connection init."""

    @staticmethod
    async def _init_connection(conn: asyncpg.Connection) -> None:
        try:
            await register_vector(conn)
        except Exception:  # noqa: BLE001 - vector extension may be absent in some test DBs
            return

    @classmethod
    async def create(
        cls,
        database_url: str,
        *,
        min_size: int = 1,
        max_size: int = 10,
    ) -> asyncpg.Pool:
        return await asyncpg.create_pool(
            DatabaseUrl(database_url).as_asyncpg(),
            min_size=min_size,
            max_size=max_size,
            init=cls._init_connection,
        )


class SchemaMigrator:
    """Applies SQL files and tracks them in ee.schema_migrations."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool
        self._schema = _MIGRATIONS_SCHEMA
        self._table = _MIGRATIONS_TABLE
        self._repairs = _REPAIR_IF_MISSING

    async def ensure_table(self, conn: asyncpg.connection.Connection) -> None:
        await conn.execute(f"CREATE SCHEMA IF NOT EXISTS {self._schema}")
        await conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {self._schema}.{self._table} (
                filename TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )

    async def _unrecord_skipped_comment_prefix_migrations(
        self,
        conn: asyncpg.connection.Connection,
        existing: set[str],
    ) -> None:
        for filename, probe in self._repairs:
            if filename not in existing:
                continue
            present = await conn.fetchval(probe)
            if present is not None:
                continue
            await conn.execute(
                f"DELETE FROM {self._schema}.{self._table} WHERE filename = $1",
                filename,
            )
            existing.discard(filename)

    async def apply(self, sql_dir: Path) -> list[str]:
        if not sql_dir.is_dir():
            msg = f"SQL directory does not exist: {sql_dir}"
            raise FileNotFoundError(msg)

        applied: list[str] = []
        sql_files = sorted(path for path in sql_dir.glob("*.sql") if path.is_file())

        async with self._pool.acquire() as conn:
            await self.ensure_table(conn)  # type: ignore[arg-type]
            existing = {
                row["filename"]
                for row in await conn.fetch(
                    f"SELECT filename FROM {self._schema}.{self._table}"
                )
            }
            await self._unrecord_skipped_comment_prefix_migrations(conn, existing)

            for sql_file in sql_files:
                if sql_file.name in existing:
                    continue
                script = SqlScript(
                    name=sql_file.name,
                    body=sql_file.read_text(encoding="utf-8").strip(),
                )
                if script.is_placeholder():
                    await conn.execute(
                        f"INSERT INTO {self._schema}.{self._table} (filename) VALUES ($1)",
                        script.name,
                    )
                    applied.append(script.name)
                    continue
                async with conn.transaction():
                    await conn.execute(script.body)
                    await conn.execute(
                        f"INSERT INTO {self._schema}.{self._table} (filename) VALUES ($1)",
                        script.name,
                    )
                applied.append(script.name)

        return applied


def normalize_database_url(database_url: str) -> str:
    """Convert SQLAlchemy-style asyncpg URLs to plain PostgreSQL URLs."""
    return DatabaseUrl(database_url).as_asyncpg()


def sql_is_placeholder(sql: str) -> bool:
    """True when the file has no executable SQL (empty or comment-only)."""
    return SqlScript(name="", body=sql).is_placeholder()


async def create_pool(
    database_url: str, *, min_size: int = 1, max_size: int = 10
) -> asyncpg.Pool:
    """Create an asyncpg connection pool for the execution engine database."""
    return await ConnectionPool.create(database_url, min_size=min_size, max_size=max_size)


async def run_migrations(pool: asyncpg.Pool, sql_dir: Path) -> list[str]:
    """Apply any pending SQL migration files and return the filenames applied."""
    return await SchemaMigrator(pool).apply(sql_dir)
