"""Unit tests for deterministic milestone forecast service (PI-044).

Acceptance criteria:
- Forecast method is explicit.
- Source/imported date is distinguished from calculated projection.
- Missing data/calendar/network limitations are returned.
- No unsupported probabilistic confidence claim.
"""

import uuid
from collections.abc import AsyncGenerator
from datetime import date

import pytest
from app.domains.schedule.forecast import compute_milestone_forecast
from app.models.auth import User, Workspace
from app.models.base import Base
from app.models.project import ImportJob, Project, ProjectVersion, UploadedFile
from app.models.schedule import Activity, WBSNode
from sqlalchemy import event
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


async def _seed_forecast_milestones(
    session: AsyncSession,
) -> tuple[Project, ProjectVersion, list[Activity]]:
    user = User(
        id=uuid.uuid4(),
        auth_subject="auth0|forecast-user",
        email="forecast.user@epc-intel.test",
        display_name="Forecast Test User",
    )
    workspace = Workspace(
        id=uuid.uuid4(),
        name="Forecast Workspace",
        owner_user_id=user.id,
    )
    session.add_all([user, workspace])
    await session.flush()

    project = Project(
        id=uuid.uuid4(),
        workspace_id=workspace.id,
        name="Turbine Plant Construction",
        project_code="TPC-001",
    )
    session.add(project)
    await session.flush()

    upload = UploadedFile(
        id=uuid.uuid4(),
        workspace_id=workspace.id,
        project_id=project.id,
        uploaded_by=user.id,
        original_filename="turbine_schedule.xer",
        object_key="mock/path.xer",
        source_format="xer",
        file_size_bytes=1024,
        sha256_checksum="abc" * 20,
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
        data_date=date(2026, 6, 1),
    )
    session.add(version)
    await session.flush()

    project.latest_version_id = version.id
    await session.flush()

    wbs = WBSNode(
        id=uuid.uuid4(),
        workspace_id=workspace.id,
        project_id=project.id,
        project_version_id=version.id,
        source_wbs_id="WBS-KEY",
        wbs_code="1.1.M",
        wbs_name="Key Project Milestones",
    )
    session.add(wbs)
    await session.flush()

    activities = [
        # 1. Milestone with negative total float (-40h = -5 working days)
        Activity(
            id=uuid.uuid4(),
            workspace_id=workspace.id,
            project_id=project.id,
            project_version_id=version.id,
            source_activity_id="MS-1010",
            activity_code="M-FOUNDATION",
            activity_name="Turbine Foundation Complete",
            wbs_node_id=wbs.id,
            activity_type="finish_milestone",
            status="in_progress",
            planned_start=date(2026, 7, 1),
            planned_finish=date(2026, 7, 1),
            finish_date=date(2026, 7, 10),
            original_duration_hours=0.0,
            remaining_duration_hours=0.0,
            total_float_hours=-40.0,
        ),
        # 2. Completed milestone
        Activity(
            id=uuid.uuid4(),
            workspace_id=workspace.id,
            project_id=project.id,
            project_version_id=version.id,
            source_activity_id="MS-1000",
            activity_code="M-NTP",
            activity_name="Notice to Proceed",
            wbs_node_id=wbs.id,
            activity_type="start_milestone",
            status="complete",
            planned_start=date(2026, 1, 15),
            planned_finish=date(2026, 1, 15),
            actual_start=date(2026, 1, 15),
            actual_finish=date(2026, 1, 15),
            original_duration_hours=0.0,
            remaining_duration_hours=0.0,
            total_float_hours=0.0,
        ),
        # 3. Future milestone with positive float (+160h = 20 working days)
        Activity(
            id=uuid.uuid4(),
            workspace_id=workspace.id,
            project_id=project.id,
            project_version_id=version.id,
            source_activity_id="MS-1020",
            activity_code="M-COD",
            activity_name="Commercial Operation Date",
            wbs_node_id=wbs.id,
            activity_type="TT_FinMile",
            status="not_started",
            planned_start=date(2026, 12, 1),
            planned_finish=date(2026, 12, 1),
            finish_date=date(2026, 12, 1),
            original_duration_hours=0.0,
            remaining_duration_hours=0.0,
            total_float_hours=160.0,
        ),
        # 4. Milestone with missing float
        Activity(
            id=uuid.uuid4(),
            workspace_id=workspace.id,
            project_id=project.id,
            project_version_id=version.id,
            source_activity_id="MS-1030",
            activity_code="M-GRID",
            activity_name="Grid Interconnection",
            wbs_node_id=wbs.id,
            activity_type="finish_milestone",
            status="not_started",
            planned_finish=date(2026, 11, 1),
            finish_date=date(2026, 11, 1),
            original_duration_hours=0.0,
            remaining_duration_hours=0.0,
            total_float_hours=None,
        ),
        # 5. Regular activity (duration > 0, not a milestone)
        Activity(
            id=uuid.uuid4(),
            workspace_id=workspace.id,
            project_id=project.id,
            project_version_id=version.id,
            source_activity_id="ACT-2000",
            activity_code="A-POUR",
            activity_name="Concrete Pouring",
            wbs_node_id=wbs.id,
            activity_type="TT_Task",
            status="in_progress",
            planned_start=date(2026, 6, 2),
            planned_finish=date(2026, 6, 25),
            original_duration_hours=184.0,
            remaining_duration_hours=80.0,
            total_float_hours=-16.0,
        ),
    ]

    session.add_all(activities)
    await session.commit()
    return project, version, activities


