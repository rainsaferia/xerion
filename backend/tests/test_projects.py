"""PI-011: Project CRUD and tenant-scoped list tests.

Acceptance criteria:
- Create, list, update, archive project.
- Project lists are tenant-scoped.
- Required timezone and project metadata are validated.
"""

import time
from collections.abc import AsyncGenerator

import jwt
import pytest
from app.core.config import Settings, get_settings
from app.db.session import get_session
from app.main import create_app
from app.models.base import Base
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

SECRET = "project-test-secret-" + "p" * 32  # noqa: S105
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
async def app_and_factory() -> AsyncGenerator[
    tuple[FastAPI, async_sessionmaker[AsyncSession]], None
]:
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

    application.dependency_overrides[get_session] = _session
    application.dependency_overrides[get_settings] = lambda: Settings(
        auth_jwt_secret=SecretStr(SECRET), auth_jwt_issuer=ISSUER, auth_jwt_audience=AUDIENCE
    )
    yield application, factory
    await engine.dispose()


@pytest.fixture
async def client(
    app_and_factory: tuple[FastAPI, async_sessionmaker[AsyncSession]],
) -> AsyncGenerator[AsyncClient, None]:
    app, _ = app_and_factory
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def test_create_project_in_personal_workspace_by_default(client: AsyncClient) -> None:
    token = make_token("auth0|planner-01", email="planner01@epc.test", name="Planner One")

    res = await client.post(
        "/api/v1/projects",
        headers=bearer(token),
        json={
            "name": "Gas Processing Facility EPC",
            "project_code": "GPF-001",
            "description": "Onshore EPC gas processing facility, East Kalimantan",
            "industry": "EPC",
            "client_name": "Pertamina Hulu Mahakam",
            "contractor_name": "PT Tripatra Engineers",
            "currency_code": "USD",
            "timezone": "Asia/Makassar",
        },
    )
    assert res.status_code == 201
    data = res.json()
    assert data["name"] == "Gas Processing Facility EPC"
    assert data["project_code"] == "GPF-001"
    assert data["industry"] == "EPC"
    assert data["currency_code"] == "USD"
    assert data["timezone"] == "Asia/Makassar"
    assert data["status"] == "active"
    assert data["workspace_id"] is not None


async def test_create_project_in_team_workspace(client: AsyncClient) -> None:
    token = make_token("auth0|planner-team", email="teamlead@epc.test")

    # 1. Create a team workspace
    ws_res = await client.post(
        "/api/v1/workspaces",
        headers=bearer(token),
        json={"name": "Joint Venture Expansion", "timezone": "Asia/Jakarta"},
    )
    assert ws_res.status_code == 201
    team_ws_id = ws_res.json()["id"]

    # 2. Create project targeting that team workspace
    proj_res = await client.post(
        "/api/v1/projects",
        headers=bearer(token),
        json={
            "workspace_id": team_ws_id,
            "name": "LNG Regasification Terminal",
            "project_code": "LNG-002",
            "timezone": "Asia/Jakarta",
        },
    )
    assert proj_res.status_code == 201
    assert proj_res.json()["workspace_id"] == team_ws_id


async def test_create_project_in_unauthorized_workspace_returns_404(
    client: AsyncClient,
) -> None:
    user_a = make_token("auth0|user-a", email="a@epc.test")
    user_b = make_token("auth0|user-b", email="b@epc.test")

    # User B creates a workspace
    b_ws = await client.post(
        "/api/v1/workspaces",
        headers=bearer(user_b),
        json={"name": "Confidential B Workspace", "timezone": "Asia/Jakarta"},
    )
    b_ws_id = b_ws.json()["id"]

    # User A tries to create a project inside User B's workspace
    res = await client.post(
        "/api/v1/projects",
        headers=bearer(user_a),
        json={
            "workspace_id": b_ws_id,
            "name": "Intruder Project",
            "timezone": "Asia/Jakarta",
        },
    )
    # Anti-enumeration rule: returns 404 NOT_FOUND
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "NOT_FOUND"


async def test_create_project_invalid_timezone_rejected(client: AsyncClient) -> None:
    token = make_token("auth0|tz-tester", email="tz@epc.test")

    res = await client.post(
        "/api/v1/projects",
        headers=bearer(token),
        json={
            "name": "Invalid Timezone Project",
            "timezone": "Mars/Olympus_Mons",
        },
    )
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "VALIDATION_ERROR"
    assert "Invalid IANA timezone" in res.json()["error"]["message"]


