"""PI-003: authentication and cross-tenant isolation tests."""

import time
import uuid
from collections.abc import AsyncGenerator, Callable
from datetime import UTC, datetime

import jwt
import pytest
from app.core.config import Settings, get_settings
from app.db.session import get_session
from app.main import create_app
from app.models.auth import User, Workspace, WorkspaceMember
from app.models.base import Base
from app.models.project import Project
from fastapi import FastAPI
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

SECRET = "test-only-secret-" + "x" * 32  # noqa: S105 - synthetic test value
ISSUER = "https://issuer.test"
AUDIENCE = "pi-api"

A_USER, A_WS, A_PROJECT = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
B_USER, B_WS, B_PROJECT = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()


def make_token(
    sub: str,
    *,
    secret: str = SECRET,
    exp_offset: int = 300,
    algorithm: str = "HS256",
    audience: str | None = AUDIENCE,
) -> str:
    claims: dict[str, object] = {"sub": sub, "iss": ISSUER, "exp": int(time.time()) + exp_offset}
    if audience:
        claims["aud"] = audience
    return jwt.encode(claims, secret, algorithm=algorithm)


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def app() -> AsyncGenerator[FastAPI, None]:
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
        s.add_all(
            [
                User(id=A_USER, auth_subject="sub|a", email="a@example.test"),
                User(id=B_USER, auth_subject="sub|b", email="b@example.test"),
            ]
        )
        await s.flush()
        s.add_all(
            [
                Workspace(id=A_WS, name="A", owner_user_id=A_USER),
                Workspace(id=B_WS, name="B", owner_user_id=B_USER),
            ]
        )
        await s.flush()
        s.add_all(
            [
                WorkspaceMember(workspace_id=A_WS, user_id=A_USER, role="owner", status="active"),
                WorkspaceMember(workspace_id=B_WS, user_id=B_USER, role="owner", status="active"),
                Project(id=A_PROJECT, workspace_id=A_WS, name="Proj A"),
                Project(id=B_PROJECT, workspace_id=B_WS, name="Proj B"),
            ]
        )
        await s.commit()

    application = create_app()

    async def _session() -> AsyncGenerator[AsyncSession, None]:
        async with factory() as session:
            yield session

    application.dependency_overrides[get_session] = _session
    application.dependency_overrides[get_settings] = lambda: Settings(
        auth_jwt_secret=SecretStr(SECRET), auth_jwt_issuer=ISSUER, auth_jwt_audience=AUDIENCE
    )
    yield application
    await engine.dispose()


@pytest.fixture
async def client(app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


def test_every_v1_route_is_guarded(app: FastAPI) -> None:
    """Guard against future routes being added without authentication."""
    from app.api.deps import get_current_user

    def get_api_routes(target: object) -> list[APIRoute]:
        found: list[APIRoute] = []
        for r in getattr(target, "routes", []):
            if isinstance(r, APIRoute):
                found.append(r)
            elif hasattr(r, "original_router"):
                found.extend(get_api_routes(r.original_router))
        return found

    def depends_on_auth(route: APIRoute) -> bool:
        stack = [route.dependant]
        while stack:
            d = stack.pop()
            if d.call is get_current_user:
                return True
            stack.extend(d.dependencies)
        return False

    v1 = [r for r in get_api_routes(app) if r.path.startswith("/api/v1")]
    assert v1
    assert [r.path for r in v1 if not depends_on_auth(r)] == []


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/me",
        "/api/v1/workspaces",
        f"/api/v1/workspaces/{A_WS}",
        f"/api/v1/projects/{A_PROJECT}",
    ],
)
async def test_missing_token_is_401(client: AsyncClient, path: str) -> None:
    r = await client.get(path)
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "UNAUTHENTICATED"
    assert r.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize(
    "make",
    [
        lambda: "not-a-jwt",
        lambda: make_token("sub|a", secret="y" * 40),  # wrong signature
        lambda: make_token("sub|a", exp_offset=-10),  # expired
        lambda: make_token("sub|a", audience="other"),  # wrong audience
        lambda: make_token("sub|a", audience=None),  # missing audience
        lambda: jwt.encode({"sub": "sub|a"}, SECRET, algorithm="HS256"),  # no exp
    ],
)
async def test_invalid_tokens_are_401(client: AsyncClient, make: Callable[[], str]) -> None:
    r = await client.get("/api/v1/me", headers=bearer(make()))
    assert r.status_code == 401


