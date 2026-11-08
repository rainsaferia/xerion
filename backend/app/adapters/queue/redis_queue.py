"""Redis queue adapter for production background workers (PI-013)."""

import uuid

from redis.asyncio import Redis

IMPORT_JOB_QUEUE_KEY = "pi:queue:import_jobs"


class RedisQueueAdapter:
    """Redis-backed queue adapter."""

    def __init__(self, redis_url: str) -> None:
        self.redis_url = redis_url
        self._client: Redis | None = None

    def _get_client(self) -> Redis:
        if self._client is None:
            self._client = Redis.from_url(self.redis_url, decode_responses=True)
        return self._client

    async def enqueue_import_job(self, job_id: uuid.UUID) -> None:
        """LPUSH job ID string to Redis list."""
        client = self._get_client()
        await client.lpush(IMPORT_JOB_QUEUE_KEY, str(job_id))

    async def dequeue_import_job(self, timeout_seconds: float = 1.0) -> uuid.UUID | None:
        """BRPOP next job ID from Redis list."""
        client = self._get_client()
        timeout = int(max(1, timeout_seconds))
        item = await client.brpop([IMPORT_JOB_QUEUE_KEY], timeout=timeout)
        if item:
            _, raw_val = item
            val_str = raw_val.decode("utf-8") if isinstance(raw_val, bytes) else str(raw_val)
            return uuid.UUID(val_str)
        return None

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
