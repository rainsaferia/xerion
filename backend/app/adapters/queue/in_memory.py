"""In-memory async queue adapter for local development and tests (PI-013)."""

import asyncio
import uuid


class InMemoryQueueAdapter:
    """In-memory queue adapter using asyncio.Queue."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[uuid.UUID] = asyncio.Queue()

    async def enqueue_import_job(self, job_id: uuid.UUID) -> None:
        """Enqueue job id."""
        await self._queue.put(job_id)

    async def dequeue_import_job(self, timeout_seconds: float = 1.0) -> uuid.UUID | None:
        """Dequeue next job id with timeout."""
        try:
            return await asyncio.wait_for(self._queue.get(), timeout=timeout_seconds)
        except TimeoutError:
            return None

    def qsize(self) -> int:
        return self._queue.qsize()
