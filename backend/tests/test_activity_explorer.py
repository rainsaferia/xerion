"""PI-031: Activity and WBS explorer API endpoint integration tests.

Acceptance criteria:
- Search, filter, and pagination are executed server-side.
- Activity detail shows source identifier and provenance.
- Predecessor and successor links resolve strictly within the same version.
- WBS tree aggregates activity counts per node.
- Strict multi-tenant isolation on all 4 endpoints.
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

SECRET = "explorer-test-secret-" + "e" * 32  # noqa: S105
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
        json={"name": "Gas Processing Facility EPC"},
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


# --- Tests ---


async def test_get_activities_search_filter_pagination(
    client: AsyncClient,
    app_and_factory: tuple[FastAPI, async_sessionmaker[AsyncSession], Settings],
) -> None:
    _, factory, settings = app_and_factory
    token = make_token("auth0|exp-test-1", email="exp1@epc.test")

    project_id, version_id = await _setup_project_with_xer(client, factory, settings, token)

    # 1. Unfiltered: returns 5 activities
    res = await client.get(f"/api/v1/projects/{project_id}/activities", headers=bearer(token))
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 5
    assert len(data["items"]) == 5
    assert data["limit"] == 50
    assert data["offset"] == 0

    # 2. Search query (q) matching code or name
    search_res = await client.get(
        f"/api/v1/projects/{project_id}/activities?q=PFD",
        headers=bearer(token),
    )
    assert search_res.status_code == 200
    search_data = search_res.json()
    assert search_data["total"] == 1
    assert search_data["items"][0]["activity_code"] == "ENG-100"
    assert search_data["items"][0]["status"] == "complete"

    # 3. Filter by status
    status_res = await client.get(
        f"/api/v1/projects/{project_id}/activities?status=in_progress",
        headers=bearer(token),
    )
    assert status_res.status_code == 200
    status_data = status_res.json()
    assert status_data["total"] == 2
    assert {i["activity_code"] for i in status_data["items"]} == {"ENG-200", "PROC-100"}

    # 4. Pagination: limit 2, offset 0 then offset 2
    p1_res = await client.get(
        f"/api/v1/projects/{project_id}/activities?limit=2&offset=0",
        headers=bearer(token),
    )
    assert p1_res.status_code == 200
    p1 = p1_res.json()
    assert p1["total"] == 5
    assert len(p1["items"]) == 2

    p2_res = await client.get(
        f"/api/v1/projects/{project_id}/activities?limit=2&offset=2",
        headers=bearer(token),
    )
    assert p2_res.status_code == 200
    p2 = p2_res.json()
    assert len(p2["items"]) == 2
    assert p1["items"][0]["id"] != p2["items"][0]["id"]


async def test_get_activity_detail_and_provenance(
    client: AsyncClient,
    app_and_factory: tuple[FastAPI, async_sessionmaker[AsyncSession], Settings],
) -> None:
    _, factory, settings = app_and_factory
    token = make_token("auth0|exp-test-2", email="exp2@epc.test")

    project_id, version_id = await _setup_project_with_xer(client, factory, settings, token)

    # Get activity list to pick an ID
    list_res = await client.get(f"/api/v1/projects/{project_id}/activities", headers=bearer(token))
    activities = list_res.json()["items"]
    target = next(a for a in activities if a["activity_code"] == "ENG-100")

    # Call GET /api/v1/projects/{project_id}/activities/{activity_id}
    detail_res = await client.get(
        f"/api/v1/projects/{project_id}/activities/{target['id']}",
        headers=bearer(token),
    )
    assert detail_res.status_code == 200
    detail = detail_res.json()

    assert detail["id"] == target["id"]
    assert detail["source_activity_id"] is not None
    assert detail["activity_code"] == "ENG-100"
    assert detail["activity_name"] == "Process Flow Diagrams (PFD)"
    assert detail["status"] == "complete"
    assert detail["wbs_code"] is not None
    assert detail["calendar_name"] is not None
    # Provenance fields present
    assert isinstance(detail["source_fields"], dict)
    assert "source_status" in detail


async def test_get_activity_relationships_endpoint(
    client: AsyncClient,
    app_and_factory: tuple[FastAPI, async_sessionmaker[AsyncSession], Settings],
) -> None:
    _, factory, settings = app_and_factory
    token = make_token("auth0|exp-test-3", email="exp3@epc.test")

    project_id, version_id = await _setup_project_with_xer(client, factory, settings, token)

    list_res = await client.get(f"/api/v1/projects/{project_id}/activities", headers=bearer(token))
    activities = list_res.json()["items"]
    # In facility fixture: ENG-200 has predecessor ENG-100 and successors
    eng_200 = next(a for a in activities if a["activity_code"] == "ENG-200")

    # Call GET /api/v1/projects/{project_id}/activities/{activity_id}/relationships
    rel_res = await client.get(
        f"/api/v1/projects/{project_id}/activities/{eng_200['id']}/relationships",
        headers=bearer(token),
    )
    assert rel_res.status_code == 200
    rels = rel_res.json()

    assert rels["activity_id"] == eng_200["id"]
    # Predecessors must contain ENG-100
    assert len(rels["predecessors"]) > 0
    pred_codes = [p["activity_code"] for p in rels["predecessors"]]
    assert "ENG-100" in pred_codes
    assert rels["predecessors"][0]["relationship_type"] == "FS"

    # Successors must resolve within same version
    assert len(rels["successors"]) > 0


async def test_get_wbs_tree_endpoint(
    client: AsyncClient,
    app_and_factory: tuple[FastAPI, async_sessionmaker[AsyncSession], Settings],
) -> None:
    _, factory, settings = app_and_factory
    token = make_token("auth0|exp-test-4", email="exp4@epc.test")

    project_id, version_id = await _setup_project_with_xer(client, factory, settings, token)

    # Call GET /api/v1/projects/{project_id}/wbs
    wbs_res = await client.get(f"/api/v1/projects/{project_id}/wbs", headers=bearer(token))
    assert wbs_res.status_code == 200
    wbs_list = wbs_res.json()
    assert len(wbs_list) == 4

    wbs_codes = {w["wbs_code"] for w in wbs_list}
    assert {"GPF", "GPF.ENG", "GPF.PROC", "GPF.CONST"}.issubset(wbs_codes)

    # Activity count verification: sum of activity counts equals 5
    total_wbs_acts = sum(w["activity_count"] for w in wbs_list)
    assert total_wbs_acts == 5


async def test_explorer_endpoints_tenant_isolation(
    client: AsyncClient,
    app_and_factory: tuple[FastAPI, async_sessionmaker[AsyncSession], Settings],
) -> None:
    _, factory, settings = app_and_factory
    user_a = make_token("auth0|exp-tenant-a", email="a@epc.test")
    user_b = make_token("auth0|exp-tenant-b", email="b@epc.test")

    proj_a_id, version_id = await _setup_project_with_xer(client, factory, settings, user_a)

    list_res = await client.get(f"/api/v1/projects/{proj_a_id}/activities", headers=bearer(user_a))
    act_a_id = list_res.json()["items"][0]["id"]

    # User B requests User A's activity list -> 404
    assert (
        await client.get(f"/api/v1/projects/{proj_a_id}/activities", headers=bearer(user_b))
    ).status_code == 404

    # User B requests User A's activity detail -> 404
    assert (
        await client.get(
            f"/api/v1/projects/{proj_a_id}/activities/{act_a_id}",
            headers=bearer(user_b),
        )
    ).status_code == 404

    # User B requests User A's activity relationships -> 404
    assert (
        await client.get(
            f"/api/v1/projects/{proj_a_id}/activities/{act_a_id}/relationships",
            headers=bearer(user_b),
        )
    ).status_code == 404

    # User B requests User A's WBS tree -> 404
    assert (
        await client.get(f"/api/v1/projects/{proj_a_id}/wbs", headers=bearer(user_b))
    ).status_code == 404
