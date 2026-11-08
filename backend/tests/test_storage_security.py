"""PI-051: Private storage and signed download URL security tests."""

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
from app.domains.reporting.service import create_report_download_token
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

SECRET = "storage-security-secret-" + "s" * 32
ISSUER = "https://auth.projectintelligence.local"
AUDIENCE = "pi-api"

USER_ID = uuid.uuid4()
WS_ID = uuid.uuid4()
PROJECT_ID = uuid.uuid4()
VERSION_ID = uuid.uuid4()
UPLOAD_ID = uuid.uuid4()
JOB_ID = uuid.uuid4()
REPORT_A_ID = uuid.uuid4()
REPORT_B_ID = uuid.uuid4()


def make_token(
    sub: str,
    *,
    secret: str = SECRET,
    exp_offset: int = 300,
    scope: str | None = None,
) -> str:
    claims: dict[str, object] = {
        "sub": sub,
        "iss": ISSUER,
        "aud": AUDIENCE,
        "exp": int(time.time()) + exp_offset,
    }
    if scope:
        claims["scope"] = scope
    return jwt.encode(claims, secret, algorithm="HS256")


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def temp_storage_dir() -> Generator[Path, None, None]:
    with tempfile.TemporaryDirectory() as tmp_dir:
        yield Path(tmp_dir)


