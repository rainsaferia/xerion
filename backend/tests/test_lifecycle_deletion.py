"""PI-051: Project, file, and account deletion lifecycle tests."""

import tempfile
import time
import uuid
from collections.abc import AsyncGenerator, Generator
from datetime import UTC, datetime
from pathlib import Path

import jwt
import pytest
from app.adapters.storage.local import LocalStorageAdapter
from app.core.config import Settings, get_settings
from app.db.session import get_session
from app.main import create_app
from app.models.auth import User, Workspace, WorkspaceMember
from app.models.base import Base
from app.models.project import ImportJob, Project, ProjectVersion, UploadedFile
from app.models.reporting import Report
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

SECRET = "lifecycle-secret-" + "l" * 32
ISSUER = "https://auth.projectintelligence.local"
AUDIENCE = "pi-api"

USER_ID = uuid.uuid4()
WS_ID = uuid.uuid4()
PROJ_A_ID = uuid.uuid4()
PROJ_B_ID = uuid.uuid4()
FILE_ID = uuid.uuid4()
REPORT_ID = uuid.uuid4()
VERSION_ID = uuid.uuid4()
JOB_ID = uuid.uuid4()


def make_token(sub: str) -> str:
    claims: dict[str, object] = {
        "sub": sub,
        "iss": ISSUER,
        "aud": AUDIENCE,
        "exp": int(time.time()) + 300,
    }
    return jwt.encode(claims, SECRET, algorithm="HS256")


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def temp_storage_dir() -> Generator[Path, None, None]:
    with tempfile.TemporaryDirectory() as tmp_dir:
        yield Path(tmp_dir)


@pytest.fixture
async def app_fixture(
    temp_storage_dir: Path,
) -> AsyncGenerator[tuple[FastAPI, LocalStorageAdapter], None]:
    engine = create_async_engine(
        "sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )

    @event.listens_for(engine.sync_engine, "connect")
    def _fk_on(dbapi_conn, _record) -> None:  # type: ignore[no-untyped-def]
        dbapi_conn.execute("PRAGMA foreign_keys = ON")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)

    storage = LocalStorageAdapter(temp_storage_dir)
    file_key = f"uploads/{FILE_ID}/schedule.xer"
    report_key = f"reports/{REPORT_ID}/report.pdf"
    await storage.put_object(file_key, b"ERMHDR synthetic p6 content")
    await storage.put_object(report_key, b"%PDF-1.4 synthetic report content")

    async with factory() as s:
        s.add(User(id=USER_ID, auth_subject="sub|lifecycle_user", email="lifecycle@example.test"))
        await s.flush()
        s.add(Workspace(id=WS_ID, name="Lifecycle WS", owner_user_id=USER_ID))
        await s.flush()
        s.add(WorkspaceMember(workspace_id=WS_ID, user_id=USER_ID, role="owner", status="active"))
        s.add_all(
            [
                Project(id=PROJ_A_ID, workspace_id=WS_ID, name="Proj A", project_code="PRJ-A"),
                Project(id=PROJ_B_ID, workspace_id=WS_ID, name="Proj B", project_code="PRJ-B"),
            ]
        )
        await s.flush()
        s.add(
            UploadedFile(
                id=FILE_ID,
                workspace_id=WS_ID,
                project_id=PROJ_A_ID,
                uploaded_by=USER_ID,
                original_filename="schedule.xer",
                object_key=file_key,
                source_format="xer",
                file_size_bytes=100,
                sha256_checksum="abc",
            )
        )
        await s.flush()
        s.add(
            ImportJob(
                id=JOB_ID,
                workspace_id=WS_ID,
                project_id=PROJ_A_ID,
                uploaded_file_id=FILE_ID,
                status="confirmed",
                requested_by=USER_ID,
            )
        )
        await s.flush()
        s.add(
            ProjectVersion(
                id=VERSION_ID,
                workspace_id=WS_ID,
                project_id=PROJ_A_ID,
                import_job_id=JOB_ID,
                version_number=1,
                version_label="Rev 1",
                source_format="xer",
                data_date=datetime.now(UTC).date(),
            )
        )
        await s.flush()
        s.add(
            Report(
                id=REPORT_ID,
                workspace_id=WS_ID,
                project_id=PROJ_A_ID,
                project_version_id=VERSION_ID,
                report_type="schedule_health",
                title="Health Report",
                output_format="pdf",
                status="ready",
                object_key=report_key,
                generated_by=USER_ID,
            )
        )
        await s.commit()

    application = create_app()

    async def _session() -> AsyncGenerator[AsyncSession, None]:
        async with factory() as session:
            yield session

    test_settings = Settings(
        auth_jwt_secret=SecretStr(SECRET),
        auth_jwt_issuer=ISSUER,
        auth_jwt_audience=AUDIENCE,
        storage_local_dir=str(temp_storage_dir),
    )
    application.dependency_overrides[get_session] = _session
    application.dependency_overrides[get_settings] = lambda: test_settings

    yield application, storage
    await engine.dispose()


