"""Unit tests for activity tabular export service (PI-047)."""

import io
import uuid
from collections.abc import AsyncGenerator
from datetime import date
from typing import Any

import openpyxl
import pytest
from app.domains.reporting.service import generate_activity_export
from app.models.auth import User, Workspace, WorkspaceMember
from app.models.base import Base
from app.models.project import ImportJob, Project, ProjectVersion, UploadedFile
from app.models.reporting import UsageEvent
from app.models.schedule import Activity, Calendar, WBSNode
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
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


@pytest.fixture
async def export_test_data(session: AsyncSession) -> dict[str, Any]:
    """Seed project, version, WBS, and activities for export tests."""
    user = User(
        auth_subject=f"sub_{uuid.uuid4().hex[:8]}",
        email=f"reporter_{uuid.uuid4().hex[:6]}@example.com",
        display_name="Export Tester",
    )
    session.add(user)
    await session.flush()

    workspace = Workspace(name="EPC Export Workspace", owner_user_id=user.id)
    session.add(workspace)
    await session.flush()

    member = WorkspaceMember(
        workspace_id=workspace.id,
        user_id=user.id,
        role="owner",
    )
    session.add(member)

    project = Project(
        workspace_id=workspace.id,
        name="Refinery Expansion",
        project_code="REF-EXP-01",
    )
    session.add(project)
    await session.flush()

    uploaded_file = UploadedFile(
        id=uuid.uuid4(),
        workspace_id=workspace.id,
        project_id=project.id,
        original_filename="refinery.xer",
        file_size_bytes=1024,
        source_format="xer",
        object_key="uploads/test.xer",
        sha256_checksum="deadbeef" * 8,
        uploaded_by=user.id,
    )
    session.add(uploaded_file)
    await session.flush()

    import_job = ImportJob(
        id=uuid.uuid4(),
        workspace_id=workspace.id,
        project_id=project.id,
        uploaded_file_id=uploaded_file.id,
        status="confirmed",
        progress_pct=100.0,
    )
    session.add(import_job)
    await session.flush()

    version = ProjectVersion(
        id=uuid.uuid4(),
        workspace_id=workspace.id,
        project_id=project.id,
        import_job_id=import_job.id,
        version_label="Baseline Rev 1",
        version_number=1,
        source_format="xer",
        data_date=date(2026, 1, 1),
    )
    session.add(version)
    await session.flush()

    project.latest_version_id = version.id
    await session.flush()

    # WBS Nodes
    wbs1 = WBSNode(
        workspace_id=workspace.id,
        project_id=project.id,
        project_version_id=version.id,
        source_wbs_id="WBS-1",
        wbs_code="1.1",
        wbs_name="Engineering",
    )
    wbs2 = WBSNode(
        workspace_id=workspace.id,
        project_id=project.id,
        project_version_id=version.id,
        source_wbs_id="WBS-2",
        wbs_code="1.2",
        wbs_name="Procurement",
    )
    session.add_all([wbs1, wbs2])
    await session.flush()

    # Calendar
    cal = Calendar(
        workspace_id=workspace.id,
        project_id=project.id,
        project_version_id=version.id,
        calendar_name="Standard 5-Day",
    )
    session.add(cal)
    await session.flush()

    # Activities: 1 critical, 1 non-critical
    act1 = Activity(
        workspace_id=workspace.id,
        project_id=project.id,
        project_version_id=version.id,
        source_activity_id="ACT-001",
        activity_code="ENG-101",
        activity_name="P&ID Approval",
        wbs_node_id=wbs1.id,
        calendar_id=cal.id,
        status="complete",
        planned_start=date(2026, 1, 2),
        planned_finish=date(2026, 1, 15),
        actual_start=date(2026, 1, 2),
        actual_finish=date(2026, 1, 14),
        original_duration_hours=80.0,
        remaining_duration_hours=0.0,
        actual_duration_hours=72.0,
        total_float_hours=40.0,
        free_float_hours=20.0,
        physical_pct_complete=100.0,
    )
    act2 = Activity(
        workspace_id=workspace.id,
        project_id=project.id,
        project_version_id=version.id,
        source_activity_id="ACT-002",
        activity_code="PROC-201",
        activity_name="Compressor Purchase Order",
        wbs_node_id=wbs2.id,
        calendar_id=cal.id,
        status="in_progress",
        planned_start=date(2026, 1, 16),
        planned_finish=date(2026, 2, 28),
        actual_start=date(2026, 1, 17),
        actual_finish=None,
        original_duration_hours=240.0,
        remaining_duration_hours=180.0,
        actual_duration_hours=60.0,
        total_float_hours=0.0,  # Critical path
        free_float_hours=0.0,
        physical_pct_complete=25.0,
    )
    session.add_all([act1, act2])
    await session.commit()

    return {
        "user": user,
        "workspace": workspace,
        "project": project,
        "version": version,
    }