@pytest.fixture
async def app_and_storage(
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
    await storage.put_object("reports/report_a.pdf", b"%PDF-1.4 Report A Content")
    await storage.put_object("reports/report_b.pdf", b"%PDF-1.4 Report B Content")

    async with factory() as s:
        s.add(User(id=USER_ID, auth_subject="sub|storage_user", email="user@example.test"))
        await s.flush()
        s.add(Workspace(id=WS_ID, name="Storage WS", owner_user_id=USER_ID))
        await s.flush()
        s.add(WorkspaceMember(workspace_id=WS_ID, user_id=USER_ID, role="owner", status="active"))
        s.add(Project(id=PROJECT_ID, workspace_id=WS_ID, name="Storage Proj"))
        await s.flush()
        s.add(
            UploadedFile(
                id=UPLOAD_ID,
                workspace_id=WS_ID,
                project_id=PROJECT_ID,
                uploaded_by=USER_ID,
                original_filename="schedule.xer",
                object_key="uploads/schedule.xer",
                source_format="xer",
                file_size_bytes=1000,
                sha256_checksum="abc",
            )
        )
        await s.flush()
        s.add(
            ImportJob(
                id=JOB_ID,
                workspace_id=WS_ID,
                project_id=PROJECT_ID,
                uploaded_file_id=UPLOAD_ID,
                status="confirmed",
                requested_by=USER_ID,
            )
        )
        await s.flush()
        s.add(
            ProjectVersion(
                id=VERSION_ID,
                workspace_id=WS_ID,
                project_id=PROJECT_ID,
                import_job_id=JOB_ID,
                version_number=1,
                version_label="Rev 1",
                source_format="xer",
                data_date=datetime.now(UTC).date(),
            )
        )
        await s.flush()
        s.add_all(
            [
                Report(
                    id=REPORT_A_ID,
                    workspace_id=WS_ID,
                    project_id=PROJECT_ID,
                    project_version_id=VERSION_ID,
                    report_type="schedule_health",
                    title="Health Report A",
                    output_format="pdf",
                    status="ready",
                    object_key="reports/report_a.pdf",
                    generated_by=USER_ID,
                ),
                Report(
                    id=REPORT_B_ID,
                    workspace_id=WS_ID,
                    project_id=PROJECT_ID,
                    project_version_id=VERSION_ID,
                    report_type="schedule_health",
                    title="Health Report B",
                    output_format="pdf",
                    status="ready",
                    object_key="reports/report_b.pdf",
                    generated_by=USER_ID,
                ),
            ]
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


@pytest.mark.parametrize(
    "malicious_key",
    [
        "../../etc/passwd",
        "..\\..\\windows\\system32\\cmd.exe",
        "C:\\Windows\\System32\\cmd.exe",
        "/../../etc/shadow",
        "nested/../../secret",
    ],
)
async def test_local_storage_adapter_rejects_path_traversal(
    temp_storage_dir: Path, malicious_key: str
) -> None:
    storage = LocalStorageAdapter(temp_storage_dir)

    with pytest.raises(ValueError, match="Path traversal"):
        await storage.put_object(malicious_key, b"data")

    with pytest.raises(ValueError, match="Path traversal"):
        await storage.get_object(malicious_key)

    with pytest.raises(ValueError, match="Path traversal"):
        await storage.delete_object(malicious_key)

    with pytest.raises(ValueError, match="Path traversal"):
        await storage.exists(malicious_key)


async def test_signed_download_token_valid(
    app_and_storage: tuple[FastAPI, LocalStorageAdapter],
) -> None:
    app, _ = app_and_storage
    token = create_report_download_token(
        report_id=REPORT_A_ID,
        project_id=PROJECT_ID,
        workspace_id=WS_ID,
        user_id=USER_ID,
        auth_subject="sub|storage_user",
        secret_key=SECRET,
        expires_in_seconds=300,
        issuer=ISSUER,
        audience=AUDIENCE,
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get(f"/api/v1/reports/{REPORT_A_ID}/content?token={token}")
        assert res.status_code == 200
        assert res.content == b"%PDF-1.4 Report A Content"
        assert res.headers["X-Content-Type-Options"] == "nosniff"
        assert res.headers["X-Frame-Options"] == "DENY"
        assert "private" in res.headers["Cache-Control"]


async def test_signed_download_token_expired_rejected(
    app_and_storage: tuple[FastAPI, LocalStorageAdapter],
) -> None:
    app, _ = app_and_storage
    token = create_report_download_token(
        report_id=REPORT_A_ID,
        project_id=PROJECT_ID,
        workspace_id=WS_ID,
        user_id=USER_ID,
        auth_subject="sub|storage_user",
        secret_key=SECRET,
        expires_in_seconds=-10,  # Expired
        issuer=ISSUER,
        audience=AUDIENCE,
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get(f"/api/v1/reports/{REPORT_A_ID}/content?token={token}")
        # Rejected due to expired token
        assert res.status_code in {401, 403}


async def test_signed_download_token_tampered_signature_rejected(
    app_and_storage: tuple[FastAPI, LocalStorageAdapter],
) -> None:
    app, _ = app_and_storage
    token = create_report_download_token(
        report_id=REPORT_A_ID,
        project_id=PROJECT_ID,
        workspace_id=WS_ID,
        user_id=USER_ID,
        auth_subject="sub|storage_user",
        secret_key="wrong-secret-" + "w" * 32,
        expires_in_seconds=300,
        issuer=ISSUER,
        audience=AUDIENCE,
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get(f"/api/v1/reports/{REPORT_A_ID}/content?token={token}")
        assert res.status_code in {401, 403}


async def test_signed_download_token_report_mismatch_rejected(
    app_and_storage: tuple[FastAPI, LocalStorageAdapter],
) -> None:
    app, _ = app_and_storage
    # Token minted for REPORT_A
    token_a = create_report_download_token(
        report_id=REPORT_A_ID,
        project_id=PROJECT_ID,
        workspace_id=WS_ID,
        user_id=USER_ID,
        auth_subject="sub|storage_user",
        secret_key=SECRET,
        expires_in_seconds=300,
        issuer=ISSUER,
        audience=AUDIENCE,
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Attempt to use token_a on REPORT_B
        res = await client.get(f"/api/v1/reports/{REPORT_B_ID}/content?token={token_a}")
        assert res.status_code == 403
        assert res.json()["error"]["message"] == "Token does not match report ID."


async def test_scoped_download_token_cannot_access_general_api(
    app_and_storage: tuple[FastAPI, LocalStorageAdapter],
) -> None:
    app, _ = app_and_storage
    download_token = create_report_download_token(
        report_id=REPORT_A_ID,
        project_id=PROJECT_ID,
        workspace_id=WS_ID,
        user_id=USER_ID,
        auth_subject="sub|storage_user",
        secret_key=SECRET,
        expires_in_seconds=300,
        issuer=ISSUER,
        audience=AUDIENCE,
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Attempting to use download token as general auth
        res_projects = await client.get(f"/api/v1/projects/{PROJECT_ID}?token={download_token}")
        assert res_projects.status_code == 403
        assert (
            "Download token cannot be used to access this resource"
            in res_projects.json()["error"]["message"]
        )
