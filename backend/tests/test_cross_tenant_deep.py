"""PI-051: Comprehensive deep cross-tenant isolation automated test suite."""

import time
import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime

import jwt
import pytest
from app.core.config import Settings, get_settings
from app.db.session import get_session
from app.main import create_app
from app.models.ai import AIConversation
from app.models.auth import User, Workspace, WorkspaceMember
from app.models.base import Base
from app.models.project import (
    ImportJob,
    ImportMapping,
    Project,
    ProjectVersion,
    UploadedFile,
)
from app.models.reporting import Report
from app.models.schedule import Activity
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

SECRET = "deep-cross-tenant-secret-" + "d" * 32
ISSUER = "https://auth.projectintelligence.local"
AUDIENCE = "pi-api"

A_USER_ID, A_WS_ID, A_PROJ_ID, A_VER_ID = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
A_FILE_ID, A_JOB_ID, A_ACT_ID, A_REP_ID = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
A_CONV_ID, A_MAP_ID = uuid.uuid4(), uuid.uuid4()

B_USER_ID, B_WS_ID, B_PROJ_ID, B_VER_ID = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
B_FILE_ID, B_JOB_ID, B_ACT_ID, B_REP_ID = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
B_CONV_ID, B_MAP_ID = uuid.uuid4(), uuid.uuid4()


def make_token(sub: str, *, email: str | None = None) -> str:
    claims: dict[str, object] = {
        "sub": sub,
        "iss": ISSUER,
        "aud": AUDIENCE,
        "exp": int(time.time()) + 300,
    }
    if email:
        claims["email"] = email
    return jwt.encode(claims, SECRET, algorithm="HS256")


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def app_fixture() -> AsyncGenerator[FastAPI, None]:
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
        # Users
        s.add_all(
            [
                User(id=A_USER_ID, auth_subject="sub|tenant_a", email="a@tenant.test"),
                User(id=B_USER_ID, auth_subject="sub|tenant_b", email="b@tenant.test"),
            ]
        )
        await s.flush()

        # Workspaces
        s.add_all(
            [
                Workspace(id=A_WS_ID, name="Tenant A Workspace", owner_user_id=A_USER_ID),
                Workspace(id=B_WS_ID, name="Tenant B Workspace", owner_user_id=B_USER_ID),
            ]
        )
        await s.flush()

        # Members
        s.add_all(
            [
                WorkspaceMember(
                    workspace_id=A_WS_ID, user_id=A_USER_ID, role="owner", status="active"
                ),
                WorkspaceMember(
                    workspace_id=B_WS_ID, user_id=B_USER_ID, role="owner", status="active"
                ),
            ]
        )
        # Projects
        s.add_all(
            [
                Project(
                    id=A_PROJ_ID, workspace_id=A_WS_ID, name="Project Alpha", project_code="PRJ-A"
                ),
                Project(
                    id=B_PROJ_ID, workspace_id=B_WS_ID, name="Project Beta", project_code="PRJ-B"
                ),
            ]
        )
        await s.flush()

        # UploadedFiles
        s.add_all(
            [
                UploadedFile(
                    id=A_FILE_ID,
                    workspace_id=A_WS_ID,
                    project_id=A_PROJ_ID,
                    uploaded_by=A_USER_ID,
                    original_filename="a_schedule.xer",
                    object_key="uploads/a_schedule.xer",
                    source_format="xer",
                    file_size_bytes=1024,
                    sha256_checksum="hash_a",
                ),
                UploadedFile(
                    id=B_FILE_ID,
                    workspace_id=B_WS_ID,
                    project_id=B_PROJ_ID,
                    uploaded_by=B_USER_ID,
                    original_filename="b_schedule.xer",
                    object_key="uploads/b_schedule.xer",
                    source_format="xer",
                    file_size_bytes=2048,
                    sha256_checksum="hash_b",
                ),
            ]
        )
        await s.flush()

        # ImportJobs
        s.add_all(
            [
                ImportJob(
                    id=A_JOB_ID,
                    workspace_id=A_WS_ID,
                    project_id=A_PROJ_ID,
                    uploaded_file_id=A_FILE_ID,
                    status="confirmed",
                    requested_by=A_USER_ID,
                ),
                ImportJob(
                    id=B_JOB_ID,
                    workspace_id=B_WS_ID,
                    project_id=B_PROJ_ID,
                    uploaded_file_id=B_FILE_ID,
                    status="confirmed",
                    requested_by=B_USER_ID,
                ),
            ]
        )
        await s.flush()

        # ProjectVersions
        s.add_all(
            [
                ProjectVersion(
                    id=A_VER_ID,
                    workspace_id=A_WS_ID,
                    project_id=A_PROJ_ID,
                    import_job_id=A_JOB_ID,
                    version_number=1,
                    version_label="Baseline A",
                    source_format="xer",
                    data_date=datetime.now(UTC).date(),
                ),
                ProjectVersion(
                    id=B_VER_ID,
                    workspace_id=B_WS_ID,
                    project_id=B_PROJ_ID,
                    import_job_id=B_JOB_ID,
                    version_number=1,
                    version_label="Baseline B",
                    source_format="xer",
                    data_date=datetime.now(UTC).date(),
                ),
            ]
        )
        await s.flush()

        # Activities
        s.add_all(
            [
                Activity(
                    id=A_ACT_ID,
                    workspace_id=A_WS_ID,
                    project_id=A_PROJ_ID,
                    project_version_id=A_VER_ID,
                    source_activity_id="SRC-A1",
                    activity_code="ACT-A1",
                    activity_name="Site Prep Alpha",
                    activity_type="Task Dependent",
                    status="not_started",
                ),
                Activity(
                    id=B_ACT_ID,
                    workspace_id=B_WS_ID,
                    project_id=B_PROJ_ID,
                    project_version_id=B_VER_ID,
                    source_activity_id="SRC-B1",
                    activity_code="ACT-B1",
                    activity_name="Foundation Beta",
                    activity_type="Task Dependent",
                    status="not_started",
                ),
            ]
        )

        # Reports
        s.add_all(
            [
                Report(
                    id=A_REP_ID,
                    workspace_id=A_WS_ID,
                    project_id=A_PROJ_ID,
                    project_version_id=A_VER_ID,
                    report_type="schedule_health",
                    title="Alpha Health",
                    output_format="pdf",
                    status="ready",
                    object_key="reports/alpha.pdf",
                    generated_by=A_USER_ID,
                ),
                Report(
                    id=B_REP_ID,
                    workspace_id=B_WS_ID,
                    project_id=B_PROJ_ID,
                    project_version_id=B_VER_ID,
                    report_type="schedule_health",
                    title="Beta Health",
                    output_format="pdf",
                    status="ready",
                    object_key="reports/beta.pdf",
                    generated_by=B_USER_ID,
                ),
            ]
        )

        # AI Conversations
        s.add_all(
            [
                AIConversation(
                    id=A_CONV_ID,
                    workspace_id=A_WS_ID,
                    project_id=A_PROJ_ID,
                    title="Alpha AI Chat",
                    created_by=A_USER_ID,
                ),
                AIConversation(
                    id=B_CONV_ID,
                    workspace_id=B_WS_ID,
                    project_id=B_PROJ_ID,
                    title="Beta AI Chat",
                    created_by=B_USER_ID,
                ),
            ]
        )

        # Mapping profiles
        s.add_all(
            [
                ImportMapping(
                    id=A_MAP_ID,
                    workspace_id=A_WS_ID,
                    name="Alpha Mapping",
                    dataset_type="activity_progress",
                    mapping_config={"activity_code": "Code"},
                    created_by=A_USER_ID,
                ),
                ImportMapping(
                    id=B_MAP_ID,
                    workspace_id=B_WS_ID,
                    name="Beta Mapping",
                    dataset_type="activity_progress",
                    mapping_config={"activity_code": "Code"},
                    created_by=B_USER_ID,
                ),
            ]
        )
        await s.commit()

    application = create_app()

    async def _session() -> AsyncGenerator[AsyncSession, None]:
        async with factory() as session:
            yield session

    test_settings = Settings(
        auth_jwt_secret=SecretStr(SECRET),
        auth_jwt_issuer=ISSUER,
        auth_jwt_audience=AUDIENCE,
    )
    application.dependency_overrides[get_session] = _session
    application.dependency_overrides[get_settings] = lambda: test_settings

    yield application
    await engine.dispose()


