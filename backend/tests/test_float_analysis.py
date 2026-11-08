"""PI-032: Float and critical exposure analysis endpoint integration tests.

Acceptance criteria:
- Threshold is explicit/configurable.
- Negative, zero, and near-critical bands are separated.
- Output labels imported source float vs recalculated value.
- Unit conversions between hours and days are supported.
- Missing float is tracked as unavailable/missing, not coerced to zero.
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

SECRET = "float-test-secret-" + "f" * 32  # noqa: S105
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


@pytest.mark.asyncio
async def test_get_float_distribution_api(
    client: AsyncClient,
    app_and_factory: tuple[FastAPI, async_sessionmaker[AsyncSession], Settings],
) -> None:
    """Verify GET /projects/{id}/schedule/float-distribution returns deterministic bands."""
    _, factory, settings = app_and_factory
    token = make_token("auth0|float-user-1", email="float1@epc.test")
    project_id, version_id = await _setup_project_with_xer(client, factory, settings, token)

    res = await client.get(
        f"/api/v1/projects/{project_id}/schedule/float-distribution",
        headers=bearer(token),
    )
    assert res.status_code == 200
    data = res.json()

    assert data["project_id"] == project_id
    assert data["version_id"] == version_id
    # Acceptance criteria: explicit label of imported source float
    assert data["float_source"] == "imported_source"
    assert data["method"] == "source_total_float_threshold"
    assert data["critical_threshold_hours"] == 0.0
    assert data["near_critical_threshold_hours"] == 80.0
    assert data["hours_per_day"] == 8.0
    assert data["total_activities"] > 0
    assert data["activities_with_float"] > 0

    # Verify bands structure
    bands = data["bands"]
    band_names = [b["name"] for b in bands]
    assert "negative" in band_names
    assert "zero" in band_names
    assert "near_critical" in band_names
    assert "low_float" in band_names
    assert "high_float" in band_names
    assert "missing" in band_names

    # Sum of counts must match total_activities
    total_in_bands = sum(b["count"] for b in bands)
    assert total_in_bands == data["total_activities"]


@pytest.mark.asyncio
async def test_get_float_distribution_custom_thresholds_api(
    client: AsyncClient,
    app_and_factory: tuple[FastAPI, async_sessionmaker[AsyncSession], Settings],
) -> None:
    """Verify configurable thresholds via query parameters."""
    _, factory, settings = app_and_factory
    token = make_token("auth0|float-user-2", email="float2@epc.test")
    project_id, _ = await _setup_project_with_xer(client, factory, settings, token)

    res = await client.get(
        f"/api/v1/projects/{project_id}/schedule/float-distribution"
        "?critical_threshold_hours=-8.0&near_critical_threshold_hours=40.0&hours_per_day=10.0",
        headers=bearer(token),
    )
    assert res.status_code == 200
    data = res.json()
    assert data["critical_threshold_hours"] == -8.0
    assert data["near_critical_threshold_hours"] == 40.0
    assert data["hours_per_day"] == 10.0


@pytest.mark.asyncio
async def test_get_critical_exposure_api(
    client: AsyncClient,
    app_and_factory: tuple[FastAPI, async_sessionmaker[AsyncSession], Settings],
) -> None:
    """Verify GET /projects/{id}/schedule/critical-exposure returns exposure items."""
    _, factory, settings = app_and_factory
    token = make_token("auth0|float-user-3", email="float3@epc.test")
    project_id, _ = await _setup_project_with_xer(client, factory, settings, token)

    # 1. All exposed
    res = await client.get(
        f"/api/v1/projects/{project_id}/schedule/critical-exposure?band=all_exposed",
        headers=bearer(token),
    )
    assert res.status_code == 200
    data = res.json()
    assert data["float_source"] == "imported_source"
    assert "items" in data
    assert data["total_exposed"] >= 0

    if data["items"]:
        first = data["items"][0]
        assert "activity_code" in first
        assert "activity_name" in first
        assert "total_float_hours" in first
        assert "total_float_days" in first
        assert "float_band" in first
        assert "is_critical" in first

    # 2. Filter by zero band
    zero_res = await client.get(
        f"/api/v1/projects/{project_id}/schedule/critical-exposure?band=zero",
        headers=bearer(token),
    )
    assert zero_res.status_code == 200
    zero_data = zero_res.json()
    for item in zero_data["items"]:
        assert item["total_float_hours"] == 0.0
        assert item["float_band"] == "zero"
        assert item["is_critical"] is True


@pytest.mark.asyncio
async def test_float_endpoints_cross_tenant_isolation(
    client: AsyncClient,
    app_and_factory: tuple[FastAPI, async_sessionmaker[AsyncSession], Settings],
) -> None:
    """Ensure user from another workspace cannot access float analytics."""
    _, factory, settings = app_and_factory
    token = make_token("auth0|float-user-4", email="float4@epc.test")
    project_id, _ = await _setup_project_with_xer(client, factory, settings, token)

    other_token = make_token("auth0|other-tenant-user", email="intruder@other.test")

    res_dist = await client.get(
        f"/api/v1/projects/{project_id}/schedule/float-distribution",
        headers=bearer(other_token),
    )
    assert res_dist.status_code == 404

    res_exp = await client.get(
        f"/api/v1/projects/{project_id}/schedule/critical-exposure",
        headers=bearer(other_token),
    )
    assert res_exp.status_code == 404
