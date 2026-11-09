"""Automated point-in-time restore utility for Project Intelligence (PI-053).

Supports:
1. Restoring private object storage from compressed .tar.gz archives.
2. Restoring PostgreSQL database from pg_dump custom/sql archives via pg_restore/psql.
"""

import argparse
import subprocess
import tarfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def restore_storage(archive_path: Path | str, destination_dir: Path | str) -> dict[str, Any]:
    """Extract a private storage .tar.gz archive into a destination directory."""
    arc = Path(archive_path)
    dest = Path(destination_dir)

    if not arc.exists():
        raise FileNotFoundError(f"Backup archive '{arc}' does not exist.")

    dest.mkdir(parents=True, exist_ok=True)

    restored_count = 0
    with tarfile.open(arc, "r:gz") as tar:
        # Filter for safe extraction preventing directory traversal
        for member in tar.getmembers():
            # Basic path traversal guard
            if member.name.startswith("/") or ".." in member.name:
                continue
            tar.extract(member, path=dest)
            if member.isfile():
                restored_count += 1

    return {
        "status": "success",
        "destination_dir": str(dest),
        "restored_files_count": restored_count,
        "timestamp": datetime.now(UTC).isoformat(),
    }


def restore_postgres(
    db_url: str,
    backup_file: Path | str,
    pg_restore_path: str = "pg_restore",
    clean: bool = True,
) -> dict[str, Any]:
    """Execute pg_restore to restore a custom-format (.dump) database backup."""
    inp = Path(backup_file)
    if not inp.exists():
        raise FileNotFoundError(f"Backup file '{inp}' does not exist.")

    cmd = [
        pg_restore_path,
        "--dbname",
        db_url,
        "--no-owner",
        "--no-privileges",
    ]
    if clean:
        cmd.append("--clean")
        cmd.append("--if-exists")

    cmd.append(str(inp))

    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)  # noqa: S603
        return {
            "status": "success",
            "backup_file": str(inp),
            "timestamp": datetime.now(UTC).isoformat(),
        }
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        return {
            "status": "failed",
            "error": str(exc),
            "timestamp": datetime.now(UTC).isoformat(),
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="Project Intelligence Restore CLI")
    parser.add_argument("--storage-archive", type=str, help="Path to storage .tar.gz archive")
    parser.add_argument("--storage-dest", type=str, help="Path to destination storage directory")
    parser.add_argument("--db-url", type=str, help="PostgreSQL connection string")
    parser.add_argument("--db-backup", type=str, help="Path to database .dump file")

    args = parser.parse_args()

    if args.storage_archive and args.storage_dest:
        res = restore_storage(args.storage_archive, args.storage_dest)
        print(f"Storage restored: {res['restored_files_count']} files to {res['destination_dir']}")

    if args.db_url and args.db_backup:
        res = restore_postgres(args.db_url, args.db_backup)
        print(f"Database restore: status={res['status']}")


if __name__ == "__main__":
    main()
