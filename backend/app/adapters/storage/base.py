"""Private object storage adapter protocol (PI-012).

Rules (02_SYSTEM_ARCHITECTURE.md Section 10):
- Store source files and reports in private buckets.
- Use opaque object keys; never expose raw bucket paths or local absolute paths.
- Public access to objects is denied.
"""

from typing import Protocol


class StorageAdapter(Protocol):
    """Protocol for private object storage."""

    async def put_object(
        self, object_key: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> None:
        """Store bytes privately at object_key."""
        ...

    async def get_object(self, object_key: str) -> bytes:
        """Retrieve private bytes by object_key. Raises FileNotFoundError if missing."""
        ...

    async def delete_object(self, object_key: str) -> bool:
        """Delete private object by object_key. Returns True if deleted, False if not found."""
        ...

    async def exists(self, object_key: str) -> bool:
        """Check whether private object exists."""
        ...

    def get_object_size(self, object_key: str) -> int:
        """Return size in bytes. Raises FileNotFoundError if missing."""
        ...
