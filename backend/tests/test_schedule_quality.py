"""PI-033: Schedule quality checks endpoint integration tests.

Acceptance criteria:
- Implement only explicitly documented checks.
- Each finding has severity, method, evidence, and limitation.
- UI/Service strictly distinguishes data-quality checks from schedule-performance findings.
- Endpoints protected by ProjectAccess tenant guard.
- Full multi-tenant isolation.
"""

import tempfile
import time
import uuid
from collections.abc import AsyncGenerator, Generator
from pathlib import Path

import jwt
import pytest
from app.adapters.queue import _get_in_memory_adapter
from app.adapters.storage import get_storage_adapter
from app.core.config import Settings
from app.core.config import get_settings as app_get_settings
from app.db.session import get_session
from app.main import create_app
from app.models.base import Base
from app.workers.import_worker import execute_import_job
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

SECRET = "qual-test-secret-" + "q" * 32  # noqa: S105
ISSUER = "https://auth.projectintelligence.local"
AUDIENCE = "pi-api"

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "xer"


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


async def _setup_project_with_xer(
    client: AsyncClient,
    factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    token: str,
    fixture_name: str = "p6_release_82_facility.xer",
) -> tuple[str, str]:
    proj_res = await client.post(
        "/api/v1/projects",
        headers=bearer(token),
        json={"name": "Gas Processing Facility Quality Audit"},
    )
    assert proj_res.status_code == 201
    project_id = proj_res.json()["id"]

    xer_bytes = (FIXTURES_DIR / fixture_name).read_bytes()
    upload_init = (
        await client.post(
            f"/api/v1/projects/{project_id}/uploads",
            headers=bearer(token),
            json={"filename": fixture_name},
        )
    ).json()

    put_res = await client.put(
        upload_init["upload_url"],
        headers=bearer(token),
        content=xer_bytes,
    )
    assert put_res.status_code == 200

    complete_res = (
        await client.post(
            f"/api/v1/uploads/{upload_init['file_id']}/complete",
            headers=bearer(token),
        )
    ).json()
    job_id = complete_res["import_job_id"]

    async with factory() as s:
        storage = get_storage_adapter(settings)
        await execute_import_job(s, storage, uuid.UUID(job_id))

    confirm_res = (
        await client.post(
            f"/api/v1/imports/{job_id}/confirm",
            headers=bearer(token),
        )
    ).json()
    version_id = confirm_res["project_version_id"]
    return project_id, version_id


@pytest.mark.asyncio
async def test_run_quality_checks_post_api(
    client: AsyncClient,
    app_and_factory: tuple[FastAPI, async_sessionmaker[AsyncSession], Settings],
) -> None:
    """Verify POST /projects/{id}/schedule/quality-checks triggers audit and returns findings."""
    _, factory, settings = app_and_factory
    token = make_token("auth0|qual-user-1", email="qual1@epc.test")
    project_id, version_id = await _setup_project_with_xer(client, factory, settings, token)

    res = await client.post(
        f"/api/v1/projects/{project_id}/schedule/quality-checks",
        headers=bearer(token),
        json={"persist": True},
    )
    assert res.status_code == 200
    data = res.json()

    assert data["project_id"] == project_id
    assert data["version_id"] == version_id
    assert data["run_id"] is not None
    assert "summary" in data
    assert "findings" in data

    summary = data["summary"]
    assert "total_findings" in summary
    assert "data_quality_count" in summary
    assert "schedule_performance_count" in summary
    assert "by_severity" in summary
    assert "checks_run" in summary
    assert (
        summary["total_findings"]
        == summary["data_quality_count"] + summary["schedule_performance_count"]
    )

    # Verify each finding has required audit fields
    for f in data["findings"]:
        assert f["category"] in ("data_quality", "schedule_performance")
        assert f["severity"] in ("info", "low", "medium", "high", "critical")
        assert len(f["method"]) > 0
        assert len(f["limitation"]) > 0
        assert isinstance(f["evidence"], list)


@pytest.mark.asyncio
async def test_get_quality_checks_api(
    client: AsyncClient,
    app_and_factory: tuple[FastAPI, async_sessionmaker[AsyncSession], Settings],
) -> None:
    """Verify GET quality-checks retrieves report and supports category filter."""
    _, factory, settings = app_and_factory
    token = make_token("auth0|qual-user-2", email="qual2@epc.test")
    project_id, version_id = await _setup_project_with_xer(client, factory, settings, token)

    # 1. Unfiltered GET
    res = await client.get(
        f"/api/v1/projects/{project_id}/schedule/quality-checks?version_id={version_id}",
        headers=bearer(token),
    )
    assert res.status_code == 200
    data = res.json()
    assert data["project_id"] == project_id

    # 2. Category filtered GET: data_quality
    dq_res = await client.get(
        f"/api/v1/projects/{project_id}/schedule/quality-checks?category=data_quality",
        headers=bearer(token),
    )
    assert dq_res.status_code == 200
    dq_data = dq_res.json()
    for f in dq_data["findings"]:
        assert f["category"] == "data_quality"


@pytest.mark.asyncio
async def test_quality_checks_cross_tenant_isolation(
    client: AsyncClient,
    app_and_factory: tuple[FastAPI, async_sessionmaker[AsyncSession], Settings],
) -> None:
    """Verify other tenants cannot run or view quality checks."""
    _, factory, settings = app_and_factory
    token = make_token("auth0|qual-user-3", email="qual3@epc.test")
    project_id, _ = await _setup_project_with_xer(client, factory, settings, token)

    other_token = make_token("auth0|unauthorized-tenant", email="intruder@other.test")

    post_res = await client.post(
        f"/api/v1/projects/{project_id}/schedule/quality-checks",
        headers=bearer(other_token),
        json={},
    )
    assert post_res.status_code == 404

    get_res = await client.get(
        f"/api/v1/projects/{project_id}/schedule/quality-checks",
        headers=bearer(other_token),
    )
    assert get_res.status_code == 404
