"""Dependency probes used by the readiness endpoint. They return only status, never secrets."""

import asyncio
from collections.abc import Awaitable, Callable

import asyncpg
import redis.asyncio as aioredis

from app.core.config import Settings

Probe = Callable[[Settings], Awaitable[None]]


async def check_postgres(settings: Settings) -> None:
    conn = await asyncpg.connect(
        settings.database_url, timeout=settings.health_check_timeout_seconds
    )
    try:
        await conn.fetchval("SELECT 1")
    finally:
        await conn.close()


async def check_redis(settings: Settings) -> None:
    client = aioredis.from_url(
        settings.redis_url,
        socket_connect_timeout=settings.health_check_timeout_seconds,
        socket_timeout=settings.health_check_timeout_seconds,
    )
    try:
        await client.ping()
    finally:
        await client.aclose()


async def run_probe(name: str, probe: Probe, settings: Settings) -> tuple[str, bool]:
    try:
        await asyncio.wait_for(probe(settings), timeout=settings.health_check_timeout_seconds + 1)
    except Exception:
        return name, False
    return name, True