@pytest.mark.asyncio
async def test_milestone_forecast_imported_schedule_dates(session: AsyncSession) -> None:
    project, version, _ = await _seed_forecast_milestones(session)

    res = await compute_milestone_forecast(
        session=session,
        project_id=project.id,
        version_id=version.id,
        method="imported_schedule_dates",
    )

    assert res.project_id == project.id
    assert res.project_version_id == version.id
    assert res.method == "imported_schedule_dates"
    assert "Imported schedule forecast dates" in res.method_description
    assert res.confidence_level is None
    assert "Deterministic schedule projection only" in res.deterministic_disclaimer
    assert len(res.limitations) >= 3

    # Only the 4 milestones should be extracted, ACT-2000 excluded
    assert len(res.items) == 4
    assert res.summary.total_milestones == 4
    assert res.summary.completed_milestones == 1

    # Imported method marks all items with is_calculated_projection = False
    for item in res.items:
        assert item.is_calculated_projection is False
        assert item.source_date is not None
        assert item.projected_date == item.source_date


@pytest.mark.asyncio
async def test_milestone_forecast_deterministic_float_indicator(
    session: AsyncSession,
) -> None:
    project, version, _ = await _seed_forecast_milestones(session)

    res = await compute_milestone_forecast(
        session=session,
        project_id=project.id,
        version_id=version.id,
        method="deterministic_float_indicator",
        hours_per_day=8.0,
    )

    assert res.method == "deterministic_float_indicator"
    assert "Deterministic slippage projection" in res.method_description

    items_by_code = {item.activity_code: item for item in res.items}

    # 1. Negative float milestone (M-FOUNDATION): -40h = 5 working days -> 7 calendar days slip
    ms_found = items_by_code["M-FOUNDATION"]
    assert ms_found.is_calculated_projection is True
    assert ms_found.source_date == date(2026, 7, 10)
    assert ms_found.source_date_type == "finish_date"
    assert ms_found.projected_date == date(2026, 7, 17)  # 10 + 7 calendar days
    assert ms_found.variance_days == 5.0
    assert ms_found.critical_status == "critical"
    assert "projects deterministic completion slip" in (ms_found.driving_notes or "")

    # 2. Completed milestone (M-NTP): projection equals actual finish
    ms_ntp = items_by_code["M-NTP"]
    assert ms_ntp.is_calculated_projection is False
    assert ms_ntp.source_date == date(2026, 1, 15)
    assert ms_ntp.source_date_type == "actual_finish"
    assert ms_ntp.projected_date == date(2026, 1, 15)
    assert ms_ntp.variance_days == 0.0

    # 3. Positive float milestone (M-COD): non-critical, projection matches source
    ms_cod = items_by_code["M-COD"]
    assert ms_cod.is_calculated_projection is False
    assert ms_cod.projected_date == date(2026, 12, 1)
    assert ms_cod.critical_status == "non_critical"
    assert ms_cod.variance_days == 0.0

    # 4. Missing float milestone (M-GRID): projection equals source with warnings
    ms_grid = items_by_code["M-GRID"]
    assert ms_grid.is_calculated_projection is False
    assert ms_grid.variance_days is None
    assert ms_grid.critical_status == "unknown"
    assert any("missing float" in w.lower() for w in ms_grid.warnings)


@pytest.mark.asyncio
async def test_milestone_forecast_single_activity_filter(session: AsyncSession) -> None:
    project, version, _ = await _seed_forecast_milestones(session)

    # Query specific milestone by code
    res = await compute_milestone_forecast(
        session=session,
        project_id=project.id,
        version_id=version.id,
        milestone_id="M-FOUNDATION",
    )
    assert len(res.items) == 1
    assert res.items[0].activity_code == "M-FOUNDATION"

    # Query specific milestone by source ID
    res2 = await compute_milestone_forecast(
        session=session,
        project_id=project.id,
        version_id=version.id,
        milestone_id="MS-1020",
    )
    assert len(res2.items) == 1
    assert res2.items[0].source_activity_id == "MS-1020"


@pytest.mark.asyncio
async def test_milestone_forecast_invalid_method(session: AsyncSession) -> None:
    project, version, _ = await _seed_forecast_milestones(session)

    with pytest.raises(ValueError, match="Unsupported forecast method"):
        await compute_milestone_forecast(
            session=session,
            project_id=project.id,
            version_id=version.id,
            method="monte_carlo_simulation",  # type: ignore[arg-type]
        )
