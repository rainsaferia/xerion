"""PI-022: Excel/CSV mapping wizard tests.

Acceptance criteria:
- Detect sheets/headers/sample rows.
- User can map required columns for activity-level progress/schedule template.
- Save and reuse mapping profile.
- Validate dates, IDs, percentages, and duplicates.
- Preview normalized data before confirmation.
"""

import io
import tempfile
import time
from collections.abc import AsyncGenerator, Generator
from pathlib import Path

import jwt
import openpyxl
import pytest
from app.adapters.queue import _get_in_memory_adapter
from app.core.config import Settings
from app.core.config import get_settings as app_get_settings
from app.db.session import get_session
from app.main import create_app
from app.models.base import Base
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

SECRET = "mapping-wizard-test-secret-" + "m" * 32  # noqa: S105
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


async def _upload_file(
    client: AsyncClient, token: str, filename: str, content: bytes
) -> tuple[str, str, str]:
    """Helper: creates project, upload session, uploads content, completes upload."""
    proj = (
        await client.post(
            "/api/v1/projects",
            headers=bearer(token),
            json={"name": "Mapping Test Project"},
        )
    ).json()

    session = (
        await client.post(
            f"/api/v1/projects/{proj['id']}/uploads",
            headers=bearer(token),
            json={"filename": filename},
        )
    ).json()

    put_res = await client.put(
        session["upload_url"],
        headers=bearer(token),
        content=content,
    )
    assert put_res.status_code == 200

    comp_res = await client.post(
        f"/api/v1/uploads/{session['file_id']}/complete",
        headers=bearer(token),
    )
    assert comp_res.status_code == 200
    comp_data = comp_res.json()

    # Get personal workspace ID
    me = (await client.get("/api/v1/me", headers=bearer(token))).json()

    return session["file_id"], comp_data["import_job_id"], me["personal_workspace_id"]


# --- PI-022 Acceptance Tests ---


async def test_detect_sheets_headers_and_sample_rows_for_csv(client: AsyncClient) -> None:
    """PI-022: Detect CSV headers, sample rows, and row counts."""
    token = make_token("auth0|map-user-1", email="m1@epc.test")
    csv_content = (
        b"Task ID,Task Description,Progress %,Target Start,Target End,WBS\n"
        b"ACT-001,Site Preparation,100%,2026-01-01,2026-01-15,1.1\n"
        b"ACT-002,Excavation,60%,2026-01-16,2026-02-15,1.2\n"
        b"ACT-003,Foundation Pouring,0%,2026-02-16,2026-03-31,1.2\n"
    )

    _, job_id, _ = await _upload_file(client, token, "schedule.csv", csv_content)

    res = await client.get(f"/api/v1/imports/{job_id}/inspect", headers=bearer(token))
    assert res.status_code == 200
    data = res.json()

    assert data["format"] == "csv"
    assert data["headers"] == [
        "Task ID",
        "Task Description",
        "Progress %",
        "Target Start",
        "Target End",
        "WBS",
    ]
    assert data["total_rows"] == 3
    assert len(data["sample_rows"]) == 3
    assert data["sample_rows"][0]["Task ID"] == "ACT-001"
    assert data["sample_rows"][0]["Task Description"] == "Site Preparation"


async def test_detect_sheets_and_headers_for_xlsx(client: AsyncClient) -> None:
    """PI-022: Detect XLSX workbook sheets, headers, and sample rows."""
    token = make_token("auth0|map-user-2", email="m2@epc.test")

    wb = openpyxl.Workbook()
    ws1 = wb.active
    ws1.title = "ScheduleData"
    ws1.append(["Code", "Activity Name", "Start Date", "Finish Date"])
    ws1.append(["A10", "Engineering Drawings", "2026-01-01", "2026-02-01"])

    ws2 = wb.create_sheet(title="Milestones")
    ws2.append(["MS_Code", "Date"])
    ws2.append(["M1", "2026-06-01"])

    buf = io.BytesIO()
    wb.save(buf)

    _, job_id, _ = await _upload_file(client, token, "schedule.xlsx", buf.getvalue())

    # Inspect default sheet
    res = await client.get(f"/api/v1/imports/{job_id}/inspect", headers=bearer(token))
    assert res.status_code == 200
    data = res.json()

    assert data["format"] == "xlsx"
    assert data["sheet_names"] == ["ScheduleData", "Milestones"]
    assert data["active_sheet"] == "ScheduleData"
    assert data["headers"] == ["Code", "Activity Name", "Start Date", "Finish Date"]
    assert data["total_rows"] == 1
    assert data["sample_rows"][0]["Code"] == "A10"

    # Inspect specific sheet
    res_m = await client.get(
        f"/api/v1/imports/{job_id}/inspect?sheet=Milestones", headers=bearer(token)
    )
    assert res_m.status_code == 200
    assert res_m.json()["active_sheet"] == "Milestones"
    assert res_m.json()["headers"] == ["MS_Code", "Date"]


