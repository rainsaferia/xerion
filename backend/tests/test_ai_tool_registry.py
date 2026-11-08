"""Unit tests for AI tool registry and argument validators (PI-041).

Acceptance criteria:
- Model cannot supply arbitrary workspace/project scope (server context strictly enforced).
- Tool definitions conform to OpenAI function calling JSON schema.
- Tool arguments are validated before execution.
- Execution captures status, duration, output summary, and evidence refs.
"""

import uuid
from collections.abc import AsyncGenerator
from datetime import date

import pytest
from app.domains.ai.schemas import (
    GetCriticalActivitiesArgs,
    ListActivitiesArgs,
    ToolExecutionResult,
)
from app.domains.ai.tools import (
    TOOL_DEFINITIONS,
    execute_tool,
    validate_tool_arguments,
)
from app.models.auth import User, Workspace
from app.models.base import Base
from app.models.project import ImportJob, Project, ProjectVersion, UploadedFile
from app.models.schedule import Activity, ActivityRelationship
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


async def _seed_tool_test_schedule(
    session: AsyncSession,
) -> tuple[Project, ProjectVersion]:
    user = User(
        id=uuid.uuid4(),
        auth_subject="auth0|tool-user",
        email="tool.user@epc-intel.test",
        display_name="Tool Engineer",
    )
    workspace = Workspace(
        id=uuid.uuid4(),
        name="Tool Test Workspace",
        owner_user_id=user.id,
    )
    session.add_all([user, workspace])
    await session.flush()

    project = Project(
        id=uuid.uuid4(),
        workspace_id=workspace.id,
        name="Tool Verification Project",
        project_code="TOOL-01",
    )
    session.add(project)
    await session.flush()

    upload = UploadedFile(
        id=uuid.uuid4(),
        workspace_id=workspace.id,
        project_id=project.id,
        original_filename="tool_test.xer",
        object_key="uploads/tool_test.xer",
        source_format="xer",
        file_size_bytes=2048,
        sha256_checksum="hash_tool_test",
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
        data_date=date(2026, 1, 1),
        status="ready",
    )
    session.add(version)
    await session.flush()

    act1 = Activity(
        id=uuid.uuid4(),
        workspace_id=workspace.id,
        project_id=project.id,
        project_version_id=version.id,
        source_activity_id="ACT-CRIT",
        activity_code="A1010",
        activity_name="Critical Foundation Work",
        status="in_progress",
        planned_start=date(2026, 1, 5),
        planned_finish=date(2026, 1, 25),
        total_float_hours=0.0,
        free_float_hours=0.0,
    )
    act2 = Activity(
        id=uuid.uuid4(),
        workspace_id=workspace.id,
        project_id=project.id,
        project_version_id=version.id,
        source_activity_id="ACT-FLOAT",
        activity_code="A1020",
        activity_name="Non-Critical Site Access",
        status="not_started",
        planned_start=date(2026, 1, 26),
        planned_finish=date(2026, 2, 10),
        total_float_hours=120.0,
        free_float_hours=40.0,
    )
    session.add_all([act1, act2])
    await session.flush()

    rel = ActivityRelationship(
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

    return project, version


def test_tool_definitions_structure() -> None:
    """Verify tool definitions contain valid schemas and required names."""
    tool_names = {t["function"]["name"] for t in TOOL_DEFINITIONS}
    expected_tools = {
        "get_project_overview",
        "list_activities",
        "get_activity_detail",
        "get_activity_relationships",
        "get_critical_activities",
        "get_float_distribution",
        "analyze_schedule_quality",
        "compare_project_versions",
    }
    assert expected_tools.issubset(tool_names)

    for tool in TOOL_DEFINITIONS:
        assert tool["type"] == "function"
        fn = tool["function"]
        assert "name" in fn
        assert "description" in fn
        assert "parameters" in fn
        assert fn["parameters"]["type"] == "object"


def test_validate_tool_arguments() -> None:
    """Test validation of JSON and dict tool arguments."""
    # Valid dict
    args1 = validate_tool_arguments("get_critical_activities", {"float_threshold_hours": 16.0})
    assert isinstance(args1, GetCriticalActivitiesArgs)
    assert args1.float_threshold_hours == 16.0

    # Valid JSON string
    args2 = validate_tool_arguments("list_activities", '{"q": "Foundation", "limit": 10}')
    assert isinstance(args2, ListActivitiesArgs)
    assert args2.q == "Foundation"
    assert args2.limit == 10

    # Invalid arguments should raise ValueError
    with pytest.raises(ValueError, match="Invalid arguments"):
        validate_tool_arguments(
            "get_critical_activities", {"float_threshold_hours": "not-a-number"}
        )


@pytest.mark.asyncio
async def test_execute_tool_overview(session: AsyncSession) -> None:
    """Test executing get_project_overview via tool dispatcher."""
    project, version = await _seed_tool_test_schedule(session)

    res: ToolExecutionResult = await execute_tool(
        session=session,
        project_id=project.id,
        version_id=version.id,
        tool_name="get_project_overview",
        arguments={},
    )

    assert res.status == "completed"
    assert res.tool_name == "get_project_overview"
    assert res.duration_ms >= 0
    assert res.summary["total_activities"] == 2
    assert res.summary["data_date"] == "2026-01-01"


@pytest.mark.asyncio
async def test_execute_tool_critical_activities(session: AsyncSession) -> None:
    """Test executing get_critical_activities with server context injection."""
    project, version = await _seed_tool_test_schedule(session)

    res: ToolExecutionResult = await execute_tool(
        session=session,
        project_id=project.id,
        version_id=version.id,
        tool_name="get_critical_activities",
        arguments={"float_threshold_hours": 0.0},
    )

    assert res.error is None
    assert res.status == "completed"
    assert res.summary["total_exposed"] == 1
    items = res.data["items"]
    assert len(items) == 1
    assert items[0]["activity_code"] == "A1010"


@pytest.mark.asyncio
async def test_execute_tool_unknown_name(session: AsyncSession) -> None:
    """Test that executing an unknown tool returns a failed result gracefully."""
    project, version = await _seed_tool_test_schedule(session)

    res: ToolExecutionResult = await execute_tool(
        session=session,
        project_id=project.id,
        version_id=version.id,
        tool_name="non_existent_tool",
        arguments={},
    )

    assert res.status == "failed"
    assert "Unknown tool" in (res.error or "")
