"""
Async DB session management.

We use SQLAlchemy Core (not the ORM) for this project deliberately: the
agent pipeline stages read/write a small, stable set of tables via plain
SQL, and Core keeps the query text visible and easy to explain in a
design review — no hidden ORM-generated joins.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from app.config import get_settings

_engine: AsyncEngine | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.database_url,
            pool_pre_ping=True,   # avoids stale-connection errors after Supabase idles the pool
            pool_size=5,
            max_overflow=5,
            echo=False,
        )
    return _engine


@asynccontextmanager
async def get_connection() -> AsyncGenerator[AsyncConnection, None]:
    """
    Usage:
        async with get_connection() as conn:
            result = await conn.execute(text("select 1"))
    """
    engine = get_engine()
    async with engine.connect() as conn:
        yield conn


async def healthcheck() -> bool:
    """Used by the /health endpoint to confirm DB connectivity before serving traffic."""
    from sqlalchemy import text

    try:
        async with get_connection() as conn:
            await conn.execute(text("select 1"))
        return True
    except Exception:
        return False


async def dispose_engine() -> None:
    """Call on app shutdown to close the pool cleanly."""
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None
