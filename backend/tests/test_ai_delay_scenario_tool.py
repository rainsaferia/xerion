"""Unit tests for AI simulate_activity_delay tool execution and evidence generation (PI-045).

Acceptance criteria:
- Tool definition exists and adheres to function schema.
- Tool arguments are validated server-side.
- Tool executes deterministic delay scenario and captures status, duration, summary.
- Generates verifiable evidence references with [EV: ...] tags.
"""

import uuid
from collections.abc import AsyncGenerator
from datetime import date

import pytest
from app.domains.ai.evidence import build_tool_evidence
from app.domains.ai.schemas import SimulateActivityDelayArgs
from app.domains.ai.tools import (
    execute_tool,
    get_tool_definition,
    validate_tool_arguments,
)
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


async def _seed_schedule(
    session: AsyncSession,
) -> tuple[Project, ProjectVersion]:
    user = User(
        id=uuid.uuid4(),
        auth_subject="auth0|ai-scen-user",
        email="ai.scen@epc.test",
        display_name="AI Scenario User",
    )
    workspace = Workspace(
        id=uuid.uuid4(),
        name="AI Workspace",
        owner_user_id=user.id,
    )
    session.add_all([user, workspace])
    await session.flush()

    project = Project(
        id=uuid.uuid4(),
        workspace_id=workspace.id,
        name="Offshore Rig Simulation",
        project_code="RIG-SIM-01",
    )
    session.add(project)
    await session.flush()

    upload = UploadedFile(
        id=uuid.uuid4(),
        workspace_id=workspace.id,
        project_id=project.id,
        uploaded_by=user.id,
        original_filename="rig_sim_schedule.xer",
        object_key="rig/sim_schedule.xer",
        source_format="xer",
        file_size_bytes=2048,
        sha256_checksum="5678" * 16,
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
        data_date=date(2026, 5, 1),
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
        source_wbs_id="WBS-RIG-SIM",
        wbs_code="1.0",
        wbs_name="Modules",
    )
    session.add(wbs)
    await session.flush()

    act = Activity(
        id=uuid.uuid4(),
        workspace_id=workspace.id,
        project_id=project.id,
        project_version_id=version.id,
        source_activity_id="MOD-LIFT-01",
        activity_code="A-HEAVY-LIFT",
        activity_name="Heavy Lift Module Installation",
        wbs_node_id=wbs.id,
        activity_type="TT_Task",
        status="in_progress",
        start_date=date(2026, 6, 1),
        finish_date=date(2026, 6, 20),
        original_duration_hours=160.0,
        remaining_duration_hours=80.0,
        total_float_hours=24.0,  # 3 days float
    )
    session.add(act)
    await session.commit()
    return project, version


def test_tool_definition_and_argument_validation() -> None:
    tool_def = get_tool_definition("simulate_activity_delay")
    assert tool_def is not None
    assert tool_def["function"]["name"] == "simulate_activity_delay"

    # Valid arguments
    args = validate_tool_arguments(
        "simulate_activity_delay",
        {
            "activity_source_id": "A-HEAVY-LIFT",
            "delay_value": 5.0,
            "delay_unit": "working_days",
            "scenario_name": "Crane maintenance +5d",
        },
    )
    assert isinstance(args, SimulateActivityDelayArgs)
    assert args.activity_source_id == "A-HEAVY-LIFT"
    assert args.delay_value == 5.0
    assert args.delay_unit == "working_days"
    assert args.scenario_name == "Crane maintenance +5d"

    # Missing required argument
    with pytest.raises(ValueError, match="Invalid arguments for tool"):
        validate_tool_arguments("simulate_activity_delay", {"activity_source_id": "A-LIFT"})


@pytest.mark.asyncio
async def test_execute_tool_simulate_activity_delay(session: AsyncSession) -> None:
    project, version = await _seed_schedule(session)

    res = await execute_tool(
        session=session,
        project_id=project.id,
        version_id=version.id,
        tool_name="simulate_activity_delay",
        arguments={
            "activity_source_id": "A-HEAVY-LIFT",
            "delay_value": 5.0,
            "delay_unit": "working_days",
        },
    )

    assert res.status == "completed"
    assert res.tool_name == "simulate_activity_delay"
    assert res.summary["target_activity_code"] == "A-HEAVY-LIFT"
    assert res.summary["delay_applied_working_days"] == 5.0
    assert res.summary["critical_path_breached"] is True
    assert len(res.evidence_refs) >= 1

    # Check evidence citations
    cit_labels = [ref["citation_label"] for ref in res.evidence_refs]
    assert any("A-HEAVY-LIFT scenario_finish=" in c for c in cit_labels)


def test_build_tool_evidence_delay_scenario() -> None:
    ver_id = uuid.uuid4()
    mock_data = {
        "status": "completed",
        "affected_items": [
            {
                "activity_id": str(uuid.uuid4()),
                "source_activity_id": "MOD-01",
                "activity_code": "A-MOD",
                "source_finish_date": "2026-06-20",
                "scenario_finish_date": "2026-06-27",
                "delay_working_days": 5.0,
            }
        ],
    }

    evidence = build_tool_evidence("simulate_activity_delay", ver_id, mock_data)
    assert len(evidence) == 1

    ev = evidence[0]
    assert ev.source_identifier == "A-MOD"
    assert ev.field_name == "scenario_finish_date"
    assert ev.normalized_value == "2026-06-27"
    assert ev.citation_label == "[EV: A-MOD scenario_finish=2026-06-27 (+5.0d)]"
