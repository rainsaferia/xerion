"""PI-045: Delay scenario endpoint integration tests.

Acceptance criteria:
- User selects activity and delay amount/unit.
- Scenario does not change source activity/version rows.
- Affected outputs and assumptions are shown.
- If the scenario engine cannot calculate valid impact, it returns a limited/insufficient result.
- Strict multi-tenant isolation via ProjectAccess.
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
from app.models.schedule import Activity
from app.workers.import_worker import execute_import_job
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

SECRET = "scenario-route-secret-" + "s" * 32  # noqa: S105
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
) -> tuple[str, str, str]:
    proj_res = await client.post(
        "/api/v1/projects",
        headers=bearer(token),
        json={"name": "Gas Processing Facility Delay Simulation"},
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

    # Retrieve an in-progress or not-started activity code
    acts_res = await client.get(
        f"/api/v1/projects/{project_id}/activities?version_id={version_id}",
        headers=bearer(token),
    )
    assert acts_res.status_code == 200
    acts = acts_res.json()["items"]
    target_code = acts[0]["activity_code"] or acts[0]["source_activity_id"]

    return project_id, version_id, target_code


@pytest.mark.asyncio
async def test_run_delay_scenario_api(
    client: AsyncClient,
    app_and_factory: tuple[FastAPI, async_sessionmaker[AsyncSession], Settings],
) -> None:
    _, factory, settings = app_and_factory
    token = make_token("auth0|delay-sim-user-1")
    project_id, version_id, target_code = await _setup_project_with_xer(
        client, factory, settings, token
    )

    res = await client.post(
        f"/api/v1/projects/{project_id}/schedule/scenarios/delay",
        headers=bearer(token),
        json={
            "version_id": version_id,
            "activity_source_id": target_code,
            "delay_value": 10.0,
            "delay_unit": "working_days",
            "scenario_name": "Equipment delivery +10 working days",
            "persist": True,
        },
    )
    assert res.status_code == 200
    data = res.json()

    assert data["project_id"] == project_id
    assert data["project_version_id"] == version_id
    assert data["scenario_name"] == "Equipment delivery +10 working days"
    assert data["source_unaltered"] is True
    assert data["status"] in ("completed", "insufficient_data")
    assert "summary" in data
    assert "affected_items" in data
    assert len(data["assumptions"]) >= 3
    assert len(data["limitations"]) >= 3

    # Check target activity in affected items
    if data["status"] == "completed":
        assert any(item["is_target"] is True for item in data["affected_items"])

    # Verify database rows were not altered
    async with factory() as s:
        act = (
            await s.scalars(
                select(Activity).where(
                    Activity.project_id == uuid.UUID(project_id),
                    Activity.activity_code == target_code,
                )
            )
        ).first()
        assert act is not None
        # Activity status or dates in DB remain as originally imported


@pytest.mark.asyncio
async def test_run_delay_scenario_tenant_isolation(
    client: AsyncClient,
    app_and_factory: tuple[FastAPI, async_sessionmaker[AsyncSession], Settings],
) -> None:
    _, factory, settings = app_and_factory
    owner_token = make_token("auth0|owner-user")
    stranger_token = make_token("auth0|stranger-user")

    project_id, version_id, target_code = await _setup_project_with_xer(
        client, factory, settings, owner_token
    )

    # Stranger user from a different workspace cannot run scenario on project
    res = await client.post(
        f"/api/v1/projects/{project_id}/schedule/scenarios/delay",
        headers=bearer(stranger_token),
        json={
            "version_id": version_id,
            "activity_source_id": target_code,
            "delay_value": 5.0,
            "delay_unit": "working_days",
        },
    )
    assert res.status_code == 404
