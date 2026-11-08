"""Queue adapter protocol (PI-013).

Rules (02_SYSTEM_ARCHITECTURE.md Section 3):
- Providers and queues are adapters. Domain services do not depend directly on queue technology.
"""

import uuid
from typing import Protocol


class QueueAdapter(Protocol):
    """Protocol for background job queuing."""

    async def enqueue_import_job(self, job_id: uuid.UUID) -> None:
        """Enqueue an import job ID for processing."""
        ...

    async def dequeue_import_job(self, timeout_seconds: float = 1.0) -> uuid.UUID | None:
        """Dequeue an import job ID for worker processing."""
        ...
