"""PI-010: Personal workspace bootstrap tests.

Acceptance criteria:
- Signup/login maps auth subject to application user.
- Exactly one personal workspace is created idempotently.
- Workspace membership owner row is present.
"""

import time
import uuid
from collections.abc import AsyncGenerator

import jwt
import pytest
from app.core.config import Settings, get_settings
from app.db.session import get_session
from app.domains.workspaces.bootstrap import bootstrap_personal_workspace
from app.main import create_app
from app.models.auth import User, Workspace, WorkspaceMember
from app.models.base import Base
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

SECRET = "bootstrap-test-secret-" + "z" * 32  # noqa: S105
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


async def test_first_login_bootstraps_user_workspace_and_owner_membership(
    client: AsyncClient,
    app_and_factory: tuple[FastAPI, async_sessionmaker[AsyncSession]],
) -> None:
    _, factory = app_and_factory
    token = make_token("auth0|new-engineer-01", email="engineer@epc.test", name="Ahmad Dahlan")

    res = await client.get("/api/v1/me", headers=bearer(token))
    assert res.status_code == 200
    data = res.json()
    assert data["email"] == "engineer@epc.test"
    assert data["display_name"] == "Ahmad Dahlan"
    assert data["personal_workspace_id"] is not None
    user_id = uuid.UUID(data["id"])
    ws_id = uuid.UUID(data["personal_workspace_id"])

    # Verify DB state directly
    async with factory() as s:
        user = await s.get(User, user_id)
        assert user is not None
        assert user.auth_subject == "auth0|new-engineer-01"

        ws = await s.get(Workspace, ws_id)
        assert ws is not None
        assert ws.workspace_type == "personal"
        assert ws.owner_user_id == user_id
        assert ws.name == "Ahmad Dahlan's Workspace"

        member = await s.get(WorkspaceMember, (ws_id, user_id))
        assert member is not None
        assert member.role == "owner"
        assert member.status == "active"


async def test_personal_workspace_bootstrap_is_idempotent(
    client: AsyncClient,
    app_and_factory: tuple[FastAPI, async_sessionmaker[AsyncSession]],
) -> None:
    _, factory = app_and_factory
    token = make_token("auth0|idempotent-user", email="user@epc.test")

    # Hit /me multiple times
    res1 = await client.get("/api/v1/me", headers=bearer(token))
    res2 = await client.get("/api/v1/me", headers=bearer(token))
    res3 = await client.get("/api/v1/workspaces", headers=bearer(token))

    assert res1.status_code == 200
    assert res2.status_code == 200
    assert res3.status_code == 200
    assert res1.json()["id"] == res2.json()["id"]
    assert res1.json()["personal_workspace_id"] == res2.json()["personal_workspace_id"]

    # Verify exactly one personal workspace exists for this user in DB
    user_id = uuid.UUID(res1.json()["id"])
    async with factory() as s:
        workspaces = (
            (
                await s.execute(
                    select(Workspace).where(
                        Workspace.owner_user_id == user_id,
                        Workspace.workspace_type == "personal",
                        Workspace.deleted_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(workspaces) == 1

        memberships = (
            (
                await s.execute(
                    select(WorkspaceMember).where(
                        WorkspaceMember.user_id == user_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(memberships) == 1
        assert memberships[0].role == "owner"


async def test_domain_bootstrap_direct_invocation_idempotency(
    app_and_factory: tuple[FastAPI, async_sessionmaker[AsyncSession]],
) -> None:
    _, factory = app_and_factory

    # First session: initial bootstrap
    async with factory() as s:
        u1, w1, m1 = await bootstrap_personal_workspace(
            session=s,
            auth_subject="auth0|direct-tester",
            email="direct@epc.test",
            display_name="Direct Tester",
        )
        await s.commit()

    # Second session: repeat bootstrap with updated display name
    async with factory() as s:
        u2, w2, m2 = await bootstrap_personal_workspace(
            session=s,
            auth_subject="auth0|direct-tester",
            email="direct@epc.test",
            display_name="Direct Tester Updated",
        )
        await s.commit()

        # Both invocations must resolve to the identical UUIDs
        assert u1.id == u2.id
        assert w1.id == w2.id
        assert m1.workspace_id == m2.workspace_id
        assert m1.user_id == m2.user_id
        assert u2.display_name == "Direct Tester Updated"
        assert w2.workspace_type == "personal"
        assert m2.role == "owner"
        assert m2.status == "active"


async def test_patch_me_updates_profile(
    client: AsyncClient,
) -> None:
    token = make_token("auth0|profile-updater", email="updater@epc.test")

    # Initial bootstrap via /me
    init_res = await client.get("/api/v1/me", headers=bearer(token))
    assert init_res.status_code == 200

    # Patch display name and preferred locale
    patch_res = await client.patch(
        "/api/v1/me",
        headers=bearer(token),
        json={"display_name": "Siti Rahma, PMP", "preferred_locale": "id"},
    )
    assert patch_res.status_code == 200
    data = patch_res.json()
    assert data["display_name"] == "Siti Rahma, PMP"
    assert data["preferred_locale"] == "id"

    # Confirm persistence on subsequent GET
    get_res = await client.get("/api/v1/me", headers=bearer(token))
    assert get_res.json()["display_name"] == "Siti Rahma, PMP"
    assert get_res.json()["preferred_locale"] == "id"


async def test_post_workspaces_creates_team_workspace(
    client: AsyncClient,
) -> None:
    token = make_token("auth0|team-builder", email="builder@epc.test")

    # User bootstraps
    me = await client.get("/api/v1/me", headers=bearer(token))
    personal_ws_id = me.json()["personal_workspace_id"]

    # Explicit POST /workspaces creates team workspace
    create_res = await client.post(
        "/api/v1/workspaces",
        headers=bearer(token),
        json={"name": "Natuna Gas Expansion Project Team", "timezone": "Asia/Jakarta"},
    )
    assert create_res.status_code == 201
    team_ws = create_res.json()
    assert team_ws["name"] == "Natuna Gas Expansion Project Team"
    assert team_ws["workspace_type"] == "team"
    assert team_ws["id"] != personal_ws_id

    # GET /workspaces returns both workspaces
    list_res = await client.get("/api/v1/workspaces", headers=bearer(token))
    assert list_res.status_code == 200
    workspaces = list_res.json()
    assert len(workspaces) == 2
    types = {w["workspace_type"] for w in workspaces}
    assert types == {"personal", "team"}
