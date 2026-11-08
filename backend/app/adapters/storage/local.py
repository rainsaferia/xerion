"""Local filesystem private object storage adapter (PI-012).

Implements StorageAdapter protocol using private local directory storage with
strict path traversal protection and secure directory creation.
"""

from pathlib import Path


class LocalStorageAdapter:
    """Stores objects privately on the local filesystem."""

    def __init__(self, base_dir: Path | str) -> None:
        self.base_dir = Path(base_dir).resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _resolve_path(self, object_key: str) -> Path:
        """Resolve object_key into a local filesystem path, preventing directory traversal."""
        # Normalize and remove leading slashes
        clean_key = object_key.strip().lstrip("/\\")
        target = (self.base_dir / clean_key).resolve()

        # Strict sandbox boundary: target must be inside base_dir
        if not target.is_relative_to(self.base_dir):
            raise ValueError(f"Path traversal detected for key '{object_key}'.")
        return target

    async def put_object(
        self, object_key: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> None:
        """Store bytes privately at object_key."""
        path = self._resolve_path(object_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    async def get_object(self, object_key: str) -> bytes:
        """Retrieve bytes by object_key."""
        path = self._resolve_path(object_key)
        if not path.is_file():
            raise FileNotFoundError(f"Object '{object_key}' not found.")
        return path.read_bytes()

    async def delete_object(self, object_key: str) -> bool:
        """Delete object by object_key."""
        path = self._resolve_path(object_key)
        if path.is_file():
            path.unlink()
            return True
        return False

    async def exists(self, object_key: str) -> bool:
        """Check whether object exists."""
        path = self._resolve_path(object_key)
        return path.is_file()

    def get_object_size(self, object_key: str) -> int:
        """Return size of object in bytes."""
        path = self._resolve_path(object_key)
        if not path.is_file():
            raise FileNotFoundError(f"Object '{object_key}' not found.")
        return path.stat().st_size
