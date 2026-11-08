"""Unit tests for AI generate_schedule_report tool execution and evidence generation (PI-046)."""

import uuid
from collections.abc import AsyncGenerator
from datetime import date

import pytest
from app.domains.ai.schemas import GenerateScheduleReportArgs
from app.domains.ai.tools import (
    execute_tool,
    get_tool_definition,
    validate_tool_arguments,
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
        auth_subject="auth0|ai-rep-user",
        email="ai.rep@epc.test",
        display_name="AI Reporting User",
    )
    workspace = Workspace(
        id=uuid.uuid4(),
        name="AI Reporting Workspace",
        owner_user_id=user.id,
    )
    project = Project(
        id=uuid.uuid4(),
        workspace_id=workspace.id,
        name="FPSO Topside Module",
        project_code="FPSO-MOD-01",
    )
    session.add_all([user, workspace, project])
    await session.flush()

    upload = UploadedFile(
        id=uuid.uuid4(),
        workspace_id=workspace.id,
        project_id=project.id,
        original_filename="sample.xer",
        object_key=f"uploads/{uuid.uuid4()}/sample.xer",
        source_format="xer",
        file_size_bytes=2048,
        sha256_checksum="deadbeef" * 8,
        uploaded_by=user.id,
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
        data_date=date(2026, 8, 30),
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
        source_activity_id="ACT-101",
        activity_code="ACT-101",
        activity_name="Engineering Design",
        status="complete",
        activity_type="Task Dependent",
        total_float_hours=0.0,
        start_date=date(2026, 1, 1),
        finish_date=date(2026, 5, 1),
    )
    session.add(act)
    await session.commit()

    return project, version


def test_generate_schedule_report_tool_definition_registered() -> None:
    tool_def = get_tool_definition("generate_schedule_report")
    assert tool_def is not None
    assert tool_def["type"] == "function"
    assert tool_def["function"]["name"] == "generate_schedule_report"
    assert "pdf" in str(tool_def["function"]["description"]).lower()


def test_generate_schedule_report_tool_validation() -> None:
    args = validate_tool_arguments("generate_schedule_report", {"format": "pdf"})
    assert isinstance(args, GenerateScheduleReportArgs)
    assert args.format == "pdf"
    assert args.include_activity_appendix is False


async def test_generate_schedule_report_tool_execution_and_evidence(
    session: AsyncSession,
) -> None:
    project, version = await _seed_schedule(session)

    stored_files: dict[str, bytes] = {}

    async def mock_storage_put(key: str, content: bytes, content_type: str) -> None:
        stored_files[key] = content

    res = await execute_tool(
        session=session,
        project_id=project.id,
        version_id=version.id,
        tool_name="generate_schedule_report",
        arguments={"format": "pdf", "include_activity_appendix": False},
        storage_put_fn=mock_storage_put,
    )

    assert res.status == "completed"
    assert res.tool_name == "generate_schedule_report"
    assert "report_id" in res.summary
    assert res.summary["output_format"] == "pdf"
    assert "id" in res.data
    report_id = res.data["id"]

    assert len(stored_files) == 1
    pdf_bytes = list(stored_files.values())[0]
    assert pdf_bytes.startswith(b"%PDF-")

    # Check evidence citations
    assert len(res.evidence_refs) >= 1
    ev = res.evidence_refs[0]
    assert ev["entity_type"] == "report_artifact"
    assert f"[EV: report/{report_id}" in ev["citation_label"]
    assert "format=pdf" in ev["citation_label"]
