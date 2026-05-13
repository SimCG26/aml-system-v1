"""
AML System — Database Layer
============================
Provides:
  · Async SQLAlchemy engine (asyncpg driver)
  · Session factory with per-request lifecycle
  · Declarative base with reusable column mixins
  · Health-check helper used by /health/ready
  · Utility to run raw SQL (migrations, one-off scripts)

PostgreSQL-specific features used:
  · JSONB columns for schema-flexible metadata
  · UUID primary keys (uuid-ossp extension)
  · TIMESTAMPTZ for timezone-aware timestamps
  · Partitioned audit_logs (RANGE on created_at)
  · pg_trgm / unaccent for fuzzy name search
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, declared_attr
from sqlalchemy.pool import NullPool, AsyncAdaptedQueuePool

from app.config import get_settings

log = logging.getLogger(__name__)
settings = get_settings()


# ─────────────────────────────────────────────────────────────
# Engine
# ─────────────────────────────────────────────────────────────

def _build_engine() -> AsyncEngine:
    """
    Build the async SQLAlchemy engine.

    Pool strategy:
      · Production → AsyncAdaptedQueuePool (persistent connections, fast)
      · Test / Alembic migrations → NullPool (no persistent connections,
        avoids "event loop closed" errors in pytest-asyncio)
    """
    pool_class = (
        NullPool
        if settings.environment in ("test", "alembic")
        else AsyncAdaptedQueuePool
    )

    engine_kwargs: dict = dict(
        url=settings.database_url,
        echo=settings.debug,
        pool_pre_ping=True,
        pool_recycle=3600,
        connect_args={
            "server_settings": {
                "application_name": "aml_system",
                "timezone": "UTC",
            },
            "command_timeout": 30,
        },
    )

    if pool_class is not NullPool:
        engine_kwargs["poolclass"] = pool_class
        engine_kwargs["pool_size"] = settings.db_pool_size
        engine_kwargs["max_overflow"] = settings.db_max_overflow
        engine_kwargs["pool_timeout"] = 10
    else:
        engine_kwargs["poolclass"] = pool_class

    eng = create_async_engine(**engine_kwargs)

    if settings.debug:
        @event.listens_for(eng.sync_engine, "before_cursor_execute")
        def _before(conn, cursor, statement, parameters, context, executemany):
            import time
            context._query_start_time = time.monotonic()

        @event.listens_for(eng.sync_engine, "after_cursor_execute")
        def _after(conn, cursor, statement, parameters, context, executemany):
            import time
            elapsed = time.monotonic() - context._query_start_time
            if elapsed >= 0.5:
                log.warning("slow_query detected=%.3fs sql=%s", elapsed, statement[:120])

    return eng


engine: AsyncEngine = _build_engine()


# ─────────────────────────────────────────────────────────────
# Session factory
# ─────────────────────────────────────────────────────────────

AsyncSessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=True,
    autocommit=False,
)


# ─────────────────────────────────────────────────────────────
# FastAPI dependency — yields a per-request session
# ─────────────────────────────────────────────────────────────

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency.  Use as:

        @router.get("/")
        async def handler(db: AsyncSession = Depends(get_db)):
            ...

    Guarantees:
      · Session is committed if no exception occurred
      · Session is rolled back on any exception
      · Session is always closed (connection returned to pool)
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# ─────────────────────────────────────────────────────────────
# Context-manager variant (for Celery tasks / scripts)
# ─────────────────────────────────────────────────────────────

@asynccontextmanager
async def get_db_context() -> AsyncGenerator[AsyncSession, None]:
    """
    Use inside async context managers (Celery tasks, seed scripts, etc.)

        async with get_db_context() as db:
            result = await db.execute(select(Customer))
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# ─────────────────────────────────────────────────────────────
# Declarative Base
# ─────────────────────────────────────────────────────────────

class Base(DeclarativeBase):
    """
    All ORM models inherit from this base.
    """

    def __repr__(self) -> str:
        pk_cols = [c.name for c in self.__table__.primary_key.columns]
        pk_vals = {c: getattr(self, c, "?") for c in pk_cols}
        return f"<{self.__class__.__name__} {pk_vals}>"

    def to_dict(self, exclude: set[str] | None = None) -> dict:
        """
        Serialize ORM object to a plain dict.
        Useful for audit logging (before/after state).
        """
        exclude = exclude or set()
        result = {}
        for col in self.__table__.columns:
            if col.name in exclude:
                continue
            val = getattr(self, col.name, None)
            if hasattr(val, "isoformat"):
                val = val.isoformat()
            elif hasattr(val, "value"):
                val = val.value
            result[col.name] = val
        return result


# ─────────────────────────────────────────────────────────────
# Health check
# ─────────────────────────────────────────────────────────────

async def check_database_health() -> dict[str, str]:
    """
    Verify the database is reachable and responsive.
    Called by GET /health/ready.
    """
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text("SELECT version(), NOW() AT TIME ZONE 'UTC'")
            )
            row = result.one()
            pg_version = row[0].split(" ")[1]
            server_time = row[1].isoformat()
        return {
            "status": "ok",
            "pg_version": pg_version,
            "server_utc": server_time,
        }
    except Exception as exc:
        log.error("database_health_check_failed error=%s", exc)
        return {"status": "error", "detail": str(exc)}


# ─────────────────────────────────────────────────────────────
# Raw SQL execution helper
# ─────────────────────────────────────────────────────────────

async def execute_sql(
    sql: str,
    params: Optional[dict] = None,
    *,
    conn: Optional[AsyncConnection] = None,
) -> list[dict]:
    """
    Execute raw SQL and return rows as a list of dicts.

        rows = await execute_sql(
            "SELECT id, risk_score FROM customers WHERE is_pep = :pep",
            {"pep": True}
        )
    """
    async def _run(connection: AsyncConnection) -> list[dict]:
        stmt = text(sql)
        result = await connection.execute(stmt, params or {})
        if result.returns_rows:
            keys = list(result.keys())
            return [dict(zip(keys, row)) for row in result.fetchall()]
        return []

    if conn is not None:
        return await _run(conn)

    async with engine.connect() as connection:
        rows = await _run(connection)
        await connection.commit()
        return rows


# ─────────────────────────────────────────────────────────────
# Teardown
# ─────────────────────────────────────────────────────────────

async def close_engine() -> None:
    """
    Dispose the connection pool gracefully.
    Called in FastAPI lifespan shutdown hook.
    """
    await engine.dispose()
    log.info("database_engine_disposed")