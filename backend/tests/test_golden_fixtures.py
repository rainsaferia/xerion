"""Tests for golden schedule fixtures and ground-truth calculations (PI-052)."""

import json
from collections.abc import AsyncGenerator
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from app.domains.schedule.comparison import compare_versions
from app.domains.schedule.float_analysis import compute_float_distribution
from app.domains.schedule.metrics import compute_project_overview_metrics
from app.models.auth import User, Workspace
from app.models.base import Base
from app.models.project import ImportJob, Project, ProjectVersion, UploadedFile
from app.models.schedule import Activity, ActivityRelationship
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "golden_schedules"


@pytest.fixture
def golden_rev0_data() -> dict[str, Any]:
    with open(FIXTURE_DIR / "epc_rev0_baseline.json", encoding="utf-8") as f:
        data: dict[str, Any] = json.load(f)
        return data


@pytest.fixture
def golden_rev1_data() -> dict[str, Any]:
    with open(FIXTURE_DIR / "epc_rev1_progress.json", encoding="utf-8") as f:
        data: dict[str, Any] = json.load(f)
        return data


@pytest.fixture
def golden_expected() -> dict[str, Any]:
    with open(FIXTURE_DIR / "expected_calculations.json", encoding="utf-8") as f:
        data: dict[str, Any] = json.load(f)
        return data


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


async def _populate_version_from_fixture(
    session: AsyncSession,
    project: Project,
    fixture_data: dict[str, Any],
    version_num: int,
) -> ProjectVersion:
    upload = UploadedFile(
        workspace_id=project.workspace_id,
        project_id=project.id,
        original_filename=f"rev{version_num}.xer",
        object_key=f"uploads/{project.id}/rev{version_num}.xer",
        source_format="xer",
        file_size_bytes=1024,
        sha256_checksum=f"{version_num}" * 64,
    )
    session.add(upload)
    await session.flush()

    job = ImportJob(
        workspace_id=project.workspace_id,
        project_id=project.id,
        uploaded_file_id=upload.id,
        status="confirmed",
    )
    session.add(job)
    await session.flush()

    version = ProjectVersion(
        workspace_id=project.workspace_id,
        project_id=project.id,
        import_job_id=job.id,
        version_number=version_num,
        version_label=fixture_data["version_label"],
        source_format="xer",
        status="ready",
    )
    session.add(version)
    await session.flush()

    act_map: dict[str, Activity] = {}
    for item in fixture_data["activities"]:
        p_start = date.fromisoformat(item["planned_start"]) if item["planned_start"] else None
        p_finish = date.fromisoformat(item["planned_finish"]) if item["planned_finish"] else None
        a_start = date.fromisoformat(item["actual_start"]) if item.get("actual_start") else None
        a_finish = date.fromisoformat(item["actual_finish"]) if item.get("actual_finish") else None
        s_date = a_start or p_start
        f_date = a_finish or p_finish

        act = Activity(
            workspace_id=project.workspace_id,
            project_id=project.id,
            project_version_id=version.id,
            source_activity_id=item["source_activity_id"],
            activity_code=item["activity_code"],
            activity_name=item["activity_name"],
            status=item["status"],
            planned_start=p_start,
            planned_finish=p_finish,
            start_date=s_date,
            finish_date=f_date,
            actual_start=a_start,
            actual_finish=a_finish,
            total_float_hours=item["total_float_hours"],
            free_float_hours=item["free_float_hours"],
            original_duration_hours=item["original_duration_hours"],
            remaining_duration_hours=item["remaining_duration_hours"],
            physical_pct_complete=item["physical_pct_complete"],
        )
        session.add(act)
        act_map[item["source_activity_id"]] = act

    await session.flush()

    for rel in fixture_data["relationships"]:
        pred = act_map.get(rel["predecessor_source_id"])
        succ = act_map.get(rel["successor_source_id"])
        if pred and succ:
            r = ActivityRelationship(
                workspace_id=project.workspace_id,
                project_id=project.id,
                project_version_id=version.id,
                predecessor_activity_id=pred.id,
                successor_activity_id=succ.id,
                relationship_type=rel["relationship_type"],
                lag_hours=rel.get("lag_hours", 0.0),
            )
            session.add(r)

    await session.commit()
    return version


