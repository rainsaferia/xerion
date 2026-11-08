"""Unit tests for reporting domain service (PI-046)."""

import uuid
from collections.abc import AsyncGenerator
from datetime import date
from typing import Any

import pytest
from app.domains.reporting.service import (
    create_report_download_token,
    generate_schedule_report,
    verify_report_download_token,
)
from app.models.auth import User, Workspace, WorkspaceMember
from app.models.base import Base
from app.models.project import ImportJob, Project, ProjectVersion, UploadedFile
from app.models.reporting import Report, UsageEvent
from app.models.schedule import Activity
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
async def reporting_test_data(session: AsyncSession) -> dict[str, Any]:
    """Seed minimal project, version, and activities for reporting tests."""
    user = User(
        auth_subject=f"sub_{uuid.uuid4().hex[:8]}",
        email=f"reporter_{uuid.uuid4().hex[:6]}@example.com",
        display_name="Report Tester",
    )
    session.add(user)
    await session.flush()

    workspace = Workspace(name="EPC Reports Workspace", owner_user_id=user.id)
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
        name="Offshore Subsea Manifold",
        project_code="OFF-SUB-01",
    )
    session.add(project)
    await session.flush()

    upload = UploadedFile(
        id=uuid.uuid4(),
        workspace_id=workspace.id,
        project_id=project.id,
        original_filename="schedule.xer",
        object_key=f"uploads/{uuid.uuid4()}/schedule.xer",
        source_format="xer",
        file_size_bytes=2048,
        sha256_checksum="deadbeef" * 8,
        uploaded_by=user.id,
    )
    session.add(upload)
    await session.flush()

    job = ImportJob(
        id=uuid.uuid4(),
        workspace_id=workspace.id,
        project_id=project.id,
        uploaded_file_id=upload.id,
        status="confirmed",
    )
    session.add(job)
    await session.flush()

    version = ProjectVersion(
        id=uuid.uuid4(),
        workspace_id=workspace.id,
        project_id=project.id,
        import_job_id=job.id,
        version_number=1,
        source_format="xer",
        version_label="Rev 0 Baseline",
        data_date=date(2026, 8, 30),
    )
    session.add(version)
    await session.flush()

    project.latest_version_id = version.id
    session.add(project)

    # Add a normal activity and a milestone
    act1 = Activity(
        workspace_id=workspace.id,
        project_id=project.id,
        project_version_id=version.id,
        source_activity_id="ACT-101",
        activity_code="ACT-101",
        activity_name="Fabrication Phase 1",
        status="in_progress",
        activity_type="Task Dependent",
        total_float_hours=-16.0,
        start_date=date(2026, 7, 1),
        finish_date=date(2026, 9, 15),
    )
    ms1 = Activity(
        workspace_id=workspace.id,
        project_id=project.id,
        project_version_id=version.id,
        source_activity_id="MS-101",
        activity_code="MS-101",
        activity_name="Ready for Loadout",
        status="not_started",
        activity_type="Finish Milestone",
        total_float_hours=-16.0,
        finish_date=date(2026, 9, 15),
    )
    session.add_all([act1, ms1])
    await session.flush()

    return {
        "user": user,
        "workspace": workspace,
        "project": project,
        "version": version,
    }


async def test_generate_schedule_report_creates_pdf_and_usage_event(
    session: AsyncSession, reporting_test_data: dict[str, Any]
) -> None:
    data = reporting_test_data
    project: Project = data["project"]
    version: ProjectVersion = data["version"]
    user: User = data["user"]

    stored_objects: dict[str, bytes] = {}

    async def mock_storage_put(key: str, content: bytes, content_type: str) -> None:
        assert content_type == "application/pdf"
        stored_objects[key] = content

    report = await generate_schedule_report(
        session=session,
        storage_put_fn=mock_storage_put,
        project_id=project.id,
        version_id=version.id,
        user_id=user.id,
        user_email=user.email,
        report_type="schedule_analysis",
        output_format="pdf",
        options={"include_activity_appendix": False},
    )

    assert isinstance(report, Report)
    assert report.status == "ready"
    assert report.output_format == "pdf"
    assert report.object_key is not None
    assert f"workspaces/{project.workspace_id}/projects/{project.id}/reports/" in report.object_key
    assert report.completed_at is not None

    # Verify storage contains valid PDF bytes
    assert report.object_key in stored_objects
    pdf_bytes = stored_objects[report.object_key]
    assert pdf_bytes.startswith(b"%PDF-")
    assert len(pdf_bytes) > 1000

    # Verify UsageEvent was added

    events = (
        (await session.execute(select(UsageEvent).where(UsageEvent.project_id == project.id)))
        .scalars()
        .all()
    )
    assert len(events) >= 1
    assert events[0].event_type == "report_export"
    assert events[0].workspace_id == project.workspace_id


async def test_generate_schedule_report_invalid_project_fails(session: AsyncSession) -> None:
    fake_id = uuid.uuid4()

    async def mock_storage_put(key: str, content: bytes, content_type: str) -> None:
        pass

    with pytest.raises(ValueError, match="not found"):
        await generate_schedule_report(
            session=session,
            storage_put_fn=mock_storage_put,
            project_id=fake_id,
            version_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            user_email="test@epc.org",
        )


def test_report_download_token_lifecycle() -> None:
    report_id = uuid.uuid4()
    project_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    user_id = uuid.uuid4()
    secret = "epc-super-secret-key-32-bytes-long-now!!"  # noqa: S105

    token = create_report_download_token(
        report_id=report_id,
        project_id=project_id,
        workspace_id=workspace_id,
        user_id=user_id,
        auth_subject="sub-user-123",
        secret_key=secret,
        expires_in_seconds=900,
    )

    assert isinstance(token, str)
    assert len(token) > 20

    payload = verify_report_download_token(token, secret)
    assert payload["sub"] == "sub-user-123"
    assert payload["report_id"] == str(report_id)
    assert payload["project_id"] == str(project_id)
    assert payload["workspace_id"] == str(workspace_id)
    assert payload["scope"] == "report_download"

    # Invalid secret fails
    with pytest.raises(ValueError, match="Invalid or expired download token"):
        verify_report_download_token(token, "wrong-secret-key-here-1234567890!")

    # Expired token fails
    expired_token = create_report_download_token(
        report_id=report_id,
        project_id=project_id,
        workspace_id=workspace_id,
        user_id=user_id,
        auth_subject="sub-user-123",
        secret_key=secret,
        expires_in_seconds=-10,
    )
    with pytest.raises(ValueError, match="Invalid or expired download token"):
        verify_report_download_token(expired_token, secret)
