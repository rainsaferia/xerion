"""Unit tests for float distribution and critical exposure domain service (PI-032).

Acceptance criteria:
- Threshold is explicit/configurable.
- Negative, zero, and near-critical bands are separated.
- Output labels imported source float vs recalculated value.
- Tests include missing float and unit conversion.
"""

import uuid
from collections.abc import AsyncGenerator
from datetime import date

import pytest
from app.domains.schedule.float_analysis import (
    compute_float_distribution,
    get_critical_exposure_activities,
)
from app.models.auth import User, Workspace
from app.models.base import Base
from app.models.project import ImportJob, Project, ProjectVersion, UploadedFile
from app.models.schedule import Activity
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


async def _seed_schedule_with_floats(
    session: AsyncSession,
) -> tuple[Project, ProjectVersion, list[Activity]]:
    user = User(
        id=uuid.uuid4(),
        auth_subject="auth0|float-user",
        email="float.user@epc-intel.test",
        display_name="Float Test User",
    )
    workspace = Workspace(
        id=uuid.uuid4(),
        name="Float Test Workspace",
        owner_user_id=user.id,
    )
    session.add_all([user, workspace])
    await session.flush()

    project = Project(
        id=uuid.uuid4(),
        workspace_id=workspace.id,
        name="Float Analysis Project",
        project_code="FLOAT-01",
    )
    session.add(project)
    await session.flush()

    upload = UploadedFile(
        id=uuid.uuid4(),
        workspace_id=workspace.id,
        project_id=project.id,
        original_filename="schedule_with_floats.xer",
        object_key="uploads/schedule_with_floats.xer",
        source_format="xer",
        file_size_bytes=4096,
        sha256_checksum="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
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
        version_label="V1",
        source_format="xer",
        data_date=date(2026, 4, 1),
        status="ready",
    )
    session.add(version)
    await session.flush()

    project.latest_version_id = version.id
    await session.flush()

    activities = [
        # 1. Negative float: -16.0h (-2 days @ 8h/d)
        Activity(
            id=uuid.uuid4(),
            workspace_id=workspace.id,
            project_id=project.id,
            project_version_id=version.id,
            source_activity_id="ACT-NEG",
            activity_code="ACT-NEG",
            activity_name="Delayed Critical Piping",
            status="in_progress",
            planned_start=date(2026, 4, 1),
            planned_finish=date(2026, 4, 20),
            total_float_hours=-16.0,
            free_float_hours=0.0,
        ),
        # 2. Zero float: 0.0h (0 days)
        Activity(
            id=uuid.uuid4(),
            workspace_id=workspace.id,
            project_id=project.id,
            project_version_id=version.id,
            source_activity_id="ACT-ZERO",
            activity_code="ACT-ZERO",
            activity_name="Turbine Alignment",
            status="not_started",
            planned_start=date(2026, 4, 10),
            planned_finish=date(2026, 5, 1),
            total_float_hours=0.0,
            free_float_hours=0.0,
        ),
        # 3. Near-critical: 40.0h (5 days @ 8h/d)
        Activity(
            id=uuid.uuid4(),
            workspace_id=workspace.id,
            project_id=project.id,
            project_version_id=version.id,
            source_activity_id="ACT-NEAR",
            activity_code="ACT-NEAR",
            activity_name="Cable Pulling",
            status="not_started",
            planned_start=date(2026, 4, 15),
            planned_finish=date(2026, 5, 10),
            total_float_hours=40.0,
            free_float_hours=8.0,
        ),
        # 4. Low float: 120.0h (15 days @ 8h/d)
        Activity(
            id=uuid.uuid4(),
            workspace_id=workspace.id,
            project_id=project.id,
            project_version_id=version.id,
            source_activity_id="ACT-LOW",
            activity_code="ACT-LOW",
            activity_name="Instrument Calibration",
            status="not_started",
            planned_start=date(2026, 5, 1),
            planned_finish=date(2026, 5, 20),
            total_float_hours=120.0,
            free_float_hours=40.0,
        ),
        # 5. High float: 320.0h (40 days @ 8h/d)
        Activity(
            id=uuid.uuid4(),
            workspace_id=workspace.id,
            project_id=project.id,
            project_version_id=version.id,
            source_activity_id="ACT-HIGH",
            activity_code="ACT-HIGH",
            activity_name="Site Landscaping",
            status="not_started",
            planned_start=date(2026, 6, 1),
            planned_finish=date(2026, 6, 30),
            total_float_hours=320.0,
            free_float_hours=160.0,
        ),
        # 6. Missing float: None (unavailable, e.g. milestone or loose unlinked task)
        Activity(
            id=uuid.uuid4(),
            workspace_id=workspace.id,
            project_id=project.id,
            project_version_id=version.id,
            source_activity_id="ACT-NOFLOAT",
            activity_code="ACT-NOFLOAT",
            activity_name="Level of Effort Support",
            status="in_progress",
            planned_start=date(2026, 4, 1),
            planned_finish=date(2026, 7, 1),
            total_float_hours=None,
            free_float_hours=None,
        ),
    ]

    session.add_all(activities)
    await session.commit()
    return project, version, activities