@pytest.fixture
async def client(
    app_fixture: tuple[FastAPI, LocalStorageAdapter],
) -> AsyncGenerator[AsyncClient, None]:
    app, _ = app_fixture
    token = make_token("sub|lifecycle_user")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", headers=bearer(token)
    ) as c:
        yield c


async def test_file_deletion_soft_deletes_and_purges_storage(
    client: AsyncClient, app_fixture: tuple[FastAPI, LocalStorageAdapter]
) -> None:
    _, storage = app_fixture
    file_key = f"uploads/{FILE_ID}/schedule.xer"
    assert await storage.exists(file_key)

    # Delete upload
    res = await client.delete(f"/api/v1/uploads/{FILE_ID}")
    assert res.status_code == 200
    assert res.json()["status"] == "deleted"

    # Storage object was purged
    assert not await storage.exists(file_key)

    # Subsequent GET returns 404
    res_get = await client.get(f"/api/v1/uploads/{FILE_ID}")
    assert res_get.status_code == 404


async def test_project_deletion_cascades_and_cleans_up_storage(
    client: AsyncClient, app_fixture: tuple[FastAPI, LocalStorageAdapter]
) -> None:
    _, storage = app_fixture
    file_key = f"uploads/{FILE_ID}/schedule.xer"
    report_key = f"reports/{REPORT_ID}/report.pdf"

    # Verify initial state
    res_a = await client.get(f"/api/v1/projects/{PROJ_A_ID}")
    assert res_a.status_code == 200

    # Delete project A
    del_res = await client.delete(f"/api/v1/projects/{PROJ_A_ID}")
    assert del_res.status_code == 200
    assert del_res.json()["status"] == "deleted"

    # Project A is now 404
    assert (await client.get(f"/api/v1/projects/{PROJ_A_ID}")).status_code == 404

    # Storage files and reports associated with Project A are cleaned up
    assert not await storage.exists(file_key)
    assert not await storage.exists(report_key)

    # Unrelated Project B remains accessible
    res_b = await client.get(f"/api/v1/projects/{PROJ_B_ID}")
    assert res_b.status_code == 200
    assert res_b.json()["name"] == "Proj B"


async def test_account_deletion_deactivates_user_and_memberships(
    client: AsyncClient,
) -> None:
    # Verify user can access /me
    res_me = await client.get("/api/v1/me")
    assert res_me.status_code == 200

    # Deactivate account
    del_res = await client.delete("/api/v1/me")
    assert del_res.status_code == 200
    assert del_res.json()["status"] == "deactivated"

    # Subsequent authenticated request fails closed with 401 UNAUTHENTICATED
    subsequent_res = await client.get("/api/v1/me")
    assert subsequent_res.status_code == 401
    assert subsequent_res.json()["error"]["message"] == "Account is deactivated."
