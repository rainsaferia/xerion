"""Integration tests for billing, usage summary, and plan limit routes (PI-050)."""

import time
import uuid
from collections.abc import AsyncGenerator

import jwt
import pytest
from app.core.config import Settings
from app.core.config import get_settings as app_get_settings
from app.db.session import get_session
from app.domains.billing.service import record_usage_event
from app.main import create_app
from app.models.base import Base
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

SECRET = "billing-route-secret-" + "s" * 32  # noqa: S105
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
    tuple[FastAPI, async_sessionmaker[AsyncSession], Settings], None
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

    test_settings = Settings(
        auth_jwt_secret=SecretStr(SECRET),
        auth_jwt_issuer=ISSUER,
        auth_jwt_audience=AUDIENCE,
    )

    application.dependency_overrides[get_session] = _session
    application.dependency_overrides[app_get_settings] = lambda: test_settings

    yield application, factory, test_settings


@pytest.fixture
async def client(
    app_and_factory: tuple[FastAPI, async_sessionmaker[AsyncSession], Settings],
) -> AsyncGenerator[AsyncClient, None]:
    application, _, _ = app_and_factory
    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="http://test",
    ) as c:
        yield c


async def test_get_plans_endpoint(client: AsyncClient) -> None:
    token = make_token("user-plan-viewer", email="viewer@epc.test")
    res = await client.get("/api/v1/plans", headers=bearer(token))
    assert res.status_code == 200
    plans = res.json()
    assert len(plans) == 3

    codes = [p["code"] for p in plans]
    assert "free" in codes
    assert "pro" in codes
    assert "enterprise" in codes

    free_plan = next(p for p in plans if p["code"] == "free")
    assert free_plan["quotas"]["max_projects"] == 2
    assert free_plan["quotas"]["max_ai_queries_per_month"] == 30
    assert len(free_plan["features"]) > 0


async def test_get_usage_summary_endpoint(
    client: AsyncClient,
    app_and_factory: tuple[FastAPI, async_sessionmaker[AsyncSession], Settings],
) -> None:
    _, factory, _ = app_and_factory
    token = make_token("user-usage-viewer", email="usage_user@epc.test")

    # Bootstrap user by calling /me
    me_res = await client.get("/api/v1/me", headers=bearer(token))
    assert me_res.status_code == 200
    ws_id = uuid.UUID(me_res.json()["personal_workspace_id"])

    # Record some usage events
    async with factory() as session:
        await record_usage_event(
            session=session,
            workspace_id=ws_id,
            event_type="ai_query",
            quantity=3.0,
            unit="query",
        )
        await session.commit()

    # Query usage summary
    summary_res = await client.get("/api/v1/usage/summary", headers=bearer(token))
    assert summary_res.status_code == 200
    summary = summary_res.json()
    assert summary["workspace_id"] == str(ws_id)
    assert summary["plan_code"] == "free"
    assert summary["billing_period_start"] is not None
    assert summary["reset_date"] is not None

    metrics = {m["metric_name"]: m for m in summary["metrics"]}
    assert "ai_query" in metrics
    assert metrics["ai_query"]["used"] == 3.0
    assert metrics["ai_query"]["limit"] == 30.0
    assert metrics["ai_query"]["remaining"] == 27.0


async def test_enforce_active_projects_limit_in_routes(client: AsyncClient) -> None:
    token = make_token("user-proj-limit", email="proj_limit@epc.test")

    # Create project 1 (Allowed)
    r1 = await client.post(
        "/api/v1/projects",
        headers=bearer(token),
        json={"name": "Project Alpha", "timezone": "Asia/Jakarta"},
    )
    assert r1.status_code == 201

    # Create project 2 (Allowed)
    r2 = await client.post(
        "/api/v1/projects",
        headers=bearer(token),
        json={"name": "Project Beta", "timezone": "Asia/Jakarta"},
    )
    assert r2.status_code == 201

    # Create project 3 (Blocked on Free plan: max 2 active projects)
    r3 = await client.post(
        "/api/v1/projects",
        headers=bearer(token),
        json={"name": "Project Gamma", "timezone": "Asia/Jakarta"},
    )
    assert r3.status_code == 403
    err = r3.json()["error"]
    assert err["code"] == "PLAN_LIMIT_EXCEEDED"
    assert "Active project limit exceeded" in err["message"]