async def test_create_project_invalid_currency_code_rejected(client: AsyncClient) -> None:
    token = make_token("auth0|curr-tester", email="curr@epc.test")

    res = await client.post(
        "/api/v1/projects",
        headers=bearer(token),
        json={
            "name": "Invalid Currency Project",
            "currency_code": "USDD",  # 4 chars, invalid
            "timezone": "Asia/Jakarta",
        },
    )
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_list_projects_is_tenant_scoped(client: AsyncClient) -> None:
    user_a = make_token("auth0|corp-a", email="corp-a@epc.test")
    user_b = make_token("auth0|corp-b", email="corp-b@epc.test")

    # User A creates 2 projects
    await client.post(
        "/api/v1/projects",
        headers=bearer(user_a),
        json={"name": "Project Alpha 1", "project_code": "PA-1"},
    )
    await client.post(
        "/api/v1/projects",
        headers=bearer(user_a),
        json={"name": "Project Alpha 2", "project_code": "PA-2"},
    )

    # User B creates 1 project
    await client.post(
        "/api/v1/projects",
        headers=bearer(user_b),
        json={"name": "Project Beta 1", "project_code": "PB-1"},
    )

    # User A lists projects: sees only Alpha 1 & Alpha 2
    a_list = await client.get("/api/v1/projects", headers=bearer(user_a))
    assert a_list.status_code == 200
    a_names = [p["name"] for p in a_list.json()]
    assert set(a_names) == {"Project Alpha 1", "Project Alpha 2"}
    assert "Project Beta 1" not in a_names

    # User B lists projects: sees only Beta 1
    b_list = await client.get("/api/v1/projects", headers=bearer(user_b))
    assert b_list.status_code == 200
    b_names = [p["name"] for p in b_list.json()]
    assert b_names == ["Project Beta 1"]


async def test_patch_project_updates_metadata(client: AsyncClient) -> None:
    token = make_token("auth0|patch-user", email="patch@epc.test")

    created = await client.post(
        "/api/v1/projects",
        headers=bearer(token),
        json={"name": "Original Name", "timezone": "Asia/Jakarta"},
    )
    proj_id = created.json()["id"]

    patch_res = await client.patch(
        f"/api/v1/projects/{proj_id}",
        headers=bearer(token),
        json={
            "name": "Updated Facility Name",
            "project_code": "REV-001",
            "description": "Updated EPC scope description",
            "client_name": "Chevron Pacific",
            "contractor_name": "McDermott Indonesia",
            "currency_code": "idr",  # lowercase -> should normalize to IDR
            "timezone": "Asia/Jayapura",
        },
    )
    assert patch_res.status_code == 200
    data = patch_res.json()
    assert data["name"] == "Updated Facility Name"
    assert data["project_code"] == "REV-001"
    assert data["description"] == "Updated EPC scope description"
    assert data["client_name"] == "Chevron Pacific"
    assert data["contractor_name"] == "McDermott Indonesia"
    assert data["currency_code"] == "IDR"
    assert data["timezone"] == "Asia/Jayapura"

    # Confirm persistence
    get_res = await client.get(f"/api/v1/projects/{proj_id}", headers=bearer(token))
    assert get_res.json()["name"] == "Updated Facility Name"
    assert get_res.json()["timezone"] == "Asia/Jayapura"


async def test_archive_project_and_filter_behavior(client: AsyncClient) -> None:
    token = make_token("auth0|archive-user", email="archive@epc.test")

    # 1. Create 2 projects
    p1 = (
        await client.post(
            "/api/v1/projects",
            headers=bearer(token),
            json={"name": "Active Pipeline Project"},
        )
    ).json()

    p2 = (
        await client.post(
            "/api/v1/projects",
            headers=bearer(token),
            json={"name": "Completed Offshore Platform"},
        )
    ).json()

    # 2. Archive project 2
    archive_res = await client.post(
        f"/api/v1/projects/{p2['id']}/archive",
        headers=bearer(token),
    )
    assert archive_res.status_code == 200
    assert archive_res.json()["status"] == "archived"
    assert archive_res.json()["archived_at"] is not None

    # 3. Default list excludes archived projects
    active_list = (await client.get("/api/v1/projects", headers=bearer(token))).json()
    assert [p["id"] for p in active_list] == [p1["id"]]

    # 4. List with include_archived=true includes both
    all_list = (
        await client.get("/api/v1/projects?include_archived=true", headers=bearer(token))
    ).json()
    assert len(all_list) == 2
    assert {p["id"] for p in all_list} == {p1["id"], p2["id"]}

    # 5. Direct access to archived project still succeeds
    detail_res = await client.get(f"/api/v1/projects/{p2['id']}", headers=bearer(token))
    assert detail_res.status_code == 200
    assert detail_res.json()["status"] == "archived"
