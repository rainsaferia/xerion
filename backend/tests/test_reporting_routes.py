"""PI-046: PDF Schedule report route integration tests.

Acceptance criteria:
- Report references exact project version and data date.
- Includes overview, methodology, findings, limitations, and generation timestamp.
- Generated file stored privately.
- Download is authorized and short-lived.
- Strict multi-tenant isolation via ProjectAccess and workspace boundary.
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

SECRET = "reporting-route-secret-" + "s" * 32  # noqa: S105
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
        json={"name": "Gas Processing Facility Schedule Analysis"},
    )
    assert proj_res.status_code == 201
    project_id = proj_res.json()["id"]

    xer_bytes = (FIXTURES_DIR / fixture_name).read_bytes()
    upload_init = (
        await client.post(
            f"/api/v1/projects/{project_id}/uploads",
            headers=bearer(token),
            json={
                "filename": fixture_name,
                "file_size_bytes": len(xer_bytes),
                "source_format": "xer",
            },
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

    async with factory() as session:
        storage = get_storage_adapter(settings)
        await execute_import_job(session, storage, uuid.UUID(job_id))

    confirm_res = (
        await client.post(
            f"/api/v1/imports/{job_id}/confirm",
            headers=bearer(token),
            json={"acknowledgement": True},
        )
    ).json()
    version_id = confirm_res["project_version_id"]

    return project_id, version_id, job_id


async def test_create_and_download_schedule_report_flow(
    client: AsyncClient,
    app_and_factory: tuple[FastAPI, async_sessionmaker[AsyncSession], Settings],
) -> None:
    _, factory, settings = app_and_factory
    token = make_token("user-report-planner", email="planner@epc.test")

    project_id, version_id, _ = await _setup_project_with_xer(client, factory, settings, token)

    # 1. Generate Report via POST /projects/{project_id}/reports
    post_res = await client.post(
        f"/api/v1/projects/{project_id}/reports",
        headers=bearer(token),
        json={
            "version_id": version_id,
            "report_type": "schedule_analysis",
            "format": "pdf",
            "options": {"include_activity_appendix": False},
        },
    )
    assert post_res.status_code == 200, post_res.text
    rep_data = post_res.json()
    assert rep_data["status"] == "ready"
    assert rep_data["output_format"] == "pdf"
    assert "Schedule Analysis" in rep_data["title"]
    report_id = rep_data["id"]

    # 2. Inspect metadata via GET /reports/{report_id}
    meta_res = await client.get(f"/api/v1/reports/{report_id}", headers=bearer(token))
    assert meta_res.status_code == 200
    meta_json = meta_res.json()
    assert meta_json["id"] == report_id
    assert meta_json["status"] == "ready"
    assert meta_json["download_url"] == f"/api/v1/reports/{report_id}/download"

    # 3. Request short-lived download URL via GET /reports/{report_id}/download
    dl_res = await client.get(f"/api/v1/reports/{report_id}/download", headers=bearer(token))
    assert dl_res.status_code == 200
    dl_json = dl_res.json()
    download_url = dl_json["download_url"]
    assert f"/api/v1/reports/{report_id}/content?token=" in download_url
    assert "expires_at" in dl_json

    # 4. Stream PDF using short-lived query token (without Bearer header)
    stream_res = await client.get(download_url)
    assert stream_res.status_code == 200
    assert stream_res.headers["content-type"] == "application/pdf"
    assert "attachment" in stream_res.headers["content-disposition"]
    pdf_bytes = stream_res.content
    assert pdf_bytes.startswith(b"%PDF-")
    assert len(pdf_bytes) > 2000

    # 5. Stream PDF using Bearer header directly
    stream_bearer_res = await client.get(
        f"/api/v1/reports/{report_id}/content", headers=bearer(token)
    )
    assert stream_bearer_res.status_code == 200
    assert stream_bearer_res.content.startswith(b"%PDF-")


async def test_report_download_invalid_token_rejected(
    client: AsyncClient,
    app_and_factory: tuple[FastAPI, async_sessionmaker[AsyncSession], Settings],
) -> None:
    _, factory, settings = app_and_factory
    token = make_token("user-report-planner-2", email="planner2@epc.test")

    project_id, version_id, _ = await _setup_project_with_xer(client, factory, settings, token)

    post_res = await client.post(
        f"/api/v1/projects/{project_id}/reports",
        headers=bearer(token),
        json={"version_id": version_id, "format": "pdf"},
    )
    report_id = post_res.json()["id"]

    # Attempt download with corrupted token
    res = await client.get(f"/api/v1/reports/{report_id}/content?token=invalid-tampered-token")
    assert res.status_code in (401, 403)


async def test_tenant_isolation_unauthorized_report_access(
    client: AsyncClient,
    app_and_factory: tuple[FastAPI, async_sessionmaker[AsyncSession], Settings],
) -> None:
    _, factory, settings = app_and_factory
    token_tenant_a = make_token("user-tenant-a", email="a@tenant.test")
    token_tenant_b = make_token("user-tenant-b", email="b@tenant.test")

    project_id, version_id, _ = await _setup_project_with_xer(
        client, factory, settings, token_tenant_a
    )

    post_res = await client.post(
        f"/api/v1/projects/{project_id}/reports",
        headers=bearer(token_tenant_a),
        json={"version_id": version_id, "format": "pdf"},
    )
    report_id = post_res.json()["id"]

    # Tenant B tries to get Tenant A's report
    b_res = await client.get(f"/api/v1/reports/{report_id}", headers=bearer(token_tenant_b))
    assert b_res.status_code == 404


async def test_create_and_download_activity_export_csv_and_xlsx(
    client: AsyncClient,
    app_and_factory: tuple[FastAPI, async_sessionmaker[AsyncSession], Settings],
) -> None:
    _, factory, settings = app_and_factory
    token = make_token("user-report-planner-export", email="export_planner@epc.test")

    project_id, version_id, _ = await _setup_project_with_xer(client, factory, settings, token)

    # 1. Export CSV
    csv_res = await client.post(
        f"/api/v1/projects/{project_id}/exports/activities",
        headers=bearer(token),
        json={"version_id": version_id, "format": "csv"},
    )
    assert csv_res.status_code == 200
    csv_body = csv_res.json()
    assert csv_body["report_type"] == "activity_export"
    assert csv_body["output_format"] == "csv"
    assert csv_body["status"] == "ready"
    assert csv_body["download_url"] is not None

    # Get download token
    dl_res = await client.get(
        f"/api/v1/reports/{csv_body['id']}/download",
        headers=bearer(token),
    )
    assert dl_res.status_code == 200
    content_url = dl_res.json()["download_url"]

    # Stream CSV content using token
    stream_res = await client.get(content_url)
    assert stream_res.status_code == 200
    assert "text/csv" in stream_res.headers.get("content-type", "")
    assert stream_res.content.startswith(b"\xef\xbb\xbf")
    assert b"Activity ID" in stream_res.content

    # 2. Export XLSX
    xlsx_res = await client.post(
        f"/api/v1/projects/{project_id}/exports/activities",
        headers=bearer(token),
        json={"version_id": version_id, "format": "xlsx", "critical_only": True},
    )
    assert xlsx_res.status_code == 200
    xlsx_body = xlsx_res.json()
    assert xlsx_body["output_format"] == "xlsx"

    # Stream XLSX content with Bearer
    xlsx_stream = await client.get(
        f"/api/v1/reports/{xlsx_body['id']}/content",
        headers=bearer(token),
    )
    assert xlsx_stream.status_code == 200
    assert "spreadsheetml" in xlsx_stream.headers.get("content-type", "")
    assert xlsx_stream.content.startswith(b"PK")
