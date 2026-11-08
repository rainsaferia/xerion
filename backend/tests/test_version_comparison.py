"""PI-034: Schedule version comparison endpoints integration tests.

Acceptance criteria:
- POST /api/v1/projects/{project_id}/versions/compare
- GET /api/v1/projects/{project_id}/versions/compare
- GET /api/v1/projects/{project_id}/versions/compare/export (returns text/csv)
- Tenant isolation guard: ProjectAccess (cross-tenant 404)
- Exact reconciliation counts and diff breakdown
"""

import csv
import io
import tempfile
import time
import uuid
from collections.abc import AsyncGenerator, Generator
from datetime import date
from pathlib import Path

import jwt
import pytest
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

SECRET = "compare-test-secret-" + "c" * 32  # noqa: S105
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


async def _seed_test_comparison_project(
    factory: async_sessionmaker[AsyncSession],
    sub: str = "auth0|engineer-1",
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    async with factory() as session:
        user = User(
            id=uuid.uuid4(),
            auth_subject=sub,
            email="eng1@epc.local",
            display_name="Engineer One",
        )
        workspace = Workspace(
            id=uuid.uuid4(),
            name="EPC Main Workspace",
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
            name="LNG Expansion Project",
            project_code="LNG-01",
        )
        session.add_all([member, project])
        await session.flush()

        # Files
        f_a = UploadedFile(
            id=uuid.uuid4(),
            workspace_id=workspace.id,
            project_id=project.id,
            original_filename="v1.xer",
            object_key="v1.xer",
            source_format="xer",
            sha256_checksum="hash_v1",
            file_size_bytes=100,
        )
        f_b = UploadedFile(
            id=uuid.uuid4(),
            workspace_id=workspace.id,
            project_id=project.id,
            original_filename="v2.xer",
            object_key="v2.xer",
            source_format="xer",
            sha256_checksum="hash_v2",
            file_size_bytes=100,
        )
        session.add_all([f_a, f_b])
        await session.flush()

        j_a = ImportJob(
            id=uuid.uuid4(),
            workspace_id=workspace.id,
            project_id=project.id,
            uploaded_file_id=f_a.id,
            status="confirmed",
        )
        j_b = ImportJob(
            id=uuid.uuid4(),
            workspace_id=workspace.id,
            project_id=project.id,
            uploaded_file_id=f_b.id,
            status="confirmed",
        )
        session.add_all([j_a, j_b])
        await session.flush()

        v_a = ProjectVersion(
            id=uuid.uuid4(),
            workspace_id=workspace.id,
            project_id=project.id,
            import_job_id=j_a.id,
            version_number=1,
            version_label="Rev A",
            source_format="xer",
            data_date=date(2026, 1, 1),
            status="ready",
        )
        v_b = ProjectVersion(
            id=uuid.uuid4(),
            workspace_id=workspace.id,
            project_id=project.id,
            import_job_id=j_b.id,
            version_number=2,
            version_label="Rev B",
            source_format="xer",
            data_date=date(2026, 2, 1),
            status="ready",
        )
        session.add_all([v_a, v_b])
        await session.flush()

        # Activities
        act_a1 = Activity(
            workspace_id=workspace.id,
            project_id=project.id,
            project_version_id=v_a.id,
            source_activity_id="SRC-1",
            activity_code="ACT-1",
            activity_name="Site Prep",
            status="not_started",
            planned_start=date(2026, 1, 10),
            planned_finish=date(2026, 1, 20),
            total_float_hours=10.0,
        )
        act_a2 = Activity(
            workspace_id=workspace.id,
            project_id=project.id,
            project_version_id=v_a.id,
            source_activity_id="SRC-2",
            activity_code="ACT-2",
            activity_name="Excavation",
            status="not_started",
            planned_start=date(2026, 1, 21),
            planned_finish=date(2026, 2, 5),
            total_float_hours=5.0,
        )

        act_b1 = Activity(
            workspace_id=workspace.id,
            project_id=project.id,
            project_version_id=v_b.id,
            source_activity_id="SRC-1",
            activity_code="ACT-1",
            activity_name="Site Prep",
            status="complete",
            planned_start=date(2026, 1, 10),
            planned_finish=date(2026, 1, 20),
            total_float_hours=0.0,
        )
        act_b3 = Activity(
            workspace_id=workspace.id,
            project_id=project.id,
            project_version_id=v_b.id,
            source_activity_id="SRC-3",
            activity_code="ACT-3",
            activity_name="Concrete Piling",
            status="not_started",
            planned_start=date(2026, 2, 1),
            planned_finish=date(2026, 2, 28),
        )

        session.add_all([act_a1, act_a2, act_b1, act_b3])
        await session.commit()
        return project.id, v_a.id, v_b.id


@pytest.mark.asyncio
async def test_compare_versions_endpoints(
    client: AsyncClient,
    app_and_factory: tuple[FastAPI, async_sessionmaker[AsyncSession], Settings],
) -> None:
    """Test POST and GET endpoints for comparing two versions."""
    _, factory, _ = app_and_factory
    token = make_token("auth0|engineer-1")
    project_id, v_a_id, v_b_id = await _seed_test_comparison_project(factory, "auth0|engineer-1")

    # 1. Test POST /projects/{project_id}/versions/compare
    post_res = await client.post(
        f"/api/v1/projects/{project_id}/versions/compare",
        headers=bearer(token),
        json={
            "from_version_id": str(v_a_id),
            "to_version_id": str(v_b_id),
        },
    )
    assert post_res.status_code == 200
    report = post_res.json()
    assert report["project_id"] == str(project_id)
    assert report["from_version_id"] == str(v_a_id)
    assert report["to_version_id"] == str(v_b_id)
    assert report["summary"]["from_version_total"] == 2
    assert report["summary"]["to_version_total"] == 2
    assert report["summary"]["matched"] == 1
    assert report["summary"]["changed"] == 1  # ACT-1 status & float changed
    assert report["summary"]["removed"] == 1  # ACT-2
    assert report["summary"]["added"] == 1  # ACT-3
    assert report["summary"]["ambiguous"] == 0

    # 2. Test GET /projects/{project_id}/versions/compare
    get_res = await client.get(
        f"/api/v1/projects/{project_id}/versions/compare",
        headers=bearer(token),
        params={
            "from_version_id": str(v_a_id),
            "to_version_id": str(v_b_id),
        },
    )
    assert get_res.status_code == 200
    get_report = get_res.json()
    assert get_report["summary"] == report["summary"]
    assert len(get_report["items"]) == 3

    # 3. Test filtering by category: category=added
    filtered_res = await client.get(
        f"/api/v1/projects/{project_id}/versions/compare",
        headers=bearer(token),
        params={
            "from_version_id": str(v_a_id),
            "to_version_id": str(v_b_id),
            "category": "added",
        },
    )
    assert filtered_res.status_code == 200
    filtered_report = filtered_res.json()
    assert len(filtered_report["items"]) == 1
    assert filtered_report["items"][0]["activity_code"] == "ACT-3"
    assert filtered_report["items"][0]["diff_category"] == "added"


@pytest.mark.asyncio
async def test_compare_versions_export_endpoint(
    client: AsyncClient,
    app_and_factory: tuple[FastAPI, async_sessionmaker[AsyncSession], Settings],
) -> None:
    """Test CSV export endpoint for version comparison."""
    _, factory, _ = app_and_factory
    token = make_token("auth0|engineer-1")
    project_id, v_a_id, v_b_id = await _seed_test_comparison_project(factory, "auth0|engineer-1")

    res = await client.get(
        f"/api/v1/projects/{project_id}/versions/compare/export",
        headers=bearer(token),
        params={
            "from_version_id": str(v_a_id),
            "to_version_id": str(v_b_id),
        },
    )
    assert res.status_code == 200
    assert "text/csv" in res.headers["content-type"]
    assert "attachment;" in res.headers["content-disposition"]

    csv_reader = csv.reader(io.StringIO(res.text))
    rows = list(csv_reader)
    assert len(rows) >= 4  # Header + rows
    header = rows[0]
    assert "diff_category" in header
    assert "activity_code" in header


@pytest.mark.asyncio
async def test_compare_versions_tenant_isolation(
    client: AsyncClient,
    app_and_factory: tuple[FastAPI, async_sessionmaker[AsyncSession], Settings],
) -> None:
    """Test cross-tenant isolation: unauthorized user gets 404."""
    _, factory, _ = app_and_factory
    project_id, v_a_id, v_b_id = await _seed_test_comparison_project(factory, "auth0|engineer-1")

    other_token = make_token("auth0|unauthorized-user")
    res = await client.get(
        f"/api/v1/projects/{project_id}/versions/compare",
        headers=bearer(other_token),
        params={
            "from_version_id": str(v_a_id),
            "to_version_id": str(v_b_id),
        },
    )
    assert res.status_code == 404
