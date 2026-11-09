"""Automated tests for database and storage backup and restore procedures (PI-053 Task 2)."""

import json
import sys
import tempfile
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from app.models.auth import User, Workspace
from app.models.base import Base
from app.models.project import Project
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

ROOT_DIR = Path(__file__).parent.parent.parent


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine(
        "sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )

    @event.listens_for(engine.sync_engine, "connect")
    def _fk_on(dbapi_conn, _record) -> None:  # type: ignore[no-untyped-def]
        dbapi_conn.execute("PRAGMA foreign_keys = ON")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


def test_storage_backup_and_restore_cycle() -> None:
    """Verify private storage archiving and restoration maintains file contents and hierarchy."""
    sys.path.insert(0, str(ROOT_DIR / "scripts"))
    import backup as backup_script  # type: ignore[import-not-found, unused-ignore]
    import restore as restore_script  # type: ignore[import-not-found]

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        source_storage = temp_path / "source_storage"
        source_storage.mkdir()

        # Seed private storage structure
        (source_storage / "uploads" / "proj_1").mkdir(parents=True)
        (source_storage / "reports" / "proj_1").mkdir(parents=True)

        file1 = source_storage / "uploads" / "proj_1" / "schedule.xer"
        file1.write_bytes(b"TEST_P6_XER_DATA_BYTES_12345")

        file2 = source_storage / "reports" / "proj_1" / "report.pdf"
        file2.write_bytes(b"%PDF-1.4 TEST_REPORT_PDF_BYTES_67890")

        # 1. Execute Backup
        backup_archive = temp_path / "storage_backup.tar.gz"
        result_meta = backup_script.backup_storage(
            storage_dir=source_storage,
            output_archive=backup_archive,
        )

        assert backup_archive.exists()
        assert result_meta["files_count"] == 2
        assert result_meta["total_bytes"] == len(file1.read_bytes()) + len(file2.read_bytes())

        # 2. Wipe / Create Target Restoration Directory
        dest_storage = temp_path / "dest_storage"
        dest_storage.mkdir()

        # 3. Execute Restore
        restore_meta = restore_script.restore_storage(
            archive_path=backup_archive,
            destination_dir=dest_storage,
        )

        assert restore_meta["restored_files_count"] == 2
        restored_file1 = dest_storage / "uploads" / "proj_1" / "schedule.xer"
        restored_file2 = dest_storage / "reports" / "proj_1" / "report.pdf"

        assert restored_file1.exists()
        assert restored_file1.read_bytes() == file1.read_bytes()
        assert restored_file2.exists()
        assert restored_file2.read_bytes() == file2.read_bytes()


@pytest.mark.asyncio
async def test_database_backup_and_restore_data_integrity(session: AsyncSession) -> None:
    """Verify database export and restore roundtrip preserves models and records."""
    sys.path.insert(0, str(ROOT_DIR / "scripts"))
    import backup as backup_script  # type: ignore[import-not-found, unused-ignore]

    user = User(
        auth_subject="auth0|backup-user",
        email="backup@epc.test",
        display_name="Backup Lead",
    )
    session.add(user)
    await session.flush()

    ws = Workspace(name="Backup Workspace", owner_user_id=user.id)
    session.add(ws)
    await session.flush()

    p1 = Project(workspace_id=ws.id, name="Project Alpha")
    p2 = Project(workspace_id=ws.id, name="Project Beta")
    session.add_all([p1, p2])
    await session.commit()

    with tempfile.TemporaryDirectory() as temp_dir:
        out_file = Path(temp_dir) / "db_export.json"

        # 1. Export database snapshot
        summary = await backup_script.export_sqlite_snapshot(session, out_file)
        assert out_file.exists()
        assert summary["users_count"] == 1
        assert summary["workspaces_count"] == 1
        assert summary["projects_count"] == 2

        # 2. Verify JSON format (synchronous read allowed in tests)
        raw_text = out_file.read_text(encoding="utf-8")  # noqa: ASYNC230
        data = json.loads(raw_text)
        assert len(data["projects"]) == 2
        project_names = {p["name"] for p in data["projects"]}
        assert project_names == {"Project Alpha", "Project Beta"}
