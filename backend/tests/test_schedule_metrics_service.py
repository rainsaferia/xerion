"""Unit tests for schedule overview metrics domain service (PI-030).

Acceptance criteria:
- Activity counts and status distribution computed from selected version.
- Data date and source finish information shown.
- Missing fields display as unavailable (None), not zero.
"""

import uuid
from collections.abc import AsyncGenerator
from datetime import date

import pytest
from app.domains.schedule.metrics import compute_project_overview_metrics
from app.models.auth import User, Workspace
from app.models.base import Base
from app.models.project import ImportJob, Project, ProjectVersion, UploadedFile
from app.models.schedule import Activity, ActivityRelationship, Calendar, WBSNode
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool


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


async def test_compute_project_overview_metrics_with_activities(session: AsyncSession) -> None:
    # 1. Setup user, workspace and project
    user = User(
        id=uuid.uuid4(),
        auth_subject="auth0|metrics-user",
        email="metrics@epc.test",
    )
    session.add(user)
    await session.flush()

    ws = Workspace(id=uuid.uuid4(), name="Test WS", owner_user_id=user.id)
    session.add(ws)
    await session.flush()

    project = Project(
        id=uuid.uuid4(),
        workspace_id=ws.id,
        name="Offshore Processing Unit",
        project_code="OPU-001",
    )
    session.add(project)
    await session.flush()

    # 2. Setup upload and job
    uploaded_file = UploadedFile(
        id=uuid.uuid4(),
        workspace_id=ws.id,
        project_id=project.id,
        original_filename="schedule_v1.xer",
        object_key="uploads/test.xer",
        source_format="xer",
        file_size_bytes=1024,
        sha256_checksum="abc",
    )
    session.add(uploaded_file)
    await session.flush()

    job = ImportJob(
        id=uuid.uuid4(),
        workspace_id=ws.id,
        project_id=project.id,
        uploaded_file_id=uploaded_file.id,
        status="confirmed",
    )
    session.add(job)
    await session.flush()

    # 3. Setup ProjectVersion
    version = ProjectVersion(
        id=uuid.uuid4(),
        workspace_id=ws.id,
        project_id=project.id,
        import_job_id=job.id,
        version_number=1,
        version_label="V1",
        source_format="xer",
        data_date=date(2026, 11, 1),
        project_start_date=date(2026, 1, 15),
        project_finish_date=date(2026, 12, 31),
        quality_summary={"warnings_count": 2},
        status="ready",
    )
    session.add(version)
    await session.flush()
    project.latest_version_id = version.id
    await session.flush()

    # 4. Add Calendar, WBS, Relationships
    cal = Calendar(
        id=uuid.uuid4(),
        workspace_id=ws.id,
        project_id=project.id,
        project_version_id=version.id,
        source_calendar_id="1",
        calendar_name="Standard",
    )
    wbs = WBSNode(
        id=uuid.uuid4(),
        workspace_id=ws.id,
        project_id=project.id,
        project_version_id=version.id,
        source_wbs_id="W1",
        wbs_name="Engineering",
    )
    session.add_all([cal, wbs])
    await session.flush()

    # 5. Add 5 activities with varied status, float, physical percent complete
    # Act 1: Complete, 100% complete, float 0
    a1 = Activity(
        id=uuid.uuid4(),
        workspace_id=ws.id,
        project_id=project.id,
        project_version_id=version.id,
        source_activity_id="A101",
        activity_code="ENG-101",
        activity_name="Design Basis",
        status="complete",
        start_date=date(2026, 1, 15),
        finish_date=date(2026, 2, 28),
        total_float_hours=0.0,
        physical_pct_complete=100.0,
    )
    # Act 2: In progress, 50% complete, float -16.0 (critical!)
    a2 = Activity(
        id=uuid.uuid4(),
        workspace_id=ws.id,
        project_id=project.id,
        project_version_id=version.id,
        source_activity_id="A102",
        activity_code="ENG-102",
        activity_name="P&ID Review",
        status="in_progress",
        start_date=date(2026, 3, 1),
        finish_date=date(2026, 5, 31),
        total_float_hours=-16.0,
        physical_pct_complete=50.0,
    )
    # Act 3: Not started, near critical (float 40.0 hours <= 80 hours threshold)
    a3 = Activity(
        id=uuid.uuid4(),
        workspace_id=ws.id,
        project_id=project.id,
        project_version_id=version.id,
        source_activity_id="A103",
        activity_code="PROC-101",
        activity_name="Long Lead Procurement",
        status="not_started",
        start_date=date(2026, 6, 1),
        finish_date=date(2026, 9, 30),
        total_float_hours=40.0,
        physical_pct_complete=0.0,
    )
    # Act 4: Not started, safe float (160.0 hours)
    a4 = Activity(
        id=uuid.uuid4(),
        workspace_id=ws.id,
        project_id=project.id,
        project_version_id=version.id,
        source_activity_id="A104",
        activity_code="CIV-101",
        activity_name="Site Preparation",
        status="not_started",
        start_date=date(2026, 7, 1),
        finish_date=date(2026, 10, 31),
        total_float_hours=160.0,
        physical_pct_complete=None,  # missing basis
    )
    # Act 5: Milestone (duration 0)
    a5 = Activity(
        id=uuid.uuid4(),
        workspace_id=ws.id,
        project_id=project.id,
        project_version_id=version.id,
        source_activity_id="A105",
        activity_code="MS-01",
        activity_name="Project Completion Milestone",
        activity_type="finish_milestone",
        status="not_started",
        start_date=date(2026, 12, 31),
        finish_date=date(2026, 12, 31),
        original_duration_hours=0.0,
        total_float_hours=0.0,
    )
    session.add_all([a1, a2, a3, a4, a5])
    await session.flush()

    # Add relationship
    rel = ActivityRelationship(
        id=uuid.uuid4(),
        workspace_id=ws.id,
        project_id=project.id,
        project_version_id=version.id,
        predecessor_activity_id=a1.id,
        successor_activity_id=a2.id,
        relationship_type="FS",
    )
    session.add(rel)
    await session.commit()

    # Execute metrics computation
    metrics = await compute_project_overview_metrics(
        session=session,
        project_id=project.id,
        version_id=version.id,
    )

    assert metrics.project_id == project.id
    assert metrics.project_name == "Offshore Processing Unit"
    assert metrics.version_id == version.id
    assert metrics.version_number == 1
    assert metrics.version_label == "V1"
    assert metrics.data_date == date(2026, 11, 1)
    assert metrics.project_start_date == date(2026, 1, 15)
    assert metrics.project_finish_date == date(2026, 12, 31)
    assert metrics.source_filename == "schedule_v1.xer"
    assert metrics.source_format == "xer"

    # Activity counts & status distribution
    assert metrics.total_activities == 5
    assert metrics.status_distribution.complete == 1
    assert metrics.status_distribution.in_progress == 1
    assert metrics.status_distribution.not_started == 3
    assert metrics.status_distribution.suspended == 0
    assert metrics.status_distribution.unknown == 0

    # Milestones and criticals
    assert metrics.milestones_count == 1
    assert metrics.critical_activities_count == 3  # a1(0.0), a2(-16.0), a5(0.0)
    assert metrics.near_critical_activities_count == 1  # a3(40.0)

    # Float statistics
    assert metrics.min_total_float_hours == -16.0
    assert metrics.max_total_float_hours == 160.0

    # Physical % complete: average of (100.0, 50.0, 0.0) ignoring None = 50.0
    assert metrics.avg_physical_pct_complete == 50.0

    # Counts of structural entities
    assert metrics.calendars_count == 1
    assert metrics.wbs_nodes_count == 1
    assert metrics.relationships_count == 1
    assert metrics.warnings_count == 2


