"""Unit tests for Project AI Orchestrator (PI-041).

Acceptance criteria:
- Server context binding: project_id, workspace_id, and version_id strictly enforced.
- Intent routes to approved tools and executes them deterministically.
- Multi-turn tool execution loop resolves tool calls and returns assistant response.
- Conversation history, messages, and tool execution traces are persisted.
"""

import uuid
from collections.abc import AsyncGenerator
from datetime import date

import pytest
from app.adapters.ai.mock_adapter import MockAIProviderAdapter
from app.domains.ai.orchestrator import (
    create_conversation,
    get_conversation,
    list_conversations,
    run_agent_turn,
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


async def _seed_orchestrator_project(
    session: AsyncSession,
) -> tuple[User, Workspace, Project, ProjectVersion]:
    user = User(
        id=uuid.uuid4(),
        auth_subject="auth0|orch-user",
        email="orch.user@epc.test",
        display_name="Orchestrator Lead",
    )
    workspace = Workspace(
        id=uuid.uuid4(),
        name="Orch Workspace",
        owner_user_id=user.id,
    )
    session.add_all([user, workspace])
    await session.flush()

    project = Project(
        id=uuid.uuid4(),
        workspace_id=workspace.id,
        name="Refinery Expansion",
        project_code="REF-01",
    )
    session.add(project)
    await session.flush()

    upload = UploadedFile(
        id=uuid.uuid4(),
        workspace_id=workspace.id,
        project_id=project.id,
        original_filename="refinery.xer",
        object_key="uploads/refinery.xer",
        source_format="xer",
        file_size_bytes=1024,
        sha256_checksum="hash_refinery",
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

    project.latest_version_id = version.id
    await session.flush()

    act = Activity(
        id=uuid.uuid4(),
        workspace_id=workspace.id,
        project_id=project.id,
        project_version_id=version.id,
        source_activity_id="ACT-001",
        activity_code="A100",
        activity_name="Distillation Column Erection",
        status="in_progress",
        total_float_hours=0.0,
    )
    session.add(act)
    await session.commit()

    return user, workspace, project, version


@pytest.mark.asyncio
async def test_conversation_lifecycle(session: AsyncSession) -> None:
    """Test creating, listing, and retrieving conversations."""
    user, workspace, project, version = await _seed_orchestrator_project(session)

    # 1. Create conversation
    conv = await create_conversation(
        session=session,
        workspace_id=workspace.id,
        project_id=project.id,
        user_id=user.id,
        title="Schedule Health Check",
        version_id=version.id,
    )
    assert conv.title == "Schedule Health Check"
    assert conv.project_id == project.id
    assert conv.selected_project_version_id == version.id

    # 2. List conversations
    convs = await list_conversations(session=session, project_id=project.id)
    assert len(convs) == 1
    assert convs[0].id == conv.id

    # 3. Get single conversation
    fetched = await get_conversation(
        session=session, project_id=project.id, conversation_id=conv.id
    )
    assert fetched.id == conv.id
    assert len(fetched.messages) == 0


@pytest.mark.asyncio
async def test_run_agent_turn_with_tool_calling_loop(session: AsyncSession) -> None:
    """Test orchestrator multi-turn loop: LLM invokes tool, tool executes, LLM answers."""
    user, workspace, project, version = await _seed_orchestrator_project(session)

    conv = await create_conversation(
        session=session,
        workspace_id=workspace.id,
        project_id=project.id,
        user_id=user.id,
        title="Critical Path Q&A",
    )

    mock_llm = MockAIProviderAdapter(model="gpt-4o")

    # Turn 1: LLM decides to call `get_critical_activities`
    mock_llm.queue_tool_call(
        name="get_critical_activities",
        arguments={"float_threshold_hours": 0.0},
        call_id="call_crit_123",
        assistant_content="I will check the critical activities for you.",
    )
    # Turn 2: LLM receives tool output and gives final answer
    mock_llm.queue_response(
        content=(
            "Based on the analysis, activity A100 (Distillation Column Erection) "
            "is critical with 0.0 hours float. [EV: A100 total_float_hours=0.0h]"
        )
    )

    result = await run_agent_turn(
        session=session,
        llm_client=mock_llm,
        workspace_id=workspace.id,
        project_id=project.id,
        user_id=user.id,
        conversation_id=conv.id,
        user_message_text="Which activities are currently critical on this project?",
    )

    # Verify agent turn result
    assert result.conversation_id == conv.id
    assert "A100" in (result.message.content or "")
    assert len(result.tool_executions) == 1
    tool_exec = result.tool_executions[0]
    assert tool_exec.tool_name == "get_critical_activities"
    assert tool_exec.status == "completed"
    assert tool_exec.duration_ms is not None
    assert len(tool_exec.evidence_refs) >= 1
    assert result.validation_status in ("verified", "caveated")

    # Verify persistence in DB
    refetched = await get_conversation(
        session=session, project_id=project.id, conversation_id=conv.id
    )
    assert len(refetched.messages) == 2  # User message + Assistant message
    assert refetched.messages[0].role == "user"
    assert (
        refetched.messages[0].content == "Which activities are currently critical on this project?"
    )
    assert refetched.messages[1].role == "assistant"
    assert "A100" in (refetched.messages[1].content or "")
    assert len(refetched.messages[1].tool_executions) == 1
