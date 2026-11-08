"""Background queue adapter package (PI-013)."""

from functools import lru_cache

from app.adapters.queue.base import QueueAdapter
from app.adapters.queue.in_memory import InMemoryQueueAdapter
from app.adapters.queue.redis_queue import RedisQueueAdapter
from app.core.config import Settings, get_settings


@lru_cache
def _get_in_memory_adapter() -> InMemoryQueueAdapter:
    return InMemoryQueueAdapter()


@lru_cache
def _get_redis_adapter(redis_url: str) -> RedisQueueAdapter:
    return RedisQueueAdapter(redis_url=redis_url)


def get_queue_adapter(settings: Settings | None = None) -> QueueAdapter:
    """Return the configured queue adapter."""
    s = settings or get_settings()
    if s.queue_backend == "redis":
        return _get_redis_adapter(s.redis_url)
    return _get_in_memory_adapter()


__all__ = ["InMemoryQueueAdapter", "QueueAdapter", "RedisQueueAdapter", "get_queue_adapter"]
