"""
AML System — Database Layer (Production Clean)
==============================================
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings

log = logging.getLogger(__name__)
settings = get_settings()

# ─────────────────────────────────────────────
# ENGINE
# ─────────────────────────────────────────────

engine: AsyncEngine = create_async_engine(
    settings.database_url,
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

# ─────────────────────────────────────────────
# SESSION FACTORY
# ─────────────────────────────────────────────

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# ─────────────────────────────────────────────
# FASTAPI DEPENDENCY
# ─────────────────────────────────────────────

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency injection for FastAPI routes
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

# ─────────────────────────────────────────────
# CONTEXT MANAGER (workers/scripts)
# ─────────────────────────────────────────────

@asynccontextmanager
async def get_db_context() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

# ─────────────────────────────────────────────
# BASE MODEL
# ─────────────────────────────────────────────

class Base(DeclarativeBase):
    pass

# ─────────────────────────────────────────────
# HEALTH CHECK
# ─────────────────────────────────────────────

async def check_database_health() -> dict[str, str]:
    try:
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT 1"))
            _ = result.scalar()
        return {"status": "ok"}
    except Exception as exc:
        log.error("db_health_failed", error=str(exc))
        return {"status": "error", "detail": str(exc)}

# ─────────────────────────────────────────────
# RAW SQL (optional utility)
# ─────────────────────────────────────────────

async def execute_sql(sql: str, params: Optional[dict] = None):
    async with engine.connect() as conn:
        result = await conn.execute(text(sql), params or {})
        await conn.commit()

        if result.returns_rows:
            keys = result.keys()
            return [dict(zip(keys, row)) for row in result.fetchall()]
        return []