async def test_apply_mapping_validates_and_generates_preview(client: AsyncClient) -> None:
    """PI-022: User maps columns and previews normalized data before confirmation."""
    token = make_token("auth0|map-user-3", email="m3@epc.test")
    csv_content = (
        b"ItemNo,Description,StatusStr,Start,End,PctDone,WBSNode\n"
        b"ACT-1,Front End Engineering,Complete,2026-01-01,2026-01-31,100%,FEED\n"
        b"ACT-2,Detailed Design,Active,2026-02-01,2026-04-30,50%,DETAIL\n"
    )

    _, job_id, _ = await _upload_file(client, token, "activities.csv", csv_content)

    mapping_payload = {
        "mapping": {
            "activity_code": "ItemNo",
            "activity_name": "Description",
            "status": "StatusStr",
            "planned_start": "Start",
            "planned_finish": "End",
            "percent_complete": "PctDone",
            "wbs_code": "WBSNode",
        },
        "save_profile_name": "EPC Standard CSV Profile",
    }

    map_res = await client.post(
        f"/api/v1/imports/{job_id}/mapping",
        headers=bearer(token),
        json=mapping_payload,
    )
    assert map_res.status_code == 200
    job_data = map_res.json()

    assert job_data["status"] == "preview_ready"
    assert job_data["progress_pct"] == 100.0
    assert job_data["preview_summary"]["activities"] == 2
    assert job_data["preview_summary"]["wbs_nodes"] == 2

    # Verify preview endpoint returns summary
    prev_res = await client.get(f"/api/v1/imports/{job_id}/preview", headers=bearer(token))
    assert prev_res.status_code == 200
    assert prev_res.json()["preview_summary"]["activities"] == 2


async def test_save_and_reuse_mapping_profile(client: AsyncClient) -> None:
    """PI-022: Save mapping profile and reuse on another import."""
    token = make_token("auth0|map-user-4", email="m4@epc.test")

    # 1. Upload first file and save profile
    csv_1 = b"Code,Title\nT1,Task One\n"
    _, job_1, ws_id = await _upload_file(client, token, "f1.csv", csv_1)

    await client.post(
        f"/api/v1/imports/{job_1}/mapping",
        headers=bearer(token),
        json={
            "mapping": {"activity_code": "Code", "activity_name": "Title"},
            "save_profile_name": "Two Column Simple",
        },
    )

    # 2. List saved profiles in workspace
    list_res = await client.get(
        f"/api/v1/workspaces/{ws_id}/mappings",
        headers=bearer(token),
    )
    assert list_res.status_code == 200
    profiles = list_res.json()
    assert len(profiles) >= 1
    profile = next(p for p in profiles if p["name"] == "Two Column Simple")
    profile_id = profile["id"]

    # 3. Upload second file and reuse saved profile ID
    csv_2 = b"Code,Title\nT2,Task Two\nT3,Task Three\n"
    _, job_2, _ = await _upload_file(client, token, "f2.csv", csv_2)

    reuse_res = await client.post(
        f"/api/v1/imports/{job_2}/mapping",
        headers=bearer(token),
        json={"mapping_profile_id": profile_id},
    )
    assert reuse_res.status_code == 200
    assert reuse_res.json()["status"] == "preview_ready"
    assert reuse_res.json()["preview_summary"]["activities"] == 2


async def test_mapping_validates_duplicates_dates_and_percentages(client: AsyncClient) -> None:
    """PI-022: Validate dates, IDs, percentages, and duplicates."""
    token = make_token("auth0|map-user-5", email="m5@epc.test")
    # CSV with:
    # - Duplicate ID (ACT-1 appears twice)
    # - Inverted date range (Start 2026-05-10 > End 2026-05-01)
    # - Invalid date format ('not-a-valid-date')
    # - Percentage out of bounds (150%)
    invalid_csv = (
        b"Code,Name,Start,End,Progress\n"
        b"ACT-1,Task One,2026-05-10,2026-05-01,150%\n"
        b"ACT-1,Task Duplicate,not-a-valid-date,2026-06-01,80%\n"
    )

    _, job_id, _ = await _upload_file(client, token, "flawed.csv", invalid_csv)

    map_res = await client.post(
        f"/api/v1/imports/{job_id}/mapping",
        headers=bearer(token),
        json={
            "mapping": {
                "activity_code": "Code",
                "activity_name": "Name",
                "planned_start": "Start",
                "planned_finish": "End",
                "percent_complete": "Progress",
            }
        },
    )
    assert map_res.status_code == 200
    data = map_res.json()

    warnings = data["warnings"]
    warn_codes = {w["code"] for w in warnings}

    assert "DUPLICATE_ACTIVITY_ID" in warn_codes
    assert "INVALID_DATE_RANGE" in warn_codes
    assert "INVALID_DATE_FORMAT" in warn_codes
    assert "PERCENTAGE_OUT_OF_BOUNDS" in warn_codes


async def test_tenant_isolation_on_mapping(client: AsyncClient) -> None:
    """Tenant isolation: User B cannot inspect or map User A's import job."""
    user_a = make_token("auth0|user-a-map", email="ua@epc.test")
    user_b = make_token("auth0|user-b-map", email="ub@epc.test")

    csv_data = b"Code,Name\nA1,Task\n"
    _, job_a_id, _ = await _upload_file(client, user_a, "user_a.csv", csv_data)

    # User B tries to inspect User A's import file
    cross_inspect = await client.get(
        f"/api/v1/imports/{job_a_id}/inspect",
        headers=bearer(user_b),
    )
    assert cross_inspect.status_code == 404

    # User B tries to map User A's import job
    cross_map = await client.post(
        f"/api/v1/imports/{job_a_id}/mapping",
        headers=bearer(user_b),
        json={"mapping": {"activity_code": "Code", "activity_name": "Name"}},
    )
    assert cross_map.status_code == 404
