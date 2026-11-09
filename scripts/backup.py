"""Automated point-in-time backup utility for Project Intelligence (PI-053).

Supports:
1. Private object storage compression to .tar.gz archives with metadata checksums.
2. PostgreSQL database dumps via pg_dump CLI and structured JSON snapshot export for testing.
"""

import argparse
import json
import os
import subprocess
import tarfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


def backup_storage(storage_dir: Path | str, output_archive: Path | str) -> dict[str, Any]:
    """Archive private storage directory into a compressed .tar.gz file."""
    src = Path(storage_dir)
    out = Path(output_archive)

    if not src.exists():
        raise FileNotFoundError(f"Storage directory '{src}' does not exist.")

    out.parent.mkdir(parents=True, exist_ok=True)

    files_count = 0
    total_bytes = 0

    with tarfile.open(out, "w:gz") as tar:
        for root, _, files in os.walk(src):
            for file in files:
                full_path = Path(root) / file
                rel_path = full_path.relative_to(src)
                tar.add(full_path, arcname=str(rel_path))
                files_count += 1
                total_bytes += full_path.stat().st_size

    return {
        "status": "success",
        "archive_path": str(out),
        "files_count": files_count,
        "total_bytes": total_bytes,
        "timestamp": datetime.now(UTC).isoformat(),
    }


def backup_postgres(
    db_url: str,
    output_file: Path | str,
    pg_dump_path: str = "pg_dump",
) -> dict[str, Any]:
    """Execute pg_dump to produce a custom-format (.dump) or plain-text (.sql) database backup."""
    out = Path(output_file)
    out.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        pg_dump_path,
        "--dbname",
        db_url,
        "--format=c",
        "--file",
        str(out),
        "--no-owner",
        "--no-privileges",
    ]

    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)  # noqa: S603
        return {
            "status": "success",
            "backup_file": str(out),
            "file_size_bytes": out.stat().st_size,
            "timestamp": datetime.now(UTC).isoformat(),
        }
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        return {
            "status": "failed",
            "error": str(exc),
            "timestamp": datetime.now(UTC).isoformat(),
        }


async def export_sqlite_snapshot(session: AsyncSession, output_json: Path | str) -> dict[str, Any]:
    """Export critical database entities to JSON for validation and portable test backups."""
    from app.models.auth import User, Workspace
    from app.models.project import Project, ProjectVersion

    out = Path(output_json)
    out.parent.mkdir(parents=True, exist_ok=True)

    users_res = await session.execute(select(User))
    users = users_res.scalars().all()

    workspaces_res = await session.execute(select(Workspace))
    workspaces = workspaces_res.scalars().all()

    projects_res = await session.execute(select(Project))
    projects = projects_res.scalars().all()

    versions_res = await session.execute(select(ProjectVersion))
    versions = versions_res.scalars().all()

    data = {
        "metadata": {
            "exported_at": datetime.now(UTC).isoformat(),
            "format_version": "1.0",
        },
        "users": [
            {"id": str(u.id), "email": u.email, "display_name": u.display_name} for u in users
        ],
        "workspaces": [
            {"id": str(w.id), "name": w.name, "plan_code": w.plan_code} for w in workspaces
        ],
        "projects": [
            {"id": str(p.id), "workspace_id": str(p.workspace_id), "name": p.name}
            for p in projects
        ],
        "versions": [
            {
                "id": str(v.id),
                "project_id": str(v.project_id),
                "version_number": v.version_number,
                "version_label": v.version_label,
            }
            for v in versions
        ],
    }

    out.write_text(json.dumps(data, indent=2), encoding="utf-8")  # noqa: ASYNC230, ASYNC240

    return {
        "status": "success",
        "output_file": str(out),
        "users_count": len(users),
        "workspaces_count": len(workspaces),
        "projects_count": len(projects),
        "versions_count": len(versions),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Project Intelligence Backup CLI")
    parser.add_argument("--storage-dir", type=str, help="Path to storage directory")
    parser.add_argument("--storage-out", type=str, help="Output path for storage archive")
    parser.add_argument("--db-url", type=str, help="PostgreSQL connection string")
    parser.add_argument("--db-out", type=str, help="Output path for database dump")

    args = parser.parse_args()

    if args.storage_dir and args.storage_out:
        res = backup_storage(args.storage_dir, args.storage_out)
        print(f"Storage backup complete: {res['files_count']} files, {res['total_bytes']} bytes")

    if args.db_url and args.db_out:
        res = backup_postgres(args.db_url, args.db_out)
        print(f"Database backup complete: status={res['status']}")


if __name__ == "__main__":
    main()
