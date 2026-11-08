"""Integration tests for AI conversation and agent endpoints (PI-041).

Acceptance criteria:
- POST /api/v1/projects/{project_id}/ai/conversations
- GET /api/v1/projects/{project_id}/ai/conversations
- GET /api/v1/projects/{project_id}/ai/conversations/{conversation_id}
- POST /api/v1/projects/{project_id}/ai/conversations/{conversation_id}/messages
- Tenant isolation guard: ProjectAccess (cross-tenant 404).
"""

import tempfile
import time
import uuid
from collections.abc import AsyncGenerator, Generator
from datetime import date
from pathlib import Path

import jwt
import pytest
from app.adapters.ai import get_ai_adapter
from app.adapters.ai.mock_adapter import MockAIProviderAdapter
from app.adapters.queue import _get_in_memory_adapter
from app.core.config import Settings
from app.core.config import get_settings as app_get_settings
from app.db.session import get_session
from app.main import create_app
from app.models.auth import User, Workspace, WorkspaceMember
from app.models.base import Base
from app.models.project import ImportJob, Project, ProjectVersion, UploadedFile
from app.models.schedule import Activity
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

SECRET = "ai-test-secret-" + "a" * 32  # noqa: S105
ISSUER = "https://auth.projectintelligence.local"
AUDIENCE = "pi-api"


def make_token(
    sub: str,
    *,
    email: str | None = None,
    name: str | None = None,
    secret: str = SECRET,
    exp_offset: int = 300,
) -> str:
    claims: dict[str, object] = {
        "sub": sub,
        "iss": ISSUER,
        "aud": AUDIENCE,
        "exp": int(time.time()) + exp_offset,
    }
    if email:
        claims["email"] = email
    if name:
        claims["name"] = name
    return jwt.encode(claims, secret, algorithm="HS256")


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def temp_storage_dir() -> Generator[Path, None, None]:
    with tempfile.TemporaryDirectory() as tmp_dir:
        yield Path(tmp_dir)


