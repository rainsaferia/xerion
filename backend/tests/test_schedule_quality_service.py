"""Unit tests for schedule quality check domain service (PI-033).

Acceptance criteria:
- Implement only explicitly documented checks (missing IDs, duplicate IDs,
  orphan links, invalid date ranges, missing predecessor/successor where applicable).
- Each finding has severity, method, evidence, and limitation.
- UI/Service strictly distinguishes data-quality checks from schedule-performance findings.
- Start milestones and finish milestones are properly handled in open end checks.
- Optional persistence to AnalysisRun and AnalysisFinding.
"""

import uuid
from collections.abc import AsyncGenerator
from datetime import date

import pytest
from app.domains.schedule.quality import (
    run_schedule_quality_checks,
)
from app.models.analytics import AnalysisFinding, AnalysisRun
from app.models.auth import User, Workspace
from app.models.base import Base
from app.models.project import ImportJob, Project, ProjectVersion, UploadedFile
from app.models.schedule import Activity, ActivityRelationship
from sqlalchemy import event, select
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


async def _seed_quality_test_schedule(
    session: AsyncSession,
) -> tuple[Project, ProjectVersion, list[Activity], list[ActivityRelationship]]:
    user = User(
        id=uuid.uuid4(),
        auth_subject="auth0|quality-user",
        email="quality.user@epc-intel.test",
        display_name="Quality Auditor",
    )
    workspace = Workspace(
        id=uuid.uuid4(),
        name="Quality Workspace",
        owner_user_id=user.id,
    )
    session.add_all([user, workspace])
    await session.flush()

    project = Project(
        id=uuid.uuid4(),
        workspace_id=workspace.id,
        name="Quality Test Project",
        project_code="QUAL-01",
    )
    session.add(project)
    await session.flush()

    upload = UploadedFile(
        id=uuid.uuid4(),
        workspace_id=workspace.id,
        project_id=project.id,
        original_filename="quality_schedule.xer",
        object_key="uploads/quality_schedule.xer",
        source_format="xer",
        file_size_bytes=4096,
        sha256_checksum="hash_quality_test",
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
        data_date=date(2026, 6, 1),
        status="ready",
    )
    session.add(version)
    await session.flush()

    project.latest_version_id = version.id
    await session.flush()

    # 1. Normal Start Milestone (no predecessors is normal for start milestone)
    start_mile = Activity(
        id=uuid.uuid4(),
        workspace_id=workspace.id,
        project_id=project.id,
        project_version_id=version.id,
        source_activity_id="SM-01",
        activity_code="M-START",
        activity_name="Project Notice to Proceed",
        activity_type="start_milestone",
        status="complete",
        planned_start=date(2026, 6, 1),
        planned_finish=date(2026, 6, 1),
        total_float_hours=0.0,
    )

    # 2. Activity with invalid date range (planned finish before planned start)
    invalid_dates = Activity(
        id=uuid.uuid4(),
        workspace_id=workspace.id,
        project_id=project.id,
        project_version_id=version.id,
        source_activity_id="ACT-INV-DATE",
        activity_code="ACT-INV-DATE",
        activity_name="Inverted Engineering Study",
        activity_type="task",
        status="not_started",
        planned_start=date(2026, 6, 15),
        planned_finish=date(2026, 6, 10),  # Error!
        total_float_hours=40.0,
    )

    # 3. Activity with negative float (schedule performance issue)
    neg_float = Activity(
        id=uuid.uuid4(),
        workspace_id=workspace.id,
        project_id=project.id,
        project_version_id=version.id,
        source_activity_id="ACT-NEG-FLOAT",
        activity_code="ACT-NEG-FLOAT",
        activity_name="Delayed Foundations Pour",
        activity_type="task",
        status="in_progress",
        planned_start=date(2026, 6, 5),
        planned_finish=date(2026, 6, 25),
        total_float_hours=-24.0,  # Critical delay
    )

    # 4. Activity with high float (schedule performance issue: unconstrained or loose)
    high_float = Activity(
        id=uuid.uuid4(),
        workspace_id=workspace.id,
        project_id=project.id,
        project_version_id=version.id,
        source_activity_id="ACT-HIGH-FLOAT",
        activity_code="ACT-HIGH-FLOAT",
        activity_name="Optional Facility Landscaping",
        activity_type="task",
        status="not_started",
        planned_start=date(2026, 7, 1),
        planned_finish=date(2026, 7, 20),
        total_float_hours=480.0,  # 60 working days
    )

    # 5. Activity with duplicate activity code (first)
    dup1 = Activity(
        id=uuid.uuid4(),
        workspace_id=workspace.id,
        project_id=project.id,
        project_version_id=version.id,
        source_activity_id="ACT-DUP-A",
        activity_code="DUP-CODE-01",
        activity_name="First Duplicate Activity",
        activity_type="task",
        status="not_started",
        planned_start=date(2026, 6, 10),
        planned_finish=date(2026, 6, 20),
        total_float_hours=80.0,
    )

    # 6. Activity with duplicate activity code (second)
    dup2 = Activity(
        id=uuid.uuid4(),
        workspace_id=workspace.id,
        project_id=project.id,
        project_version_id=version.id,
        source_activity_id="ACT-DUP-B",
        activity_code="DUP-CODE-01",  # Same code!
        activity_name="Second Duplicate Activity",
        activity_type="task",
        status="not_started",
        planned_start=date(2026, 6, 10),
        planned_finish=date(2026, 6, 20),
        total_float_hours=80.0,
    )

    # 7. Activity with missing activity code / blank identifier
    missing_id = Activity(
        id=uuid.uuid4(),
        workspace_id=workspace.id,
        project_id=project.id,
        project_version_id=version.id,
        source_activity_id="",  # Blank
        activity_code=None,  # Null
        activity_name="Orphan Activity Missing ID",
        activity_type="task",
        status="not_started",
        planned_start=date(2026, 6, 10),
        planned_finish=date(2026, 6, 20),
        total_float_hours=80.0,
    )

    # 8. Activity with Open Start (task with no predecessors)
    open_start_task = Activity(
        id=uuid.uuid4(),
        workspace_id=workspace.id,
        project_id=project.id,
        project_version_id=version.id,
        source_activity_id="ACT-OPEN-START",
        activity_code="ACT-OPEN-START",
        activity_name="Dangling Start Civil Work",
        activity_type="task",
        status="not_started",
        planned_start=date(2026, 6, 10),
        planned_finish=date(2026, 6, 20),
        total_float_hours=80.0,
    )

    # 9. Activity with Open Finish (task with no successors)
    open_finish_task = Activity(
        id=uuid.uuid4(),
        workspace_id=workspace.id,
        project_id=project.id,
        project_version_id=version.id,
        source_activity_id="ACT-OPEN-FINISH",
        activity_code="ACT-OPEN-FINISH",
        activity_name="Dangling End Piping Work",
        activity_type="task",
        status="not_started",
        planned_start=date(2026, 6, 10),
        planned_finish=date(2026, 6, 20),
        total_float_hours=80.0,
    )

    # 10. Finish Milestone (no successors is normal for finish milestone)
    finish_mile = Activity(
        id=uuid.uuid4(),
        workspace_id=workspace.id,
        project_id=project.id,
        project_version_id=version.id,
        source_activity_id="FM-01",
        activity_code="M-FINISH",
        activity_name="Project Final Handover",
        activity_type="finish_milestone",
        status="not_started",
        planned_start=date(2026, 7, 30),
        planned_finish=date(2026, 7, 30),
        total_float_hours=0.0,
    )

    activities = [
        start_mile,
        invalid_dates,
        neg_float,
        high_float,
        dup1,
        dup2,
        missing_id,
        open_start_task,
        open_finish_task,
        finish_mile,
    ]
    session.add_all(activities)
    await session.flush()

    # Relationships
    # Link start_mile -> invalid_dates -> finish_mile
    rel1 = ActivityRelationship(
        id=uuid.uuid4(),
        workspace_id=workspace.id,
        project_id=project.id,
        project_version_id=version.id,
        predecessor_activity_id=start_mile.id,
        successor_activity_id=invalid_dates.id,
        relationship_type="FS",
    )
    rel2 = ActivityRelationship(
        id=uuid.uuid4(),
        workspace_id=workspace.id,
        project_id=project.id,
        project_version_id=version.id,
        predecessor_activity_id=invalid_dates.id,
        successor_activity_id=finish_mile.id,
        relationship_type="FS",
    )
    # Link start_mile -> open_finish_task (has predecessor, but no successor)
    rel3 = ActivityRelationship(
        id=uuid.uuid4(),
        workspace_id=workspace.id,
        project_id=project.id,
        project_version_id=version.id,
        predecessor_activity_id=start_mile.id,
        successor_activity_id=open_finish_task.id,
        relationship_type="FS",
    )
    # Link open_start_task -> finish_mile (has successor, but no predecessor)
    rel4 = ActivityRelationship(
        id=uuid.uuid4(),
        workspace_id=workspace.id,
        project_id=project.id,
        project_version_id=version.id,
        predecessor_activity_id=open_start_task.id,
        successor_activity_id=finish_mile.id,
        relationship_type="FS",
    )

    job2 = ImportJob(
        id=uuid.uuid4(),
        workspace_id=workspace.id,
        project_id=project.id,
        uploaded_file_id=upload.id,
        status="confirmed",
    )
    session.add(job2)
    await session.flush()

    # Version 2 for another baseline/snapshot
    version_other = ProjectVersion(
        id=uuid.uuid4(),
        workspace_id=workspace.id,
        project_id=project.id,
        import_job_id=job2.id,
        version_number=2,
        version_label="V2",
        source_format="xer",
        data_date=date(2026, 7, 1),
        status="ready",
    )
    other_act = Activity(
        id=uuid.uuid4(),
        workspace_id=workspace.id,
        project_id=project.id,
        project_version_id=version_other.id,
        source_activity_id="ACT-V2-EXT",
        activity_code="ACT-V2-EXT",
        activity_name="Foreign Version Task",
        status="not_started",
        planned_start=date(2026, 7, 1),
        planned_finish=date(2026, 7, 10),
    )
    session.add_all([version_other, other_act])
    await session.flush()

    # 11. Orphan relationship: pointing to activity from a different version
    orphan_rel = ActivityRelationship(
        id=uuid.uuid4(),
        workspace_id=workspace.id,
        project_id=project.id,
        project_version_id=version.id,
        predecessor_activity_id=other_act.id,  # Exists in DB, but NOT in version 1!
        successor_activity_id=neg_float.id,
        relationship_type="FS",
        is_external=False,
    )

    relationships = [rel1, rel2, rel3, rel4, orphan_rel]
    session.add_all(relationships)
    await session.commit()

    return project, version, activities, relationships


