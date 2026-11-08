"""Database engine and session management."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings, get_settings


def make_async_url(url: str) -> str:
    """Normalize a postgresql:// URL to postgresql+asyncpg:// for async SQLAlchemy."""
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    return url


def make_sync_url(url: str) -> str:
    """Normalize a postgresql+asyncpg:// URL to postgresql:// for sync engine/Alembic."""
    if url.startswith("postgresql+asyncpg://"):
        return url.replace("postgresql+asyncpg://", "postgresql://", 1)
    return url


def get_sync_engine(url: str | None = None) -> Engine:
    settings = get_settings()
    target_url = make_sync_url(url or settings.database_url)
    return create_engine(target_url, echo=False, pool_pre_ping=True)


def get_async_engine(url: str | None = None) -> AsyncEngine:
    settings = get_settings()
    target_url = make_async_url(url or settings.database_url)
    return create_async_engine(target_url, echo=False, pool_pre_ping=True)


@asynccontextmanager
async def get_db_session(
    settings: Settings | None = None,
) -> AsyncGenerator[AsyncSession, None]:
    s = settings or get_settings()
    engine = get_async_engine(s.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    await engine.dispose()


@lru_cache
def _session_factory() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_async_engine(), expire_on_commit=False)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: one pooled async session per request."""
    async with _session_factory()() as session:
        yield session