async def test_generate_activity_export_csv(
    session: AsyncSession,
    export_test_data: dict[str, Any],
) -> None:
    saved_objects: dict[str, bytes] = {}

    async def fake_storage_put(key: str, data: bytes, content_type: str) -> None:
        saved_objects[key] = data

    project = export_test_data["project"]
    version = export_test_data["version"]
    user = export_test_data["user"]

    report = await generate_activity_export(
        session=session,
        storage_put_fn=fake_storage_put,
        project_id=project.id,
        version_id=version.id,
        user_id=user.id,
        output_format="csv",
    )

    assert report.status == "ready"
    assert report.report_type == "activity_export"
    assert report.output_format == "csv"
    assert report.object_key in saved_objects

    csv_data = saved_objects[report.object_key].decode("utf-8-sig")
    assert "Activity ID,Activity Code,Activity Name" in csv_data
    assert "ENG-101" in csv_data
    assert "PROC-201" in csv_data

    # Verify UsageEvent
    events = (
        (await session.execute(select(UsageEvent).where(UsageEvent.project_id == project.id)))
        .scalars()
        .all()
    )
    assert len(events) == 1
    assert events[0].event_type == "report_export"
    assert events[0].metadata_["row_count"] == 2


async def test_generate_activity_export_with_filters(
    session: AsyncSession,
    export_test_data: dict[str, Any],
) -> None:
    saved_objects: dict[str, bytes] = {}

    async def fake_storage_put(key: str, data: bytes, content_type: str) -> None:
        saved_objects[key] = data

    project = export_test_data["project"]
    version = export_test_data["version"]
    user = export_test_data["user"]

    # Filter critical only -> should only include PROC-201
    report = await generate_activity_export(
        session=session,
        storage_put_fn=fake_storage_put,
        project_id=project.id,
        version_id=version.id,
        user_id=user.id,
        output_format="csv",
        critical_only=True,
    )

    assert report.object_key is not None
    csv_data = saved_objects[report.object_key].decode("utf-8-sig")
    assert "PROC-201" in csv_data
    assert "ENG-101" not in csv_data


async def test_generate_activity_export_xlsx(
    session: AsyncSession,
    export_test_data: dict[str, Any],
) -> None:
    saved_objects: dict[str, bytes] = {}

    async def fake_storage_put(key: str, data: bytes, content_type: str) -> None:
        saved_objects[key] = data

    project = export_test_data["project"]
    version = export_test_data["version"]
    user = export_test_data["user"]

    report = await generate_activity_export(
        session=session,
        storage_put_fn=fake_storage_put,
        project_id=project.id,
        version_id=version.id,
        user_id=user.id,
        output_format="xlsx",
    )

    assert report.status == "ready"
    assert report.output_format == "xlsx"
    assert report.object_key is not None
    xlsx_bytes = saved_objects[report.object_key]
    assert xlsx_bytes.startswith(b"PK")

    wb = openpyxl.load_workbook(io.BytesIO(xlsx_bytes))
    ws = wb["Activities"]
    assert ws.max_row == 3  # Header + 2 activities