@pytest.mark.asyncio
async def test_float_distribution_bands_and_source_label(session: AsyncSession) -> None:
    """Verify float bands separation, total counts, and imported source labeling."""
    project, version, _ = await _seed_schedule_with_floats(session)

    res = await compute_float_distribution(
        session=session,
        project_id=project.id,
        version_id=version.id,
        critical_threshold_hours=0.0,
        near_critical_threshold_hours=80.0,
        hours_per_day=8.0,
    )

    assert res.project_id == project.id
    assert res.version_id == version.id
    # Rule: imported float must be labeled as imported source value
    assert res.float_source == "imported_source"
    assert res.method == "source_total_float_threshold"
    assert res.critical_threshold_hours == 0.0
    assert res.near_critical_threshold_hours == 80.0
    assert res.hours_per_day == 8.0

    # Total counts
    assert res.total_activities == 6
    assert res.activities_with_float == 5
    assert res.activities_missing_float == 1
    assert res.min_float_hours == -16.0
    assert res.max_float_hours == 320.0

    # Bands verification
    band_map = {b.name: b for b in res.bands}
    assert set(band_map.keys()) == {
        "negative",
        "zero",
        "near_critical",
        "low_float",
        "high_float",
        "missing",
    }

    assert band_map["negative"].count == 1
    assert band_map["zero"].count == 1
    assert band_map["near_critical"].count == 1
    assert band_map["low_float"].count == 1
    assert band_map["high_float"].count == 1
    assert band_map["missing"].count == 1

    # Check percentage calculation
    # 1 out of 6 is ~16.67%
    assert round(band_map["negative"].percentage, 2) == 16.67
    assert round(band_map["missing"].percentage, 2) == 16.67


@pytest.mark.asyncio
async def test_float_distribution_custom_thresholds_and_unit_conversion(
    session: AsyncSession,
) -> None:
    """Verify configurable critical/near-critical thresholds and custom hours_per_day."""
    project, version, _ = await _seed_schedule_with_floats(session)

    # When near-critical threshold is lowered to 20h, 40h is now in low_float
    res = await compute_float_distribution(
        session=session,
        project_id=project.id,
        version_id=version.id,
        critical_threshold_hours=0.0,
        near_critical_threshold_hours=20.0,
        hours_per_day=10.0,  # 10 hours per day schedule
    )

    assert res.hours_per_day == 10.0
    band_map = {b.name: b for b in res.bands}
    assert band_map["near_critical"].count == 0
    assert band_map["low_float"].count == 2  # 40h and 120h


@pytest.mark.asyncio
async def test_get_critical_exposure_activities(session: AsyncSession) -> None:
    """Verify listing and filtering activities by float exposure bands."""
    project, version, _ = await _seed_schedule_with_floats(session)

    # All exposed (negative, zero, near-critical <= 80h)
    exposed_res = await get_critical_exposure_activities(
        session=session,
        project_id=project.id,
        version_id=version.id,
        band="all_exposed",
        critical_threshold_hours=0.0,
        near_critical_threshold_hours=80.0,
        hours_per_day=8.0,
    )
    assert exposed_res.float_source == "imported_source"
    assert exposed_res.total_exposed == 3
    # Ordered by total_float_hours ASC: -16.0, 0.0, 40.0
    items = exposed_res.items
    assert len(items) == 3
    assert items[0].activity_code == "ACT-NEG"
    assert items[0].total_float_hours == -16.0
    assert items[0].total_float_days == -2.0  # -16 / 8.0
    assert items[0].float_band == "negative"
    assert items[0].is_critical is True

    assert items[1].activity_code == "ACT-ZERO"
    assert items[1].total_float_hours == 0.0
    assert items[1].total_float_days == 0.0
    assert items[1].float_band == "zero"
    assert items[1].is_critical is True

    assert items[2].activity_code == "ACT-NEAR"
    assert items[2].total_float_hours == 40.0
    assert items[2].total_float_days == 5.0  # 40 / 8.0
    assert items[2].float_band == "near_critical"
    assert items[2].is_critical is False

    # Filter band: negative only
    neg_res = await get_critical_exposure_activities(
        session=session,
        project_id=project.id,
        version_id=version.id,
        band="negative",
    )
    assert neg_res.total_exposed == 1
    assert neg_res.items[0].activity_code == "ACT-NEG"

    # Filter band: zero only
    zero_res = await get_critical_exposure_activities(
        session=session,
        project_id=project.id,
        version_id=version.id,
        band="zero",
    )
    assert zero_res.total_exposed == 1
    assert zero_res.items[0].activity_code == "ACT-ZERO"

    # Filter band: near_critical only
    near_res = await get_critical_exposure_activities(
        session=session,
        project_id=project.id,
        version_id=version.id,
        band="near_critical",
    )
    assert near_res.total_exposed == 1
    assert near_res.items[0].activity_code == "ACT-NEAR"