@pytest.fixture
async def app_and_factory(
    temp_storage_dir: Path,
) -> AsyncGenerator[tuple[FastAPI, async_sessionmaker[AsyncSession], Settings], None]:
    engine = create_async_engine(
        "sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )

    @event.listens_for(engine.sync_engine, "connect")
    def _fk_on(dbapi_conn, _record) -> None:  # type: ignore[no-untyped-def]
        dbapi_conn.execute("PRAGMA foreign_keys = ON")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    application = create_app()

    async def _session() -> AsyncGenerator[AsyncSession, None]:
        async with factory() as session:
            yield session

    test_settings = Settings(
        auth_jwt_secret=SecretStr(SECRET),
        auth_jwt_issuer=ISSUER,
        auth_jwt_audience=AUDIENCE,
        storage_local_dir=str(temp_storage_dir),
        queue_backend="in_memory",
        ai_provider="mock",
    )

    application.dependency_overrides[get_session] = _session
    application.dependency_overrides[app_get_settings] = lambda: test_settings

    _get_in_memory_adapter.cache_clear()
    yield application, factory, test_settings
    _get_in_memory_adapter.cache_clear()
    await engine.dispose()


@pytest.fixture
async def client(
    app_and_factory: tuple[FastAPI, async_sessionmaker[AsyncSession], Settings],
) -> AsyncGenerator[AsyncClient, None]:
    app, _, _ = app_and_factory
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def _seed_test_ai_project(
    factory: async_sessionmaker[AsyncSession],
    sub: str = "auth0|ai-engineer-1",
) -> tuple[uuid.UUID, uuid.UUID]:
    async with factory() as session:
        user = User(
            id=uuid.uuid4(),
            auth_subject=sub,
            email="ai_eng@epc.local",
            display_name="AI Engineer",
        )
        workspace = Workspace(
            id=uuid.uuid4(),
            name="AI EPC Workspace",
            owner_user_id=user.id,
        )
        session.add_all([user, workspace])
        await session.flush()

        member = WorkspaceMember(
            workspace_id=workspace.id,
            user_id=user.id,
            role="owner",
        )
        project = Project(
            id=uuid.uuid4(),
            workspace_id=workspace.id,
            name="FPSO Topside Module",
            project_code="FPSO-01",
        )
        session.add_all([member, project])
        await session.flush()

        file_item = UploadedFile(
            id=uuid.uuid4(),
            workspace_id=workspace.id,
            project_id=project.id,
            original_filename="fpso.xer",
            object_key="fpso.xer",
            source_format="xer",
            sha256_checksum="hash_fpso",
            file_size_bytes=500,
        )
        session.add(file_item)
        await session.flush()

        job = ImportJob(
            id=uuid.uuid4(),
            workspace_id=workspace.id,
            project_id=project.id,
            uploaded_file_id=file_item.id,
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
            data_date=date(2026, 3, 1),
            status="ready",
        )
        session.add(version)
        await session.flush()

        project.latest_version_id = version.id
        await session.flush()

        act = Activity(
            workspace_id=workspace.id,
            project_id=project.id,
            project_version_id=version.id,
            source_activity_id="SRC-FPSO-10",
            activity_code="F100",
            activity_name="Compressor Skid Installation",
            status="in_progress",
            total_float_hours=0.0,
        )
        session.add(act)
        await session.commit()
        return project.id, version.id


@pytest.mark.asyncio
async def test_ai_conversation_endpoints(
    client: AsyncClient,
    app_and_factory: tuple[FastAPI, async_sessionmaker[AsyncSession], Settings],
) -> None:
    """Test creating conversation, listing, and getting details."""
    _, factory, _ = app_and_factory
    token = make_token("auth0|ai-engineer-1")
    project_id, version_id = await _seed_test_ai_project(factory, "auth0|ai-engineer-1")

    # 1. Create conversation
    create_res = await client.post(
        f"/api/v1/projects/{project_id}/ai/conversations",
        headers=bearer(token),
        json={"title": "Compressor Skid Criticality", "version_id": str(version_id)},
    )
    assert create_res.status_code == 201
    conv = create_res.json()
    conv_id = conv["id"]
    assert conv["title"] == "Compressor Skid Criticality"
    assert conv["project_id"] == str(project_id)

    # 2. List conversations
    list_res = await client.get(
        f"/api/v1/projects/{project_id}/ai/conversations",
        headers=bearer(token),
    )
    assert list_res.status_code == 200
    conv_list = list_res.json()
    assert len(conv_list) >= 1
    assert any(c["id"] == conv_id for c in conv_list)

    # 3. Get single conversation
    get_res = await client.get(
        f"/api/v1/projects/{project_id}/ai/conversations/{conv_id}",
        headers=bearer(token),
    )
    assert get_res.status_code == 200
    fetched_conv = get_res.json()
    assert fetched_conv["id"] == conv_id
    assert fetched_conv["messages"] == []


@pytest.mark.asyncio
async def test_ai_send_message_endpoint(
    client: AsyncClient,
    app_and_factory: tuple[FastAPI, async_sessionmaker[AsyncSession], Settings],
) -> None:
    """Test sending user message and executing agent turn with mock tool calls."""
    _, factory, settings = app_and_factory
    token = make_token("auth0|ai-engineer-1")
    project_id, version_id = await _seed_test_ai_project(factory, "auth0|ai-engineer-1")

    # Create conversation
    create_res = await client.post(
        f"/api/v1/projects/{project_id}/ai/conversations",
        headers=bearer(token),
        json={"title": "Q&A Session"},
    )
    conv_id = create_res.json()["id"]

    # Configure mock adapter to execute tool call
    mock_adapter = get_ai_adapter(settings)
    assert isinstance(mock_adapter, MockAIProviderAdapter)
    mock_adapter.clear()
    mock_adapter.queue_tool_call(
        name="get_project_overview",
        arguments={},
        call_id="call_overview_1",
    )
    mock_adapter.queue_response("Project FPSO Topside Module has 1 total activity.")

    # Send message
    msg_res = await client.post(
        f"/api/v1/projects/{project_id}/ai/conversations/{conv_id}/messages",
        headers=bearer(token),
        json={"message": "Can you summarize the project status?"},
    )
    assert msg_res.status_code == 200
    turn_resp = msg_res.json()
    assert turn_resp["conversation_id"] == conv_id
    assert "FPSO Topside Module" in turn_resp["message"]["content"]
    assert len(turn_resp["tool_executions"]) == 1
    assert turn_resp["tool_executions"][0]["tool_name"] == "get_project_overview"
    assert turn_resp["tool_executions"][0]["status"] == "completed"
    assert len(turn_resp["tool_executions"][0]["evidence_refs"]) >= 1
    assert "validation_status" in turn_resp


@pytest.mark.asyncio
async def test_ai_tenant_isolation(
    client: AsyncClient,
    app_and_factory: tuple[FastAPI, async_sessionmaker[AsyncSession], Settings],
) -> None:
    """Test cross-tenant isolation: unauthorized user gets 404."""
    _, factory, _ = app_and_factory
    project_id, _ = await _seed_test_ai_project(factory, "auth0|ai-engineer-1")

    other_token = make_token("auth0|unauthorized-user")
    res = await client.get(
        f"/api/v1/projects/{project_id}/ai/conversations",
        headers=bearer(other_token),
    )
    assert res.status_code == 404