async def test_golden_fixtures_overview_metrics(
    session: AsyncSession,
    golden_rev0_data: dict[str, Any],
    golden_rev1_data: dict[str, Any],
    golden_expected: dict[str, Any],
) -> None:
    user = User(
        auth_subject="auth0|golden-test",
        email="golden@epc.test",
        display_name="Golden Test User",
    )
    session.add(user)
    await session.flush()

    workspace = Workspace(name="EPC Test WS", owner_user_id=user.id)
    session.add(workspace)
    await session.flush()

    project = Project(
        workspace_id=workspace.id,
        name="Golden EPC Project",
    )
    session.add(project)
    await session.flush()

    v0 = await _populate_version_from_fixture(session, project, golden_rev0_data, 1)
    v1 = await _populate_version_from_fixture(session, project, golden_rev1_data, 2)

    # 1. Overview metrics test against ground truth
    m0 = await compute_project_overview_metrics(session, project.id, v0.id)
    assert m0.total_activities == golden_expected["rev0"]["total_activities"]
    exp_rev0_status = golden_expected["rev0"]["status_counts"]
    assert m0.status_distribution.not_started == exp_rev0_status["not_started"]
    assert m0.status_distribution.complete == exp_rev0_status["complete"]

    m1 = await compute_project_overview_metrics(session, project.id, v1.id)
    assert m1.total_activities == golden_expected["rev1"]["total_activities"]
    exp_rev1_status = golden_expected["rev1"]["status_counts"]
    assert m1.status_distribution.in_progress == exp_rev1_status["in_progress"]
    assert m1.status_distribution.complete == exp_rev1_status["complete"]


async def test_golden_fixtures_float_and_comparison(
    session: AsyncSession,
    golden_rev0_data: dict[str, Any],
    golden_rev1_data: dict[str, Any],
    golden_expected: dict[str, Any],
) -> None:
    user = User(
        auth_subject="auth0|golden-test-2",
        email="golden2@epc.test",
        display_name="Golden Test User 2",
    )
    session.add(user)
    await session.flush()

    workspace = Workspace(name="EPC Test WS 2", owner_user_id=user.id)
    session.add(workspace)
    await session.flush()

    project = Project(
        workspace_id=workspace.id,
        name="Golden EPC Project",
    )
    session.add(project)
    await session.flush()

    v0 = await _populate_version_from_fixture(session, project, golden_rev0_data, 1)
    v1 = await _populate_version_from_fixture(session, project, golden_rev1_data, 2)

    # 2. Float distribution test
    f0 = await compute_float_distribution(session, project.id, v0.id)
    band_map_0 = {b.name: b for b in f0.bands}
    assert band_map_0["negative"].count == golden_expected["rev0"]["float_distribution"]["negative"]

    f1 = await compute_float_distribution(session, project.id, v1.id)
    band_map_1 = {b.name: b for b in f1.bands}
    assert band_map_1["negative"].count == golden_expected["rev1"]["float_distribution"]["negative"]

    # 3. Version comparison test
    comp = await compare_versions(session, project.id, v0.id, v1.id)
    assert comp.summary.matched == golden_expected["comparison"]["matched"]
    assert comp.summary.added == golden_expected["comparison"]["added"]
    assert comp.summary.removed == golden_expected["comparison"]["removed"]
    added_items = [i for i in comp.items if i.diff_category == "added"]
    exp_added_codes = golden_expected["comparison"]["added_codes"]
    assert [i.activity_code for i in added_items] == exp_added_codes
