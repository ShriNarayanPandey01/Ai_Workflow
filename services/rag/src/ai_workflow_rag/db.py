from __future__ import annotations

from pathlib import Path

import asyncpg
from pgvector.asyncpg import register_vector

MIGRATIONS_SCHEMA = "rag"
MIGRATIONS_TABLE = "schema_migrations"


def normalize_database_url(database_url: str) -> str:
    if database_url.startswith("postgresql+asyncpg://"):
        return "postgresql://" + database_url.removeprefix("postgresql+asyncpg://")
    return database_url


async def _init_connection(conn: asyncpg.Connection) -> None:
    try:
        await register_vector(conn)
    except Exception:
        return


async def create_pool(database_url: str, *, min_size: int = 1, max_size: int = 10) -> asyncpg.Pool:
    return await asyncpg.create_pool(
        normalize_database_url(database_url),
        min_size=min_size,
        max_size=max_size,
        init=_init_connection,
    )


async def ensure_migrations_table(conn: asyncpg.Connection) -> None:
    await conn.execute(f"CREATE SCHEMA IF NOT EXISTS {MIGRATIONS_SCHEMA}")
    await conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {MIGRATIONS_SCHEMA}.{MIGRATIONS_TABLE} (
            filename TEXT PRIMARY KEY,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )


async def run_migrations(pool: asyncpg.Pool, sql_dir: Path) -> list[str]:
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

        for sql_file in sql_files:
            if sql_file.name in existing:
                continue
            sql = sql_file.read_text(encoding="utf-8").strip()
            if not sql or sql.startswith("--"):
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
