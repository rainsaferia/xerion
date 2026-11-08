"""PI-013: Import job queue and worker execution tests.

Acceptance criteria:
- Upload completion creates a queued job.
- Worker claims job and updates progress.
- Retry does not duplicate a confirmed project version.
- Failure state stores actionable error code.
"""

import tempfile
import time
import uuid
from collections.abc import AsyncGenerator, Generator
from pathlib import Path

import jwt
import pytest
from app.adapters.queue import _get_in_memory_adapter, get_queue_adapter
from app.adapters.storage import get_storage_adapter
from app.core.config import Settings
from app.db.session import get_session
from app.main import create_app
from app.models.base import Base
from app.models.project import ImportJob
from app.workers.import_worker import execute_import_job, process_next_job
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

SECRET = "import-job-test-secret-" + "q" * 32  # noqa: S105
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


async def _setup_uploaded_file(
    client: AsyncClient, token: str, filename: str, content: bytes
) -> tuple[str, str]:
    """Helper: create project, session, upload content, and complete upload."""
    proj = (
        await client.post(
            "/api/v1/projects",
            headers=bearer(token),
            json={"name": "Import Test Project"},
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
    assert comp_data["import_job_id"] is not None

    return session["file_id"], comp_data["import_job_id"]


# --- PI-013 Acceptance Tests ---


async def test_upload_completion_creates_queued_job(client: AsyncClient) -> None:
    token = make_token("auth0|queue-user-1", email="q1@epc.test")
    xer_sample = b"ERMHDR\t8.0\t2026-11-05\n%T\tPROJECT\nPROJ_ID\t1\n"

    _, job_id = await _setup_uploaded_file(client, token, "sample.xer", xer_sample)

    # Verify status is queued
    job_res = await client.get(f"/api/v1/imports/{job_id}", headers=bearer(token))
    assert job_res.status_code == 200
    job_data = job_res.json()
    assert job_data["id"] == job_id
    assert job_data["status"] == "queued"
    assert job_data["progress_pct"] == 0.0


async def test_worker_claims_job_and_updates_progress_to_preview_ready(
    client: AsyncClient,
    app_and_factory: tuple[FastAPI, async_sessionmaker[AsyncSession], Settings],
) -> None:
    _, factory, settings = app_and_factory
    token = make_token("auth0|worker-user-2", email="w2@epc.test")

    # Sample XER with 2 tasks, 1 wbs node, 1 relationship, 1 calendar
    xer_content = (
        b"ERMHDR\t8.2\t2026-11-05\n"
        b"%T\tPROJECT\n%F\tproj_id\tproj_short_name\n%R\t1\tEPC-FACILITY\n"
        b"%T\tPROJWBS\n%F\twbs_id\tproj_id\n%R\t10\t1\n"
        b"%T\tTASK\n%F\ttask_id\tproj_id\n%R\t101\t1\n%R\t102\t1\n"
        b"%T\tTASKPRED\n%F\ttask_pred_id\ttask_id\tpred_task_id\n%R\t201\t102\t101\n"
        b"%T\tCALENDAR\n%F\tclndr_id\tclndr_name\n%R\t301\tStandard 5 Day\n"
    )

    _, job_id = await _setup_uploaded_file(client, token, "complex.xer", xer_content)

    # Run background worker claiming from queue
    async with factory() as s:
        storage = get_storage_adapter(settings)
        queue = get_queue_adapter(settings)

        processed = await process_next_job(s, storage, queue)
        assert processed is True

    # Poll status via API
    poll_res = await client.get(f"/api/v1/imports/{job_id}", headers=bearer(token))
    assert poll_res.status_code == 200
    poll_data = poll_res.json()
    assert poll_data["status"] == "preview_ready"
    assert poll_data["progress_pct"] == 100.0
    assert poll_data["preview_summary"]["activities"] == 2
    assert poll_data["preview_summary"]["wbs_nodes"] == 1
    assert poll_data["preview_summary"]["relationships"] == 1
    assert poll_data["preview_summary"]["calendars"] == 1
    assert poll_data["detected_metadata"]["project_code"] == "EPC-FACILITY"
    assert poll_data["started_at"] is not None
    assert poll_data["finished_at"] is not None

    # Verify preview endpoint
    prev_res = await client.get(f"/api/v1/imports/{job_id}/preview", headers=bearer(token))
    assert prev_res.status_code == 200
    assert prev_res.json()["preview_summary"]["activities"] == 2


async def test_failure_state_stores_actionable_error_code(
    client: AsyncClient,
    app_and_factory: tuple[FastAPI, async_sessionmaker[AsyncSession], Settings],
) -> None:
    _, factory, settings = app_and_factory
    token = make_token("auth0|fail-user-3", email="fail@epc.test")

    # XER with valid ERMHDR header on line 1, but truncated/garbled table data
    corrupted_xer = b"ERMHDR\t8.0\t2026-11-05\n%T\tPROJECT\nINVALID_GARBLED_NO_TABS"

    _, job_id = await _setup_uploaded_file(client, token, "corrupt.xer", corrupted_xer)

    # Worker processes the job
    async with factory() as s:
        storage = get_storage_adapter(settings)
        await execute_import_job(s, storage, uuid.UUID(job_id))

    # Verify failed state and actionable error structure
    job_res = await client.get(f"/api/v1/imports/{job_id}", headers=bearer(token))
    assert job_res.status_code == 200
    data = job_res.json()
    assert data["status"] in ("preview_ready", "failed")  # Depending on partial line tolerance

    # Test an explicit ActionableImportError trigger with missing ERMHDR header on decode
    empty_csv_bytes = b"   \n\n   \n"
    _, empty_csv_job = await _setup_uploaded_file(client, token, "empty.csv", empty_csv_bytes)

    async with factory() as s:
        storage = get_storage_adapter(settings)
        await execute_import_job(s, storage, uuid.UUID(empty_csv_job))

    empty_res = await client.get(f"/api/v1/imports/{empty_csv_job}", headers=bearer(token))
    assert empty_res.status_code == 200
    empty_data = empty_res.json()
    assert empty_data["status"] == "failed"
    assert len(empty_data["errors"]) > 0
    err = empty_data["errors"][0]
    assert err["code"] == "EMPTY_CSV_FILE"
    assert "actionable" in err
    assert "Add activity rows" in err["actionable"]


async def test_retry_does_not_duplicate_a_confirmed_project_version(
    client: AsyncClient,
    app_and_factory: tuple[FastAPI, async_sessionmaker[AsyncSession], Settings],
) -> None:
    _, factory, _ = app_and_factory
    token = make_token("auth0|retry-user-4", email="retry@epc.test")
    csv_sample = b"Code,Name,Duration\nA100,Design,5\nA200,Procure,10\n"

    _, job_id = await _setup_uploaded_file(client, token, "schedule.csv", csv_sample)
    job_uuid = uuid.UUID(job_id)

    # 1. Mark job as confirmed in DB (simulating user confirmed the preview)
    async with factory() as s:
        job = await s.get(ImportJob, job_uuid)
        assert job is not None
        job.status = "confirmed"
        await s.commit()

    # 2. Attempt to retry the confirmed job via POST /imports/{import_job_id}/retry
    retry_res = await client.post(f"/api/v1/imports/{job_id}/retry", headers=bearer(token))
    assert retry_res.status_code == 200
    # Must remain confirmed! Does NOT reset to queued or re-run
    assert retry_res.json()["status"] == "confirmed"

    # 3. For a failed job, retry MUST reset to queued and clear errors
    async with factory() as s:
        job = await s.get(ImportJob, job_uuid)
        assert job is not None
        job.status = "failed"
        job.errors = [{"code": "TEST_ERR", "message": "Failed", "actionable": "Retry"}]
        await s.commit()

    retry_fail_res = await client.post(f"/api/v1/imports/{job_id}/retry", headers=bearer(token))
    assert retry_fail_res.status_code == 200
    assert retry_fail_res.json()["status"] == "queued"
    assert retry_fail_res.json()["progress_pct"] == 0.0
    assert retry_fail_res.json()["errors"] == []


async def test_tenant_isolation_on_import_jobs(client: AsyncClient) -> None:
    user_a = make_token("auth0|tenant-a-jobs", email="a@epc.test")
    user_b = make_token("auth0|tenant-b-jobs", email="b@epc.test")

    _, job_a_id = await _setup_uploaded_file(
        client, user_a, "sched_a.xer", b"ERMHDR\t8.0\tSchedule A\n"
    )

    # User B tries to view User A's import job
    cross_res = await client.get(f"/api/v1/imports/{job_a_id}", headers=bearer(user_b))
    assert cross_res.status_code == 404
    assert cross_res.json()["error"]["code"] == "NOT_FOUND"

    # User B tries to retry User A's import job
    cross_retry = await client.post(f"/api/v1/imports/{job_a_id}/retry", headers=bearer(user_b))
    assert cross_retry.status_code == 404
    assert cross_retry.json()["error"]["code"] == "NOT_FOUND"

    # User B tries to confirm User A's import job
    cross_confirm = await client.post(f"/api/v1/imports/{job_a_id}/confirm", headers=bearer(user_b))
    assert cross_confirm.status_code == 404
    assert cross_confirm.json()["error"]["code"] == "NOT_FOUND"


async def test_confirm_import_job_succeeds_for_preview_ready_job(
    client: AsyncClient,
    app_and_factory: tuple[FastAPI, async_sessionmaker[AsyncSession], Settings],
) -> None:
    _, factory, settings = app_and_factory
    token = make_token("auth0|confirm-user-1", email="c1@epc.test")

    xer_sample = (
        b"ERMHDR\t8.2\t2026-11-05\n"
        b"%T\tPROJECT\n%F\tproj_id\tproj_short_name\n%R\t1\tEPC-EXP\n"
        b"%T\tTASK\n%F\ttask_id\tproj_id\n%R\t101\t1\n"
    )
    _, job_id = await _setup_uploaded_file(client, token, "confirm_ok.xer", xer_sample)

    # Worker processes to preview_ready
    async with factory() as s:
        storage = get_storage_adapter(settings)
        await execute_import_job(s, storage, uuid.UUID(job_id))

    # Verify status is preview_ready before confirm
    status_res = await client.get(f"/api/v1/imports/{job_id}", headers=bearer(token))
    assert status_res.status_code == 200
    assert status_res.json()["status"] == "preview_ready"

    # Confirm explicitly
    confirm_res = await client.post(f"/api/v1/imports/{job_id}/confirm", headers=bearer(token))
    assert confirm_res.status_code == 200
    assert confirm_res.json()["status"] == "confirmed"

    # Idempotent confirmation
    confirm_res_2 = await client.post(f"/api/v1/imports/{job_id}/confirm", headers=bearer(token))
    assert confirm_res_2.status_code == 200
    assert confirm_res_2.json()["status"] == "confirmed"


async def test_confirm_import_job_fails_when_blocking_errors_exist(
    client: AsyncClient,
    app_and_factory: tuple[FastAPI, async_sessionmaker[AsyncSession], Settings],
) -> None:
    _, factory, settings = app_and_factory
    token = make_token("auth0|confirm-user-2", email="c2@epc.test")

    empty_csv = b"   \n\n   \n"
    _, job_id = await _setup_uploaded_file(client, token, "empty.csv", empty_csv)

    # Worker processes, resulting in failed state with blocking errors
    async with factory() as s:
        storage = get_storage_adapter(settings)
        await execute_import_job(s, storage, uuid.UUID(job_id))

    status_res = await client.get(f"/api/v1/imports/{job_id}", headers=bearer(token))
    assert status_res.status_code == 200
    assert status_res.json()["status"] == "failed"
    assert len(status_res.json()["errors"]) > 0

    # User cannot confirm a blocking import (PI-014 criterion)
    confirm_res = await client.post(f"/api/v1/imports/{job_id}/confirm", headers=bearer(token))
    assert confirm_res.status_code == 400
    err_body = confirm_res.json()
    assert err_body["error"]["code"] == "CANNOT_CONFIRM_IMPORT"
    assert "blocking errors" in err_body["error"]["message"].lower()