async def test_compute_overview_metrics_missing_fields_stay_none(session: AsyncSession) -> None:
    """PI-030 Acceptance criterion: Missing fields display as unavailable, not zero."""
    user = User(
        id=uuid.uuid4(),
        auth_subject="auth0|metrics-user-2",
        email="metrics2@epc.test",
    )
    session.add(user)
    await session.flush()

    ws = Workspace(id=uuid.uuid4(), name="Test WS 2", owner_user_id=user.id)
    session.add(ws)
    await session.flush()

    project = Project(
        id=uuid.uuid4(),
        workspace_id=ws.id,
        name="Crude Storage Expansion",
    )
    session.add(project)
    await session.flush()

    uploaded_file = UploadedFile(
        id=uuid.uuid4(),
        workspace_id=ws.id,
        project_id=project.id,
        original_filename="minimal.csv",
        object_key="uploads/minimal.csv",
        source_format="csv",
        file_size_bytes=100,
        sha256_checksum="xyz",
    )
    session.add(uploaded_file)
    await session.flush()

    job = ImportJob(
        id=uuid.uuid4(),
        workspace_id=ws.id,
        project_id=project.id,
        uploaded_file_id=uploaded_file.id,
        status="confirmed",
    )
    session.add(job)
    await session.flush()

    version = ProjectVersion(
        id=uuid.uuid4(),
        workspace_id=ws.id,
        project_id=project.id,
        import_job_id=job.id,
        version_number=1,
        source_format="csv",
        status="ready",
    )
    session.add(version)
    await session.flush()
    project.latest_version_id = version.id
    await session.flush()

    # Activities with NO float and NO physical percent complete
    a1 = Activity(
        id=uuid.uuid4(),
        workspace_id=ws.id,
        project_id=project.id,
        project_version_id=version.id,
        source_activity_id="T1",
        activity_name="Task 1",
        status="not_started",
        total_float_hours=None,
        physical_pct_complete=None,
    )
    a2 = Activity(
        id=uuid.uuid4(),
        workspace_id=ws.id,
        project_id=project.id,
        project_version_id=version.id,
        source_activity_id="T2",
        activity_name="Task 2",
        status="not_started",
        total_float_hours=None,
        physical_pct_complete=None,
    )
    session.add_all([a1, a2])
    await session.commit()

    metrics = await compute_project_overview_metrics(session, project.id)

    assert metrics.total_activities == 2
    # Critical acceptance criterion: MUST BE None (unavailable), NEVER 0.0!
    assert metrics.min_total_float_hours is None
    assert metrics.max_total_float_hours is None
    assert metrics.avg_physical_pct_complete is None
    assert metrics.critical_activities_count == 0
    assert metrics.near_critical_activities_count == 0
