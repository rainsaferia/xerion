"""PI-023: Immutable project versions and canonical materialization tests.

Acceptance criteria (08_DEVELOPMENT_BACKLOG.md PI-023):
- Confirmed import creates next sequential version number (1, 2, ...).
- Prior version records remain unchanged (isolated by project_version_id).
- projects.latest_version_id updates only after version is ready.
- Version list shows data date, source file, parser version, and activity count.
- Version detail shows quality summary and canonical metadata.
- Strict tenant isolation across version endpoints.
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
from app.db.session import get_session
from app.main import create_app
from app.models.base import Base
from app.models.project import Project, ProjectVersion
from app.models.schedule import Activity, ActivityRelationship, Calendar, WBSNode
from app.workers.import_worker import execute_import_job
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

SECRET = "version-test-secret-" + "v" * 32  # noqa: S105
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


async def _upload_and_process_file(
    client: AsyncClient,
    factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    token: str,
    project_id: str,
    filename: str,
    content: bytes,
) -> str:
    """Helper to upload a file and run the worker synchronously."""
    upload_init = (
        await client.post(
            f"/api/v1/projects/{project_id}/uploads",
            headers=bearer(token),
            json={"filename": filename},
        )
    ).json()

    put_res = await client.put(
        upload_init["upload_url"],
        headers=bearer(token),
        content=content,
    )
    assert put_res.status_code == 200

    complete_res = (
        await client.post(
            f"/api/v1/uploads/{upload_init['file_id']}/complete",
            headers=bearer(token),
        )
    ).json()
    job_id = str(complete_res["import_job_id"])

    # Worker processes the job
    async with factory() as s:
        storage = get_storage_adapter(settings)
        await execute_import_job(s, storage, uuid.UUID(job_id))

    return job_id


# --- Tests ---


async def test_confirmed_import_creates_next_version_number(
    client: AsyncClient,
    app_and_factory: tuple[FastAPI, async_sessionmaker[AsyncSession], Settings],
) -> None:
    _, factory, settings = app_and_factory
    token = make_token("auth0|version-user-1", email="v1@epc.test")

    # 1. Create project
    proj_res = await client.post(
        "/api/v1/projects",
        headers=bearer(token),
        json={"name": "Offshore Processing Plant"},
    )
    assert proj_res.status_code == 201
    project_id = proj_res.json()["id"]

    # Read XER fixture files
    xer_v1_bytes = (FIXTURES_DIR / "p6_release_82_facility.xer").read_bytes()
    xer_v2_bytes = (FIXTURES_DIR / "p6_release_20_pipeline.xer").read_bytes()

    # 2. Upload first XER and confirm -> Version 1
    job_1_id = await _upload_and_process_file(
        client, factory, settings, token, project_id, "facility.xer", xer_v1_bytes
    )
    confirm_1 = await client.post(f"/api/v1/imports/{job_1_id}/confirm", headers=bearer(token))
    assert confirm_1.status_code == 200
    confirm_1_data = confirm_1.json()
    assert confirm_1_data["status"] == "confirmed"
    v1_id = confirm_1_data["project_version_id"]
    assert v1_id is not None

    async with factory() as s:
        v1 = await s.get(ProjectVersion, uuid.UUID(v1_id))
        assert v1 is not None
        assert v1.version_number == 1
        assert v1.version_label == "V1"
        assert v1.status == "ready"

    # 3. Upload second XER to same project and confirm -> Version 2
    job_2_id = await _upload_and_process_file(
        client, factory, settings, token, project_id, "pipeline.xer", xer_v2_bytes
    )
    confirm_2 = await client.post(f"/api/v1/imports/{job_2_id}/confirm", headers=bearer(token))
    assert confirm_2.status_code == 200
    confirm_2_data = confirm_2.json()
    assert confirm_2_data["status"] == "confirmed"
    v2_id = confirm_2_data["project_version_id"]
    assert v2_id is not None
    assert v2_id != v1_id

    async with factory() as s:
        v2 = await s.get(ProjectVersion, uuid.UUID(v2_id))
        assert v2 is not None
        assert v2.version_number == 2
        assert v2.version_label == "V2"
        assert v2.status == "ready"


async def test_prior_version_records_remain_unchanged(
    client: AsyncClient,
    app_and_factory: tuple[FastAPI, async_sessionmaker[AsyncSession], Settings],
) -> None:
    _, factory, settings = app_and_factory
    token = make_token("auth0|immutability-user", email="imm@epc.test")

    proj_res = await client.post(
        "/api/v1/projects",
        headers=bearer(token),
        json={"name": "LNG Terminal Complex"},
    )
    project_id = proj_res.json()["id"]

    xer_v1_bytes = (FIXTURES_DIR / "p6_release_82_facility.xer").read_bytes()
    xer_v2_bytes = (FIXTURES_DIR / "p6_release_20_pipeline.xer").read_bytes()

    # Upload & confirm V1
    job_1_id = await _upload_and_process_file(
        client, factory, settings, token, project_id, "v1.xer", xer_v1_bytes
    )
    c1 = (await client.post(f"/api/v1/imports/{job_1_id}/confirm", headers=bearer(token))).json()
    v1_uuid = uuid.UUID(c1["project_version_id"])

    # Inspect V1 activity count and activity IDs
    async with factory() as s:
        v1_activities = (
            (await s.execute(select(Activity).where(Activity.project_version_id == v1_uuid)))
            .scalars()
            .all()
        )
        v1_wbs = (
            (await s.execute(select(WBSNode).where(WBSNode.project_version_id == v1_uuid)))
            .scalars()
            .all()
        )
        v1_rels = (
            (
                await s.execute(
                    select(ActivityRelationship).where(
                        ActivityRelationship.project_version_id == v1_uuid
                    )
                )
            )
            .scalars()
            .all()
        )
        v1_cals = (
            (await s.execute(select(Calendar).where(Calendar.project_version_id == v1_uuid)))
            .scalars()
            .all()
        )

        v1_act_count = len(v1_activities)
        v1_act_ids = {a.id for a in v1_activities}
        assert v1_act_count == 5
        assert len(v1_wbs) == 4
        assert len(v1_rels) == 5
        assert len(v1_cals) == 2

    # Upload & confirm V2
    job_2_id = await _upload_and_process_file(
        client, factory, settings, token, project_id, "v2.xer", xer_v2_bytes
    )
    c2 = (await client.post(f"/api/v1/imports/{job_2_id}/confirm", headers=bearer(token))).json()
    v2_uuid = uuid.UUID(c2["project_version_id"])

    # Re-verify V1 records: strict immutability check
    async with factory() as s:
        v1_activities_post = (
            (await s.execute(select(Activity).where(Activity.project_version_id == v1_uuid)))
            .scalars()
            .all()
        )
        v2_activities = (
            (await s.execute(select(Activity).where(Activity.project_version_id == v2_uuid)))
            .scalars()
            .all()
        )

        # V1 records must be completely identical and unaltered
        assert len(v1_activities_post) == v1_act_count
        assert {a.id for a in v1_activities_post} == v1_act_ids

        # V2 activities must be disjoint and distinct
        v2_act_ids = {a.id for a in v2_activities}
        assert len(v2_activities) == 3
        assert v1_act_ids.isdisjoint(v2_act_ids)


async def test_project_latest_version_id_updates_only_after_ready(
    client: AsyncClient,
    app_and_factory: tuple[FastAPI, async_sessionmaker[AsyncSession], Settings],
) -> None:
    _, factory, settings = app_and_factory
    token = make_token("auth0|pointer-user", email="pointer@epc.test")

    proj_res = await client.post(
        "/api/v1/projects",
        headers=bearer(token),
        json={"name": "Pipeline Project Alpha"},
    )
    project_id = proj_res.json()["id"]
    proj_uuid = uuid.UUID(project_id)

    # 1. Before any import confirm, project.latest_version_id is None
    async with factory() as s:
        p_initial = await s.get(Project, proj_uuid)
        assert p_initial is not None
        assert p_initial.latest_version_id is None

    # 2. Upload file, job created but NOT confirmed -> latest_version_id must still be None
    xer_v1_bytes = (FIXTURES_DIR / "p6_release_82_facility.xer").read_bytes()
    job_1_id = await _upload_and_process_file(
        client, factory, settings, token, project_id, "fac.xer", xer_v1_bytes
    )

    async with factory() as s:
        p_pre_confirm = await s.get(Project, proj_uuid)
        assert p_pre_confirm is not None
        assert p_pre_confirm.latest_version_id is None

    # 3. Confirm job 1 -> latest_version_id updates to V1 ID
    c1 = (await client.post(f"/api/v1/imports/{job_1_id}/confirm", headers=bearer(token))).json()
    v1_uuid = uuid.UUID(c1["project_version_id"])

    async with factory() as s:
        p_v1 = await s.get(Project, proj_uuid)
        assert p_v1 is not None
        assert p_v1.latest_version_id == v1_uuid

    # 4. Confirm job 2 -> latest_version_id updates to V2 ID
    xer_v2_bytes = (FIXTURES_DIR / "p6_release_20_pipeline.xer").read_bytes()
    job_2_id = await _upload_and_process_file(
        client, factory, settings, token, project_id, "pipe.xer", xer_v2_bytes
    )
    c2 = (await client.post(f"/api/v1/imports/{job_2_id}/confirm", headers=bearer(token))).json()
    v2_uuid = uuid.UUID(c2["project_version_id"])

    async with factory() as s:
        p_v2 = await s.get(Project, proj_uuid)
        assert p_v2 is not None
        assert p_v2.latest_version_id == v2_uuid


async def test_version_list_and_detail_endpoints(
    client: AsyncClient,
    app_and_factory: tuple[FastAPI, async_sessionmaker[AsyncSession], Settings],
) -> None:
    _, factory, settings = app_and_factory
    token = make_token("auth0|history-user", email="hist@epc.test")

    proj_res = await client.post(
        "/api/v1/projects",
        headers=bearer(token),
        json={"name": "History Verification Project"},
    )
    project_id = proj_res.json()["id"]

    # Upload & confirm V1
    xer_v1_bytes = (FIXTURES_DIR / "p6_release_82_facility.xer").read_bytes()
    job_1_id = await _upload_and_process_file(
        client, factory, settings, token, project_id, "facility_snapshot_1.xer", xer_v1_bytes
    )
    c1 = (await client.post(f"/api/v1/imports/{job_1_id}/confirm", headers=bearer(token))).json()
    v1_id = c1["project_version_id"]

    # Upload & confirm V2
    xer_v2_bytes = (FIXTURES_DIR / "p6_release_20_pipeline.xer").read_bytes()
    job_2_id = await _upload_and_process_file(
        client, factory, settings, token, project_id, "pipeline_snapshot_2.xer", xer_v2_bytes
    )
    c2 = (await client.post(f"/api/v1/imports/{job_2_id}/confirm", headers=bearer(token))).json()
    v2_id = c2["project_version_id"]
    assert v2_id != v1_id

    # 1. Query version list: GET /api/v1/projects/{project_id}/versions
    list_res = await client.get(f"/api/v1/projects/{project_id}/versions", headers=bearer(token))
    assert list_res.status_code == 200
    versions = list_res.json()
    assert len(versions) == 2

    # Descending order by version_number: V2 is first, V1 is second
    assert versions[0]["version_number"] == 2
    assert versions[0]["version_label"] == "V2"
    assert versions[0]["source_filename"] == "pipeline_snapshot_2.xer"
    assert versions[0]["parser_version"] is not None
    assert versions[0]["status"] == "ready"
    assert versions[0]["activity_count"] == 3
    assert versions[0]["data_date"] is not None

    assert versions[1]["version_number"] == 1
    assert versions[1]["version_label"] == "V1"
    assert versions[1]["source_filename"] == "facility_snapshot_1.xer"
    assert versions[1]["activity_count"] == 5

    # 2. Query version detail: GET /api/v1/projects/{project_id}/versions/{version_id}
    detail_res = await client.get(
        f"/api/v1/projects/{project_id}/versions/{v1_id}",
        headers=bearer(token),
    )
    assert detail_res.status_code == 200
    detail = detail_res.json()
    assert detail["id"] == v1_id
    assert detail["version_number"] == 1
    assert detail["source_filename"] == "facility_snapshot_1.xer"
    assert detail["status"] == "ready"
    assert detail["quality_summary"]["activities_count"] == 5
    assert detail["quality_summary"]["relationships_count"] == 5
    assert detail["quality_summary"]["wbs_nodes_count"] == 4
    assert detail["quality_summary"]["calendars_count"] == 2
    assert "warnings_count" in detail["quality_summary"]

    # Non-existent version returns 404
    missing_id = str(uuid.uuid4())
    missing_res = await client.get(
        f"/api/v1/projects/{project_id}/versions/{missing_id}",
        headers=bearer(token),
    )
    assert missing_res.status_code == 404
    assert missing_res.json()["error"]["code"] == "NOT_FOUND"


async def test_tenant_isolation_on_versions(
    client: AsyncClient,
    app_and_factory: tuple[FastAPI, async_sessionmaker[AsyncSession], Settings],
) -> None:
    _, factory, settings = app_and_factory
    user_a = make_token("auth0|tenant-a-vers", email="a-vers@epc.test")
    user_b = make_token("auth0|tenant-b-vers", email="b-vers@epc.test")

    # Tenant A creates project & version
    proj_a = (
        await client.post(
            "/api/v1/projects",
            headers=bearer(user_a),
            json={"name": "Tenant A Secret Facility"},
        )
    ).json()

    xer_bytes = (FIXTURES_DIR / "p6_release_82_facility.xer").read_bytes()
    job_a_id = await _upload_and_process_file(
        client, factory, settings, user_a, proj_a["id"], "secret.xer", xer_bytes
    )
    c1 = (await client.post(f"/api/v1/imports/{job_a_id}/confirm", headers=bearer(user_a))).json()
    v_a_id = c1["project_version_id"]

    # Tenant B tries to list Tenant A's project versions -> 404
    cross_list = await client.get(
        f"/api/v1/projects/{proj_a['id']}/versions",
        headers=bearer(user_b),
    )
    assert cross_list.status_code == 404
    assert cross_list.json()["error"]["code"] == "NOT_FOUND"

    # Tenant B tries to view Tenant A's project version detail -> 404
    cross_detail = await client.get(
        f"/api/v1/projects/{proj_a['id']}/versions/{v_a_id}",
        headers=bearer(user_b),
    )
    assert cross_detail.status_code == 404
    assert cross_detail.json()["error"]["code"] == "NOT_FOUND"
