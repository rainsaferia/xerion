"""PI-012: Secure upload session and file safety tests.

Acceptance criteria:
- Only supported extensions/content types accepted.
- Actual file signature is checked after upload.
- File stored in private object storage.
- Size limit configurable.
- Checksum stored.
- Public access to object is denied.
"""

import hashlib
import tempfile
import time
from collections.abc import AsyncGenerator, Generator
from pathlib import Path

import jwt
import pytest
from app.adapters.storage.local import LocalStorageAdapter
from app.core.config import Settings, get_settings
from app.db.session import get_session
from app.domains.ingestion.safety import (
    compute_sha256,
    detect_and_validate_extension,
    validate_file_payload,
)
from app.main import create_app
from app.models.base import Base
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

SECRET = "upload-test-secret-" + "u" * 32  # noqa: S105
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
) -> AsyncGenerator[tuple[FastAPI, async_sessionmaker[AsyncSession]], None]:
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
        upload_max_size_bytes=1024 * 1024,  # 1MB limit for tests
    )

    application.dependency_overrides[get_session] = _session
    application.dependency_overrides[get_settings] = lambda: test_settings

    yield application, factory
    await engine.dispose()


@pytest.fixture
async def client(
    app_and_factory: tuple[FastAPI, async_sessionmaker[AsyncSession]],
) -> AsyncGenerator[AsyncClient, None]:
    app, _ = app_and_factory
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


# --- Unit Safety Validation Tests ---


def test_detect_and_validate_extension() -> None:
    assert detect_and_validate_extension("project_schedule.xer") == "xer"
    assert detect_and_validate_extension("activities.XLSX") == "xlsx"
    assert detect_and_validate_extension("data.csv") == "csv"

    with pytest.raises(ValueError, match="Unsupported file extension"):
        detect_and_validate_extension("malware.exe")

    with pytest.raises(ValueError, match="Unsupported file extension"):
        detect_and_validate_extension("script.sh")


def test_validate_file_payload_xer_magic() -> None:
    valid_xer = b"ERMHDR\t8.0\t2026-11-01\n%T\tPROJECT\nPROJ_ID\t1\n"
    fmt, size, checksum = validate_file_payload(valid_xer, "sample.xer", 1024 * 1024)
    assert fmt == "xer"
    assert size == len(valid_xer)
    assert checksum == hashlib.sha256(valid_xer).hexdigest()

    # Masquerading fake XER (e.g. binary or wrong header)
    fake_xer = b"NOT_ERMHDR binary content here"
    with pytest.raises(ValueError, match="Invalid XER file signature"):
        validate_file_payload(fake_xer, "fake.xer", 1024 * 1024)


def test_validate_file_payload_xlsx_magic() -> None:
    # Valid ZIP header PK\x03\x04
    valid_xlsx = b"PK\x03\x04" + b"\x00" * 100
    fmt, size, checksum = validate_file_payload(valid_xlsx, "book.xlsx", 1024 * 1024)
    assert fmt == "xlsx"
    assert size == len(valid_xlsx)

    fake_xlsx = b"NOT_A_ZIP_CONTAINER"
    with pytest.raises(ValueError, match="Invalid XLSX file signature"):
        validate_file_payload(fake_xlsx, "fake.xlsx", 1024 * 1024)


def test_validate_file_payload_csv_null_byte_rejection() -> None:
    valid_csv = b"Activity_ID,Activity_Name,Duration\nA100,Engineering,10\n"
    fmt, size, checksum = validate_file_payload(valid_csv, "tasks.csv", 1024 * 1024)
    assert fmt == "csv"

    # Binary executable disguised as CSV (contains null bytes)
    disguised_binary = b"Activity_ID\x00\x00\x01\x02binary_payload"
    with pytest.raises(ValueError, match="Binary content or null bytes detected"):
        validate_file_payload(disguised_binary, "evil.csv", 1024 * 1024)


# --- Local Storage Path Traversal Protection ---


async def test_local_storage_prevents_path_traversal(temp_storage_dir: Path) -> None:
    adapter = LocalStorageAdapter(temp_storage_dir)

    # Legitimate save
    await adapter.put_object("workspaces/1/file.xer", b"ERMHDR data")
    assert await adapter.exists("workspaces/1/file.xer")

    # Path traversal attempts
    with pytest.raises(ValueError, match="Path traversal detected"):
        await adapter.put_object("../../etc/passwd", b"evil")

    with pytest.raises(ValueError, match="Path traversal detected"):
        await adapter.get_object("../../../windows/system32/cmd.exe")


# --- End-to-End API Upload Flow ---