async def test_alg_none_token_is_rejected(client: AsyncClient) -> None:
    claims = {"sub": "sub|a", "iss": ISSUER, "aud": AUDIENCE, "exp": int(time.time()) + 300}
    token = jwt.encode(claims, key="", algorithm="none")
    r = await client.get("/api/v1/me", headers=bearer(token))
    assert r.status_code == 401


async def test_deactivated_user_is_denied(app: FastAPI, client: AsyncClient) -> None:
    override = app.dependency_overrides[get_session]
    async for s in override():
        user = await s.get(User, A_USER)
        assert user is not None
        user.deleted_at = datetime.now(UTC)
        await s.commit()
    r = await client.get("/api/v1/me", headers=bearer(make_token("sub|a")))
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "UNAUTHENTICATED"


async def test_unset_or_weak_secret_fails_closed(app: FastAPI, client: AsyncClient) -> None:
    app.dependency_overrides[get_settings] = lambda: Settings()  # no secret configured
    r = await client.get("/api/v1/me", headers=bearer(make_token("sub|a")))
    assert r.status_code == 401
    app.dependency_overrides[get_settings] = lambda: Settings(auth_jwt_secret=SecretStr("short"))
    r = await client.get("/api/v1/me", headers=bearer(make_token("sub|a", secret="short")))  # noqa: S106
    assert r.status_code == 401


async def test_me_returns_own_identity(client: AsyncClient) -> None:
    r = await client.get("/api/v1/me", headers=bearer(make_token("sub|a")))
    assert r.status_code == 200
    assert r.json()["id"] == str(A_USER)


async def test_list_workspaces_only_own(client: AsyncClient) -> None:
    r = await client.get("/api/v1/workspaces", headers=bearer(make_token("sub|a")))
    assert [w["id"] for w in r.json()] == [str(A_WS)]


async def test_own_workspace_and_project_accessible(client: AsyncClient) -> None:
    h = bearer(make_token("sub|a"))
    assert (await client.get(f"/api/v1/workspaces/{A_WS}", headers=h)).status_code == 200
    assert (await client.get(f"/api/v1/projects/{A_PROJECT}", headers=h)).status_code == 200


async def test_cross_tenant_workspace_and_project_return_404(client: AsyncClient) -> None:
    h = bearer(make_token("sub|a"))
    other_ws = await client.get(f"/api/v1/workspaces/{B_WS}", headers=h)
    other_proj = await client.get(f"/api/v1/projects/{B_PROJECT}", headers=h)
    missing_ws = await client.get(f"/api/v1/workspaces/{uuid.uuid4()}", headers=h)
    assert other_ws.status_code == other_proj.status_code == 404
    # Another tenant's resource is indistinguishable from one that does not exist.
    assert other_ws.json()["error"]["code"] == missing_ws.json()["error"]["code"] == "NOT_FOUND"
    assert other_ws.json()["error"]["message"] == missing_ws.json()["error"]["message"]
    assert "Proj B" not in other_proj.text


async def test_isolation_is_symmetric(client: AsyncClient) -> None:
    h = bearer(make_token("sub|b"))
    assert (await client.get(f"/api/v1/projects/{A_PROJECT}", headers=h)).status_code == 404
    assert (await client.get(f"/api/v1/projects/{B_PROJECT}", headers=h)).status_code == 200


@pytest.mark.parametrize("status", ["invited", "suspended"])
async def test_non_active_membership_denied(app: FastAPI, client: AsyncClient, status: str) -> None:
    override = app.dependency_overrides[get_session]
    async for s in override():
        member = await s.get(WorkspaceMember, (A_WS, A_USER))
        assert member is not None
        member.status = status
        await s.commit()
    h = bearer(make_token("sub|a"))
    assert (await client.get(f"/api/v1/workspaces/{A_WS}", headers=h)).status_code == 404
    assert (await client.get(f"/api/v1/projects/{A_PROJECT}", headers=h)).status_code == 404


async def test_malformed_uuid_is_validation_error(client: AsyncClient) -> None:
    h = bearer(make_token("sub|a"))
    r = await client.get("/api/v1/projects/not-a-uuid", headers=h)
    assert r.status_code == 422