@pytest.mark.asyncio
async def test_run_schedule_quality_checks_findings_and_categories(
    session: AsyncSession,
) -> None:
    """Verify quality check execution strictly separates data-quality vs schedule-performance."""
    project, version, _, _ = await _seed_quality_test_schedule(session)

    report = await run_schedule_quality_checks(
        session=session,
        project_id=project.id,
        version_id=version.id,
        persist=True,
    )

    assert report.project_id == project.id
    assert report.version_id == version.id
    assert report.summary.total_findings > 0

    # Verify summary distinguishes categories
    assert report.summary.data_quality_count > 0
    assert report.summary.schedule_performance_count > 0
    assert (
        report.summary.total_findings
        == report.summary.data_quality_count + report.summary.schedule_performance_count
    )

    check_codes = {f.check_code for f in report.findings}

    # Data Quality findings expected:
    assert "missing_activity_identifier" in check_codes
    assert "duplicate_activity_identifier" in check_codes
    assert "orphan_relationships" in check_codes
    assert "invalid_date_range" in check_codes
    assert "missing_predecessors" in check_codes
    assert "missing_successors" in check_codes

    # Schedule Performance findings expected:
    assert "negative_float" in check_codes
    assert "high_float" in check_codes

    # Verify every single finding adheres to strict audit criteria
    for f in report.findings:
        assert f.severity in ("info", "low", "medium", "high", "critical")
        assert f.category in ("data_quality", "schedule_performance")
        assert len(f.method) > 0, "Finding must disclose method"
        assert len(f.limitation) > 0, "Finding must disclose limitation"
        assert isinstance(f.evidence, list), "Evidence must be a structured list"
        assert len(f.evidence) > 0, "Evidence must not be empty"

    # Start milestone and Finish milestone should NOT be flagged as missing logic
    open_start_codes = [
        f.entity_source_id for f in report.findings if f.check_code == "missing_predecessors"
    ]
    assert "SM-01" not in open_start_codes, "Start milestone must not be flagged for open start"

    open_finish_codes = [
        f.entity_source_id for f in report.findings if f.check_code == "missing_successors"
    ]
    assert "FM-01" not in open_finish_codes, "Finish milestone must not be flagged for open finish"

    # Verify persistence into AnalysisRun and AnalysisFinding
    assert report.run_id is not None
    run = await session.get(AnalysisRun, report.run_id)
    assert run is not None
    assert run.analysis_type == "schedule_quality"
    assert run.status == "completed"

    stored_findings = (
        await session.scalars(
            select(AnalysisFinding).where(AnalysisFinding.analysis_run_id == report.run_id)
        )
    ).all()
    assert len(stored_findings) == report.summary.total_findings


@pytest.mark.asyncio
async def test_run_selected_checks_without_persist(session: AsyncSession) -> None:
    """Verify selective check execution and running without DB persistence."""
    project, version, _, _ = await _seed_quality_test_schedule(session)

    report = await run_schedule_quality_checks(
        session=session,
        project_id=project.id,
        version_id=version.id,
        selected_checks=["negative_float"],
        persist=False,
    )

    assert report.run_id is None
    assert report.summary.checks_run == ["negative_float"]
    assert report.summary.total_findings == 1
    assert report.summary.data_quality_count == 0
    assert report.summary.schedule_performance_count == 1
    assert report.findings[0].check_code == "negative_float"
    assert report.findings[0].category == "schedule_performance"
