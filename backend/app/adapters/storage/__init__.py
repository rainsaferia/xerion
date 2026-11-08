"""Private object storage adapter package (PI-012)."""

from functools import lru_cache

from app.adapters.storage.base import StorageAdapter
from app.adapters.storage.local import LocalStorageAdapter
from app.core.config import Settings, get_settings


@lru_cache
def _get_local_adapter(base_dir: str) -> StorageAdapter:
    return LocalStorageAdapter(base_dir=base_dir)


def get_storage_adapter(settings: Settings | None = None) -> StorageAdapter:
    """Return the configured private storage adapter."""
    s = settings or get_settings()
    return _get_local_adapter(s.storage_local_dir)


__all__ = ["LocalStorageAdapter", "StorageAdapter", "get_storage_adapter"]
