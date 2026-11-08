"""Unit tests for AI get_milestone_forecast tool execution and evidence generation (PI-044).

Acceptance criteria:
- Tool definition exists and adheres to function schema.
- Tool arguments are validated server-side.
- Tool executes deterministic forecast engine and captures status, duration, summary.
- Generates verifiable evidence references with [EV: ...] tags.
"""

import uuid
from collections.abc import AsyncGenerator
from datetime import date

import pytest
from app.domains.ai.evidence import build_tool_evidence
from app.domains.ai.schemas import GetMilestoneForecastArgs
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
        auth_subject="auth0|ai-fc-user",
        email="ai.fc@epc.test",
        display_name="AI Forecast User",
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
        name="Offshore Rig Forecast",
        project_code="RIG-001",
    )
    session.add(project)
    await session.flush()

    upload = UploadedFile(
        id=uuid.uuid4(),
        workspace_id=workspace.id,
        project_id=project.id,
        uploaded_by=user.id,
        original_filename="rig_schedule.xer",
        object_key="rig/schedule.xer",
        source_format="xer",
        file_size_bytes=2048,
        sha256_checksum="1234" * 16,
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
        source_wbs_id="WBS-RIG-01",
        wbs_code="1.0",
        wbs_name="Milestones",
    )
    session.add(wbs)
    await session.flush()

    milestone = Activity(
        id=uuid.uuid4(),
        workspace_id=workspace.id,
        project_id=project.id,
        project_version_id=version.id,
        source_activity_id="MS-SAIL",
        activity_code="M-SAILAWAY",
        activity_name="Rig Sailaway",
        wbs_node_id=wbs.id,
        activity_type="finish_milestone",
        status="in_progress",
        finish_date=date(2026, 8, 1),
        original_duration_hours=0.0,
        remaining_duration_hours=0.0,
        total_float_hours=-24.0,  # 3 days slip -> 5 calendar days slip
    )
    session.add(milestone)
    await session.commit()
    return project, version


def test_tool_definition_and_argument_validation() -> None:
    tool_def = get_tool_definition("get_milestone_forecast")
    assert tool_def is not None
    assert tool_def["function"]["name"] == "get_milestone_forecast"

    # Default empty arguments
    args = validate_tool_arguments("get_milestone_forecast", {})
    assert isinstance(args, GetMilestoneForecastArgs)
    assert args.method == "imported_schedule_dates"
    assert args.milestone_id is None

    # Valid arguments
    args2 = validate_tool_arguments(
        "get_milestone_forecast",
        {"method": "deterministic_float_indicator", "milestone_id": "M-SAILAWAY"},
    )
    assert isinstance(args2, GetMilestoneForecastArgs)
    assert args2.method == "deterministic_float_indicator"
    assert args2.milestone_id == "M-SAILAWAY"

    # Invalid method raises error
    with pytest.raises(ValueError, match="Invalid arguments for tool"):
        validate_tool_arguments(
            "get_milestone_forecast",
            {"method": "unsupported_ml_predictor"},
        )


@pytest.mark.asyncio
async def test_execute_tool_milestone_forecast(session: AsyncSession) -> None:
    project, version = await _seed_schedule(session)

    res = await execute_tool(
        session=session,
        project_id=project.id,
        version_id=version.id,
        tool_name="get_milestone_forecast",
        arguments={"method": "deterministic_float_indicator"},
    )

    assert res.status == "completed"
    assert res.tool_name == "get_milestone_forecast"
    assert res.summary["total_milestones"] == 1
    assert res.summary["delayed_or_slipping_milestones"] == 1
    assert res.summary["method"] == "deterministic_float_indicator"
    assert len(res.evidence_refs) >= 1

    # Check evidence citations
    cit_labels = [ref["citation_label"] for ref in res.evidence_refs]
    assert any("M-SAILAWAY forecast=" in c for c in cit_labels)
    assert any("float=-24.0h" in c for c in cit_labels)


def test_build_tool_evidence_milestone_forecast() -> None:
    ver_id = uuid.uuid4()
    mock_data = {
        "method": "deterministic_float_indicator",
        "items": [
            {
                "activity_id": str(uuid.uuid4()),
                "source_activity_id": "MS-01",
                "activity_code": "M-COD",
                "source_date": "2026-10-01",
                "projected_date": "2026-10-15",
                "is_calculated_projection": True,
                "total_float_hours": -80.0,
            }
        ],
    }

    evidence = build_tool_evidence("get_milestone_forecast", ver_id, mock_data)
    assert len(evidence) == 2

    # Date evidence
    date_ev = evidence[0]
    assert date_ev.source_identifier == "M-COD"
    assert date_ev.field_name == "projected_date"
    assert date_ev.normalized_value == "2026-10-15"
    assert date_ev.citation_label == "[EV: M-COD forecast=2026-10-15 (calc)]"

    # Float evidence
    float_ev = evidence[1]
    assert float_ev.source_identifier == "M-COD"
    assert float_ev.field_name == "total_float_hours"
    assert float_ev.source_value == -80.0
    assert float_ev.citation_label == "[EV: M-COD float=-80.0h]"
