"""PI-030: Project overview metrics endpoint integration tests.

Acceptance criteria:
- Activity counts and status distribution computed from selected version.
- Data date and source finish information shown.
- Missing fields display as unavailable (None), not zero.
- Defaults to latest project version when version_id is omitted.
- Explicit version_id parameter selects historical version.
- Returns 404 NO_VERSION_AVAILABLE when project has no versions.
- Strict multi-tenant isolation.
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

SECRET = "overview-test-secret-" + "o" * 32  # noqa: S105
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

    from app.core.config import get_settings as app_get_settings

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


async def _upload_and_process_file(
    client: AsyncClient,
    factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    token: str,
    project_id: str,
    filename: str,
    content: bytes,
) -> str:
    upload_init = (
        await client.post(
            f"/api/v1/projects/{project_id}/uploads",
            headers=bearer(token),
            json={"filename": filename},
        )
    ).json()

    put_res = await client.put(
        upload_init["upload_url"],
        headers=bearer(token),
        content=content,
    )
    assert put_res.status_code == 200

    complete_res = (
        await client.post(
            f"/api/v1/uploads/{upload_init['file_id']}/complete",
            headers=bearer(token),
        )
    ).json()
    job_id = str(complete_res["import_job_id"])

    async with factory() as s:
        storage = get_storage_adapter(settings)
        await execute_import_job(s, storage, uuid.UUID(job_id))

    return job_id


# --- Tests ---


async def test_get_project_overview_for_confirmed_xer(
    client: AsyncClient,
    app_and_factory: tuple[FastAPI, async_sessionmaker[AsyncSession], Settings],
) -> None:
    _, factory, settings = app_and_factory
    token = make_token("auth0|ov-user-1", email="ov1@epc.test")

    # Create project
    proj_res = await client.post(
        "/api/v1/projects",
        headers=bearer(token),
        json={"name": "Gas Processing Facility EPC"},
    )
    assert proj_res.status_code == 201
    project_id = proj_res.json()["id"]

    # Upload and confirm XER
    xer_bytes = (FIXTURES_DIR / "p6_release_82_facility.xer").read_bytes()
    job_id = await _upload_and_process_file(
        client, factory, settings, token, project_id, "gpf_v1.xer", xer_bytes
    )
    confirm_res = await client.post(f"/api/v1/imports/{job_id}/confirm", headers=bearer(token))
    assert confirm_res.status_code == 200
    v1_id = confirm_res.json()["project_version_id"]

    # Call GET /api/v1/projects/{project_id}/overview
    res = await client.get(f"/api/v1/projects/{project_id}/overview", headers=bearer(token))
    assert res.status_code == 200
    data = res.json()

    assert data["project_id"] == project_id
    assert data["project_name"] == "Gas Processing Facility EPC"
    assert data["version_id"] == v1_id
    assert data["version_number"] == 1
    assert data["version_label"] == "V1"
    assert data["source_filename"] == "gpf_v1.xer"
    assert data["source_format"] == "xer"
    assert data["data_date"] == "2026-11-01"

    # Facility fixture activity stats: 5 total activities
    assert data["total_activities"] == 5
    assert data["status_distribution"]["complete"] == 1
    assert data["status_distribution"]["in_progress"] == 2
    assert data["status_distribution"]["not_started"] == 2
    assert data["status_distribution"]["suspended"] == 0
    assert data["status_distribution"]["unknown"] == 0

    assert data["calendars_count"] == 2
    assert data["wbs_nodes_count"] == 4
    assert data["relationships_count"] == 5


async def test_get_project_overview_missing_fields_stay_none(
    client: AsyncClient,
    app_and_factory: tuple[FastAPI, async_sessionmaker[AsyncSession], Settings],
) -> None:
    """PI-030 Acceptance criterion: Missing fields display as unavailable, not zero."""
    _, factory, settings = app_and_factory
    token = make_token("auth0|ov-user-none", email="none@epc.test")

    proj_res = await client.post(
        "/api/v1/projects",
        headers=bearer(token),
        json={"name": "Minimal Tabular Project"},
    )
    project_id = proj_res.json()["id"]

    # Upload simple CSV without float or physical % complete
    csv_bytes = b"Code,Name\nA100,Engineering\nA200,Procurement\n"
    job_id = await _upload_and_process_file(
        client, factory, settings, token, project_id, "simple.csv", csv_bytes
    )
    confirm_res = await client.post(f"/api/v1/imports/{job_id}/confirm", headers=bearer(token))
    assert confirm_res.status_code == 200

    res = await client.get(f"/api/v1/projects/{project_id}/overview", headers=bearer(token))
    assert res.status_code == 200
    data = res.json()

    assert data["total_activities"] == 2
    # Must be null/None in JSON, NEVER 0.0 or 0
    assert data["min_total_float_hours"] is None
    assert data["max_total_float_hours"] is None
    assert data["avg_physical_pct_complete"] is None
    assert data["critical_activities_count"] == 0


async def test_get_project_overview_version_parameter_and_default(
    client: AsyncClient,
    app_and_factory: tuple[FastAPI, async_sessionmaker[AsyncSession], Settings],
) -> None:
    """Explicit version_id query returns requested historical version.

    Omitting version_id defaults to the latest version.
    """
    _, factory, settings = app_and_factory
    token = make_token("auth0|ov-multi-ver", email="multiver@epc.test")

    proj_res = await client.post(
        "/api/v1/projects",
        headers=bearer(token),
        json={"name": "Multi-version Project"},
    )
    project_id = proj_res.json()["id"]

    xer_v1_bytes = (FIXTURES_DIR / "p6_release_82_facility.xer").read_bytes()
    xer_v2_bytes = (FIXTURES_DIR / "p6_release_20_pipeline.xer").read_bytes()

    # V1 (facility: 5 activities)
    j1 = await _upload_and_process_file(
        client, factory, settings, token, project_id, "v1.xer", xer_v1_bytes
    )
    c1 = (await client.post(f"/api/v1/imports/{j1}/confirm", headers=bearer(token))).json()
    v1_id = c1["project_version_id"]

    # V2 (pipeline: 3 activities)
    j2 = await _upload_and_process_file(
        client, factory, settings, token, project_id, "v2.xer", xer_v2_bytes
    )
    c2 = (await client.post(f"/api/v1/imports/{j2}/confirm", headers=bearer(token))).json()
    v2_id = c2["project_version_id"]

    # 1. Query without version_id -> defaults to latest version (V2)
    latest_res = await client.get(f"/api/v1/projects/{project_id}/overview", headers=bearer(token))
    assert latest_res.status_code == 200
    latest_data = latest_res.json()
    assert latest_data["version_id"] == v2_id
    assert latest_data["version_number"] == 2
    assert latest_data["total_activities"] == 3

    # 2. Query with explicit version_id=v1_id -> returns V1 metrics
    v1_res = await client.get(
        f"/api/v1/projects/{project_id}/overview?version_id={v1_id}",
        headers=bearer(token),
    )
    assert v1_res.status_code == 200
    v1_data = v1_res.json()
    assert v1_data["version_id"] == v1_id
    assert v1_data["version_number"] == 1
    assert v1_data["total_activities"] == 5


async def test_get_project_overview_no_version_available(client: AsyncClient) -> None:
    """Project with zero confirmed versions returns 404 NO_VERSION_AVAILABLE."""
    token = make_token("auth0|ov-empty-proj", email="empty@epc.test")

    proj_res = await client.post(
        "/api/v1/projects",
        headers=bearer(token),
        json={"name": "Empty Project"},
    )
    project_id = proj_res.json()["id"]

    res = await client.get(f"/api/v1/projects/{project_id}/overview", headers=bearer(token))
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "NO_VERSION_AVAILABLE"


async def test_get_project_overview_tenant_isolation(
    client: AsyncClient,
    app_and_factory: tuple[FastAPI, async_sessionmaker[AsyncSession], Settings],
) -> None:
    """User in Workspace B cannot access Workspace A's project overview."""
    _, factory, settings = app_and_factory
    user_a = make_token("auth0|ov-tenant-a", email="a@epc.test")
    user_b = make_token("auth0|ov-tenant-b", email="b@epc.test")

    proj_res = await client.post(
        "/api/v1/projects",
        headers=bearer(user_a),
        json={"name": "Tenant A Secret Project"},
    )
    project_id = proj_res.json()["id"]

    xer_bytes = (FIXTURES_DIR / "p6_release_82_facility.xer").read_bytes()
    j1 = await _upload_and_process_file(
        client, factory, settings, user_a, project_id, "secret.xer", xer_bytes
    )
    await client.post(f"/api/v1/imports/{j1}/confirm", headers=bearer(user_a))

    # User B requests User A's project overview -> 404 NOT_FOUND
    cross_res = await client.get(
        f"/api/v1/projects/{project_id}/overview",
        headers=bearer(user_b),
    )
    assert cross_res.status_code == 404
    assert cross_res.json()["error"]["code"] == "NOT_FOUND"
