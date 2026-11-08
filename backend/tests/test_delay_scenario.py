"""Unit tests for deterministic delay scenario engine (PI-045).

Acceptance criteria:
- User selects activity and delay amount/unit.
- Scenario does not change source activity/version rows (zero mutation).
- Affected outputs and assumptions are shown.
- If the scenario engine cannot calculate valid impact, it returns a limited/insufficient result.
"""

import uuid
from collections.abc import AsyncGenerator
from datetime import date

import pytest
from app.domains.schedule.scenario import simulate_activity_delay
from app.models.auth import User, Workspace
from app.models.base import Base
from app.models.project import ImportJob, Project, ProjectVersion, UploadedFile
from app.models.schedule import Activity, ActivityRelationship, WBSNode
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


async def _seed_scenario_network(
    session: AsyncSession,
) -> tuple[Project, ProjectVersion, Activity, Activity, Activity]:
    user = User(
        id=uuid.uuid4(),
        auth_subject="auth0|scenario-user",
        email="scenario@epc.test",
        display_name="Scenario Engineer",
    )
    workspace = Workspace(
        id=uuid.uuid4(),
        name="Scenario Workspace",
        owner_user_id=user.id,
    )
    session.add_all([user, workspace])
    await session.flush()

    project = Project(
        id=uuid.uuid4(),
        workspace_id=workspace.id,
        name="Petrochemical Expansion",
        project_code="PCX-001",
    )
    session.add(project)
    await session.flush()

    upload = UploadedFile(
        id=uuid.uuid4(),
        workspace_id=workspace.id,
        project_id=project.id,
        uploaded_by=user.id,
        original_filename="pcx_schedule.xer",
        object_key="pcx/schedule.xer",
        source_format="xer",
        file_size_bytes=4096,
        sha256_checksum="deadbeef" * 8,
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
        source_wbs_id="WBS-PCX",
        wbs_code="1.0",
        wbs_name="Process Unit",
    )
    session.add(wbs)
    await session.flush()

    # Activity 1: Target piping activity (Finish date: 2026-07-10, TF: 16h = 2 working days)
    act1 = Activity(
        id=uuid.uuid4(),
        workspace_id=workspace.id,
        project_id=project.id,
        project_version_id=version.id,
        source_activity_id="ACT-PIPE-01",
        activity_code="A-PIPE",
        activity_name="Reactor Piping Prefabrication",
        wbs_node_id=wbs.id,
        activity_type="TT_Task",
        status="in_progress",
        start_date=date(2026, 6, 15),
        finish_date=date(2026, 7, 10),
        planned_start=date(2026, 6, 15),
        planned_finish=date(2026, 7, 10),
        original_duration_hours=160.0,
        remaining_duration_hours=80.0,
        total_float_hours=16.0,  # 2 days float
        free_float_hours=0.0,
    )

    # Activity 2: Successor testing activity (FS link, finish 2026-07-24)
    act2 = Activity(
        id=uuid.uuid4(),
        workspace_id=workspace.id,
        project_id=project.id,
        project_version_id=version.id,
        source_activity_id="ACT-HYDRO-01",
        activity_code="A-HYDRO",
        activity_name="Piping Hydrotest",
        wbs_node_id=wbs.id,
        activity_type="TT_Task",
        status="not_started",
        start_date=date(2026, 7, 10),
        finish_date=date(2026, 7, 24),
        planned_start=date(2026, 7, 10),
        planned_finish=date(2026, 7, 24),
        original_duration_hours=80.0,
        remaining_duration_hours=80.0,
        total_float_hours=16.0,
        free_float_hours=0.0,
    )

    # Activity 3: Downstream critical finish milestone (Finish 2026-08-30, TF: 0h)
    act3 = Activity(
        id=uuid.uuid4(),
        workspace_id=workspace.id,
        project_id=project.id,
        project_version_id=version.id,
        source_activity_id="MS-MC",
        activity_code="M-MECH-COMPLETION",
        activity_name="Mechanical Completion",
        wbs_node_id=wbs.id,
        activity_type="finish_milestone",
        status="not_started",
        planned_start=date(2026, 8, 30),
        planned_finish=date(2026, 8, 30),
        finish_date=date(2026, 8, 30),
        original_duration_hours=0.0,
        remaining_duration_hours=0.0,
        total_float_hours=0.0,
    )

    # Activity 4: Completed historical activity
    act4 = Activity(
        id=uuid.uuid4(),
        workspace_id=workspace.id,
        project_id=project.id,
        project_version_id=version.id,
        source_activity_id="ACT-CIVIL-01",
        activity_code="A-CIVIL",
        activity_name="Foundation Excavation",
        wbs_node_id=wbs.id,
        activity_type="TT_Task",
        status="complete",
        actual_start=date(2026, 5, 1),
        actual_finish=date(2026, 6, 1),
        planned_start=date(2026, 5, 1),
        planned_finish=date(2026, 6, 1),
        original_duration_hours=160.0,
        remaining_duration_hours=0.0,
        total_float_hours=0.0,
    )

    session.add_all([act1, act2, act3, act4])
    await session.flush()

    # Link: A-PIPE -> A-HYDRO (FS, lag 0)
    rel = ActivityRelationship(
        id=uuid.uuid4(),
        workspace_id=workspace.id,
        project_id=project.id,
        project_version_id=version.id,
        predecessor_activity_id=act1.id,
        successor_activity_id=act2.id,
        relationship_type="FS",
        lag_hours=0.0,
    )
    session.add(rel)
    await session.commit()

    return project, version, act1, act2, act3