async def test_end_to_end_xer_upload_lifecycle(client: AsyncClient) -> None:
    token = make_token("auth0|uploader-01", email="uploader@epc.test")

    # 1. Create a project
    proj_res = await client.post(
        "/api/v1/projects",
        headers=bearer(token),
        json={"name": "Upload Target Project", "timezone": "Asia/Jakarta"},
    )
    assert proj_res.status_code == 201
    proj_id = proj_res.json()["id"]

    # 2. Initiate upload session
    session_res = await client.post(
        f"/api/v1/projects/{proj_id}/uploads",
        headers=bearer(token),
        json={"filename": "Schedule_Nov2026.xer", "file_size_bytes": 1024},
    )
    assert session_res.status_code == 201
    session_data = session_res.json()
    file_id = session_data["file_id"]
    upload_url = session_data["upload_url"]
    assert session_data["upload_method"] == "direct"
    assert session_data["max_size_bytes"] == 1024 * 1024

    # 3. Upload content via PUT
    sample_xer_bytes = b"ERMHDR\t8.2\t2026-11-05\n%T\tTASK\ntask_code\tA10\n"
    put_res = await client.put(
        upload_url,
        headers={**bearer(token), "Content-Type": "application/octet-stream"},
        content=sample_xer_bytes,
    )
    assert put_res.status_code == 200
    upload_data = put_res.json()
    assert upload_data["id"] == file_id
    assert upload_data["file_size_bytes"] == len(sample_xer_bytes)
    assert upload_data["sha256_checksum"] == compute_sha256(sample_xer_bytes)
    assert upload_data["storage_status"] == "private"
    assert "object_key" not in upload_data  # Internal storage path never exposed to client

    # 4. Complete upload
    complete_res = await client.post(
        f"/api/v1/uploads/{file_id}/complete",
        headers=bearer(token),
    )
    assert complete_res.status_code == 200
    assert complete_res.json()["id"] == file_id

    # 5. Retrieve metadata
    meta_res = await client.get(
        f"/api/v1/uploads/{file_id}",
        headers=bearer(token),
    )
    assert meta_res.status_code == 200
    assert meta_res.json()["original_filename"] == "Schedule_Nov2026.xer"
    assert meta_res.json()["source_format"] == "xer"

    # 6. Delete file
    del_res = await client.delete(
        f"/api/v1/uploads/{file_id}",
        headers=bearer(token),
    )
    assert del_res.status_code == 200
    assert del_res.json()["status"] == "deleted"

    # Subsequent GET returns 404 (soft-deleted)
    gone_res = await client.get(
        f"/api/v1/uploads/{file_id}",
        headers=bearer(token),
    )
    assert gone_res.status_code == 404


async def test_upload_session_unsupported_extension_rejected(client: AsyncClient) -> None:
    token = make_token("auth0|ext-tester", email="ext@epc.test")

    proj = (
        await client.post(
            "/api/v1/projects",
            headers=bearer(token),
            json={"name": "Ext Check Proj"},
        )
    ).json()

    res = await client.post(
        f"/api/v1/projects/{proj['id']}/uploads",
        headers=bearer(token),
        json={"filename": "malicious_script.bat"},
    )
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "VALIDATION_ERROR"
    assert "Unsupported file extension" in res.json()["error"]["message"]


async def test_upload_content_signature_mismatch_rejected(client: AsyncClient) -> None:
    token = make_token("auth0|sig-tester", email="sig@epc.test")

    proj = (
        await client.post(
            "/api/v1/projects",
            headers=bearer(token),
            json={"name": "Sig Check Proj"},
        )
    ).json()

    session_res = (
        await client.post(
            f"/api/v1/projects/{proj['id']}/uploads",
            headers=bearer(token),
            json={"filename": "fake_schedule.xer"},
        )
    ).json()

    # Upload corrupt/executable bytes under .xer extension
    corrupt_bytes = b"MZ\x90\x00\x03\x00\x00\x00WindowsPE_executable_binary"
    put_res = await client.put(
        session_res["upload_url"],
        headers=bearer(token),
        content=corrupt_bytes,
    )
    assert put_res.status_code == 422
    assert put_res.json()["error"]["code"] == "VALIDATION_ERROR"
    assert "Invalid XER file signature" in put_res.json()["error"]["message"]


async def test_upload_exceeding_max_size_limit_rejected(client: AsyncClient) -> None:
    token = make_token("auth0|size-tester", email="size@epc.test")

    proj = (
        await client.post(
            "/api/v1/projects",
            headers=bearer(token),
            json={"name": "Size Check Proj"},
        )
    ).json()

    # 1. Declared size exceeds test limit (1MB = 1048576)
    session_res = await client.post(
        f"/api/v1/projects/{proj['id']}/uploads",
        headers=bearer(token),
        json={"filename": "huge.xer", "file_size_bytes": 2 * 1024 * 1024},
    )
    assert session_res.status_code == 422
    assert "exceeds maximum allowed limit" in session_res.json()["error"]["message"]

    # 2. Actual uploaded bytes exceed limit
    valid_session = (
        await client.post(
            f"/api/v1/projects/{proj['id']}/uploads",
            headers=bearer(token),
            json={"filename": "huge_actual.xer"},
        )
    ).json()

    oversized_data = b"ERMHDR" + b"X" * (1024 * 1024 + 50)
    put_res = await client.put(
        valid_session["upload_url"],
        headers=bearer(token),
        content=oversized_data,
    )
    assert put_res.status_code == 422
    assert "exceeds maximum limit" in put_res.json()["error"]["message"]


async def test_public_and_cross_tenant_access_denied(client: AsyncClient) -> None:
    user_a = make_token("auth0|tenant-a", email="a@epc.test")
    user_b = make_token("auth0|tenant-b", email="b@epc.test")

    # User A creates project and uploads file
    proj_a = (
        await client.post(
            "/api/v1/projects",
            headers=bearer(user_a),
            json={"name": "Tenant A Secret Project"},
        )
    ).json()

    session_a = (
        await client.post(
            f"/api/v1/projects/{proj_a['id']}/uploads",
            headers=bearer(user_a),
            json={"filename": "secret.xer"},
        )
    ).json()

    put_res = await client.put(
        session_a["upload_url"],
        headers=bearer(user_a),
        content=b"ERMHDR\tConfidential schedule",
    )
    file_id = put_res.json()["id"]

    # 1. Public unauthenticated access is denied (401)
    unauth_res = await client.get(f"/api/v1/uploads/{file_id}")
    assert unauth_res.status_code == 401
    assert unauth_res.json()["error"]["code"] == "UNAUTHENTICATED"

    # 2. Cross-tenant access by User B is denied (404 anti-enumeration)
    cross_res = await client.get(
        f"/api/v1/uploads/{file_id}",
        headers=bearer(user_b),
    )
    assert cross_res.status_code == 404
    assert cross_res.json()["error"]["code"] == "NOT_FOUND"
