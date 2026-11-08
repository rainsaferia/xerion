"""Unit tests for AI export_activity_data tool execution and evidence generation (PI-047)."""

import uuid
from collections.abc import AsyncGenerator
from datetime import date

import pytest
from app.domains.ai.schemas import ExportActivityDataArgs
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
        auth_subject="auth0|ai-exp-user",
        email="ai.exp@epc.test",
        display_name="AI Export User",
    )
    workspace = Workspace(
        id=uuid.uuid4(),
        name="AI Export Workspace",
        owner_user_id=user.id,
    )
    project = Project(
        id=uuid.uuid4(),
        workspace_id=workspace.id,
        name="LNG Liquefaction Train",
        project_code="LNG-TR-01",
    )
    session.add_all([user, workspace, project])
    await session.flush()

    upload = UploadedFile(
        id=uuid.uuid4(),
        workspace_id=workspace.id,
        project_id=project.id,
        original_filename="schedule.xer",
        object_key="uploads/schedule.xer",
        source_format="xer",
        file_size_bytes=1024,
        sha256_checksum="beef" * 16,
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
        version_label="Rev 0",
        data_date=date(2026, 6, 1),
    )
    session.add(version)
    await session.flush()

    project.latest_version_id = version.id
    session.add(project)

    act1 = Activity(
        id=uuid.uuid4(),
        workspace_id=workspace.id,
        project_id=project.id,
        project_version_id=version.id,
        source_activity_id="ACT-001",
        activity_code="CIVIL-01",
        activity_name="Site Foundation",
        status="in_progress",
        planned_start=date(2026, 6, 2),
        planned_finish=date(2026, 6, 20),
        total_float_hours=0.0,
    )
    act2 = Activity(
        id=uuid.uuid4(),
        workspace_id=workspace.id,
        project_id=project.id,
        project_version_id=version.id,
        source_activity_id="ACT-002",
        activity_code="ELEC-01",
        activity_name="Cabling",
        status="not_started",
        planned_start=date(2026, 6, 21),
        planned_finish=date(2026, 7, 10),
        total_float_hours=48.0,
    )
    session.add_all([act1, act2])
    await session.commit()

    return project, version


def test_export_activity_data_definition_and_validation() -> None:
    defn = get_tool_definition("export_activity_data")
    assert defn is not None
    assert defn["function"]["name"] == "export_activity_data"

    parsed = validate_tool_arguments(
        "export_activity_data",
        {"format": "csv", "critical_only": True},
    )
    assert isinstance(parsed, ExportActivityDataArgs)
    assert parsed.format == "csv"
    assert parsed.critical_only is True

    # Bad format fails validation
    with pytest.raises(ValueError, match="Invalid arguments for tool"):
        validate_tool_arguments(
            "export_activity_data",
            {"format": "invalid_doc"},
        )


async def test_execute_export_activity_data_tool(session: AsyncSession) -> None:
    project, version = await _seed_schedule(session)

    saved_files: dict[str, bytes] = {}

    async def mock_storage_put(key: str, data: bytes, content_type: str) -> None:
        saved_files[key] = data

    result = await execute_tool(
        session=session,
        tool_name="export_activity_data",
        arguments={"format": "csv", "critical_only": True},
        project_id=project.id,
        version_id=version.id,
        user_id=None,
        storage_put_fn=mock_storage_put,
    )

    assert result.status == "completed"
    assert result.tool_name == "export_activity_data"
    assert result.data["output_format"] == "csv"
    assert result.data["status"] == "ready"
    assert len(saved_files) == 1

    # Verify evidence citations
    assert len(result.evidence_refs) == 1
    ev = result.evidence_refs[0]
    assert ev["entity_type"] == "export_artifact"
    assert ev["method"] == "tabular_csv_export"
    assert f"[EV: export/{result.data['id']} status=ready format=csv]" in ev["citation_label"]