@pytest.mark.asyncio
async def test_simulate_delay_exceeds_float_breaches_critical(
    session: AsyncSession,
) -> None:
    project, version, act1, act2, act3 = await _seed_scenario_network(session)

    # Simulate 5 working days delay on A-PIPE (available total float is 16h = 2 days)
    res = await simulate_activity_delay(
        session=session,
        project_id=project.id,
        version_id=version.id,
        activity_source_id="A-PIPE",
        delay_value=5.0,
        delay_unit="working_days",
        scenario_name="Piping fabrication delay +5d",
    )

    assert res.status == "completed"
    assert res.scenario_name == "Piping fabrication delay +5d"
    assert res.source_unaltered is True
    assert len(res.assumptions) >= 3
    assert len(res.limitations) >= 3

    # Summary checks
    s = res.summary
    assert s.delay_applied_working_days == 5.0
    assert s.delay_applied_hours == 40.0
    assert s.delay_applied_calendar_days == 7  # 5 working days -> 7 calendar days
    assert s.total_float_absorbed_hours == 16.0  # 16h absorbed
    assert s.critical_path_breached is True
    assert s.net_project_delay_working_days == 3.0  # 40h - 16h = 24h = 3 days excess
    assert s.net_project_delay_calendar_days == 5  # ceil(3 * 7/5) = 5 days

    # Items checks: Target activity, Direct successor, Critical milestone
    assert len(res.affected_items) == 3
    by_code = {item.activity_code: item for item in res.affected_items}

    # 1. Target item
    target = by_code["A-PIPE"]
    assert target.is_target is True
    assert target.impact_type == "primary_delay"
    assert target.source_finish_date == date(2026, 7, 10)
    assert target.scenario_finish_date == date(2026, 7, 17)  # 10 + 7 calendar days
    assert target.delay_working_days == 5.0
    assert target.scenario_remaining_total_float_hours == -24.0

    # 2. Direct successor
    hydro = by_code["A-HYDRO"]
    assert hydro.is_target is False
    assert hydro.impact_type == "direct_successor_push"
    assert hydro.source_start_date == date(2026, 7, 10)
    assert hydro.scenario_start_date == date(2026, 7, 17)
    assert hydro.scenario_finish_date == date(2026, 7, 31)

    # 3. Downstream critical milestone
    mc = by_code["M-MECH-COMPLETION"]
    assert mc.is_milestone is True
    assert mc.impact_type == "critical_milestone_slip"
    assert mc.source_finish_date == date(2026, 8, 30)
    assert mc.scenario_finish_date == date(2026, 9, 4)  # 30 + 5 calendar days
    assert mc.delay_working_days == 3.0

    # CRITICAL: Verify source database rows were NEVER modified
    db_act1 = await session.scalar(select(Activity).where(Activity.id == act1.id))
    assert db_act1 is not None
    assert db_act1.finish_date == date(2026, 7, 10)  # Unchanged!
    assert db_act1.total_float_hours == 16.0  # Unchanged!


@pytest.mark.asyncio
async def test_simulate_delay_absorbed_by_float(session: AsyncSession) -> None:
    project, version, _, _, _ = await _seed_scenario_network(session)

    # Simulate 1 working day (8 hours) delay (available float is 16h)
    res = await simulate_activity_delay(
        session=session,
        project_id=project.id,
        version_id=version.id,
        activity_source_id="A-PIPE",
        delay_value=1.0,
        delay_unit="working_days",
    )

    assert res.status == "completed"
    s = res.summary
    assert s.delay_applied_working_days == 1.0
    assert s.delay_applied_hours == 8.0
    assert s.total_float_absorbed_hours == 8.0
    assert s.critical_path_breached is False
    assert s.net_project_delay_working_days == 0.0
    assert s.net_project_delay_calendar_days == 0

    # Downstream critical milestone is NOT delayed because float absorbed it
    codes = [item.activity_code for item in res.affected_items]
    assert "M-MECH-COMPLETION" not in codes


@pytest.mark.asyncio
async def test_simulate_delay_completed_activity(session: AsyncSession) -> None:
    project, version, _, _, _ = await _seed_scenario_network(session)

    # Try simulating delay on completed activity A-CIVIL
    res = await simulate_activity_delay(
        session=session,
        project_id=project.id,
        version_id=version.id,
        activity_source_id="A-CIVIL",
        delay_value=3.0,
        delay_unit="working_days",
    )

    assert res.status == "insufficient_data"
    assert res.summary.delay_applied_working_days == 0.0
    assert len(res.warnings) == 1
    assert "already completed" in res.warnings[0]


@pytest.mark.asyncio
async def test_simulate_delay_invalid_inputs(session: AsyncSession) -> None:
    project, version, _, _, _ = await _seed_scenario_network(session)

    with pytest.raises(ValueError, match="not found"):
        await simulate_activity_delay(
            session=session,
            project_id=project.id,
            version_id=version.id,
            activity_source_id="NON-EXISTENT-ACT",
            delay_value=5.0,
        )

    with pytest.raises(ValueError, match="greater than zero"):
        await simulate_activity_delay(
            session=session,
            project_id=project.id,
            version_id=version.id,
            activity_source_id="A-PIPE",
            delay_value=-2.0,
        )