@pytest.fixture
async def client_a(app_fixture: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    token = make_token("sub|tenant_a", email="a@tenant.test")
    async with AsyncClient(
        transport=ASGITransport(app=app_fixture),
        base_url="http://test",
        headers=bearer(token),
    ) as c:
        yield c


@pytest.fixture
async def client_b(app_fixture: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    token = make_token("sub|tenant_b", email="b@tenant.test")
    async with AsyncClient(
        transport=ASGITransport(app=app_fixture),
        base_url="http://test",
        headers=bearer(token),
    ) as c:
        yield c


async def test_cross_tenant_projects_and_versions(client_a: AsyncClient) -> None:
    # User A attempting to access Tenant B's project
    r_proj = await client_a.get(f"/api/v1/projects/{B_PROJ_ID}")
    assert r_proj.status_code == 404
    assert r_proj.json()["error"]["code"] == "NOT_FOUND"
    assert "Beta" not in r_proj.text

    # Overview
    r_over = await client_a.get(f"/api/v1/projects/{B_PROJ_ID}/overview")
    assert r_over.status_code == 404

    # Versions
    r_ver = await client_a.get(f"/api/v1/projects/{B_PROJ_ID}/versions/{B_VER_ID}")
    assert r_ver.status_code == 404


async def test_cross_tenant_activities_and_explorer(client_a: AsyncClient) -> None:
    # Activities list on Tenant B project
    r_acts = await client_a.get(f"/api/v1/projects/{B_PROJ_ID}/activities")
    assert r_acts.status_code == 404

    # Specific activity on Tenant B project
    r_act = await client_a.get(f"/api/v1/projects/{B_PROJ_ID}/activities/{B_ACT_ID}")
    assert r_act.status_code == 404

    # Activity summary
    r_sum = await client_a.get(f"/api/v1/projects/{B_PROJ_ID}/activities/summary")
    assert r_sum.status_code == 404

    # Critical path
    r_cp = await client_a.get(f"/api/v1/projects/{B_PROJ_ID}/activities/critical-path")
    assert r_cp.status_code == 404


async def test_cross_tenant_quality_and_analytics(client_a: AsyncClient) -> None:
    # Quality checks list
    r_q = await client_a.get(f"/api/v1/projects/{B_PROJ_ID}/quality-checks")
    assert r_q.status_code == 404

    # Trigger quality checks
    r_trig = await client_a.post(f"/api/v1/projects/{B_PROJ_ID}/quality-checks", json={})
    assert r_trig.status_code == 404

    # Delay scenario
    r_delay = await client_a.post(
        f"/api/v1/projects/{B_PROJ_ID}/delay-scenarios",
        json={"name": "S", "delays": [{"activity_code": "ACT-B1", "delay_days": 5}]},
    )
    assert r_delay.status_code == 404

    # Milestone forecast
    r_fore = await client_a.post(f"/api/v1/projects/{B_PROJ_ID}/milestone-forecast", json={})
    assert r_fore.status_code == 404


async def test_cross_tenant_reports_and_exports(client_a: AsyncClient) -> None:
    # Create report on Tenant B project
    r_post_rep = await client_a.post(
        f"/api/v1/projects/{B_PROJ_ID}/reports",
        json={"report_type": "schedule_health", "output_format": "pdf"},
    )
    assert r_post_rep.status_code == 404

    # Single report metadata
    r_rep = await client_a.get(f"/api/v1/reports/{B_REP_ID}")
    assert r_rep.status_code == 404

    # Download URL
    r_url = await client_a.get(f"/api/v1/reports/{B_REP_ID}/download")
    assert r_url.status_code == 404

    # Report binary content
    r_cont = await client_a.get(f"/api/v1/reports/{B_REP_ID}/content")
    assert r_cont.status_code == 404

    # Activity export
    r_exp = await client_a.post(
        f"/api/v1/projects/{B_PROJ_ID}/exports/activities", json={"format": "csv"}
    )
    assert r_exp.status_code == 404


async def test_cross_tenant_uploads_and_imports(client_a: AsyncClient) -> None:
    # Get uploaded file metadata
    r_file = await client_a.get(f"/api/v1/uploads/{B_FILE_ID}")
    assert r_file.status_code == 404

    # Complete upload
    r_comp = await client_a.post(f"/api/v1/uploads/{B_FILE_ID}/complete")
    assert r_comp.status_code == 404

    # Delete upload
    r_del = await client_a.delete(f"/api/v1/uploads/{B_FILE_ID}")
    assert r_del.status_code == 404

    # Import job
    r_job = await client_a.get(f"/api/v1/imports/{B_JOB_ID}")
    assert r_job.status_code == 404

    # Import preview
    r_prev = await client_a.get(f"/api/v1/imports/{B_JOB_ID}/preview")
    assert r_prev.status_code == 404


async def test_cross_tenant_ai_conversations_and_mappings_and_usage(
    client_a: AsyncClient,
) -> None:
    # AI conversations list
    r_convs = await client_a.get(f"/api/v1/projects/{B_PROJ_ID}/ai/conversations")
    assert r_convs.status_code == 404

    # AI conversation detail
    r_conv = await client_a.get(f"/api/v1/projects/{B_PROJ_ID}/ai/conversations/{B_CONV_ID}")
    assert r_conv.status_code == 404

    # Send AI message
    r_msg = await client_a.post(
        f"/api/v1/projects/{B_PROJ_ID}/ai/conversations/{B_CONV_ID}/messages",
        json={"message": "What is the critical path?"},
    )
    assert r_msg.status_code == 404

    # Workspace mapping profiles
    r_maps = await client_a.get(f"/api/v1/workspaces/{B_WS_ID}/mappings")
    assert r_maps.status_code == 404

    # Workspace usage summary
    r_usage = await client_a.get(f"/api/v1/usage/summary?workspace_id={B_WS_ID}")
    assert r_usage.status_code == 404


async def test_cross_tenant_isolation_is_symmetric_and_leak_free(
    client_a: AsyncClient, client_b: AsyncClient
) -> None:
    # User B cannot access User A's project
    r_b_on_a = await client_b.get(f"/api/v1/projects/{A_PROJ_ID}")
    assert r_b_on_a.status_code == 404
    assert r_b_on_a.json()["error"]["code"] == "NOT_FOUND"

    # User A CAN access User A's project
    r_a_on_a = await client_a.get(f"/api/v1/projects/{A_PROJ_ID}")
    assert r_a_on_a.status_code == 200
    assert r_a_on_a.json()["name"] == "Project Alpha"

    # User B CAN access User B's project
    r_b_on_b = await client_b.get(f"/api/v1/projects/{B_PROJ_ID}")
    assert r_b_on_b.status_code == 200
    assert r_b_on_b.json()["name"] == "Project Beta"
