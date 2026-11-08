"""Unit tests for activity and WBS explorer domain service (PI-031).

Acceptance criteria:
- Search, filter, and pagination are executed server-side.
- Activity detail shows source identifier and provenance.
- Predecessor and successor links resolve strictly within the same version.
- WBS tree aggregates activity counts per node.
"""

import uuid
from collections.abc import AsyncGenerator
from datetime import date

import pytest
from app.domains.schedule.explorer import (
    get_activity_detail,
    get_activity_relationships,
    get_wbs_tree,
    list_activities,
)
from app.models.auth import User, Workspace
from app.models.base import Base
from app.models.project import ImportJob, Project, ProjectVersion, UploadedFile
from app.models.schedule import (
    Activity,
    ActivityRelationship,
    BaselineActivityValue,
    Calendar,
    WBSNode,
)
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine(
        "sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )

    @event.listens_for(engine.sync_engine, "connect")
    def _fk_on(dbapi_conn, _record) -> None:  # type: ignore[no-untyped-def]
        dbapi_conn.execute("PRAGMA foreign_keys = ON")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


async def _seed_test_schedule(
    session: AsyncSession,
) -> tuple[Project, ProjectVersion, list[Activity], list[WBSNode]]:
    user = User(
        id=uuid.uuid4(),
        auth_subject="auth0|exp-user",
        email="explorer@epc.test",
    )
    session.add(user)
    await session.flush()

    ws = Workspace(id=uuid.uuid4(), name="Explorer WS", owner_user_id=user.id)
    session.add(ws)
    await session.flush()

    project = Project(
        id=uuid.uuid4(),
        workspace_id=ws.id,
        name="Gas Turbine Power Plant",
    )
    session.add(project)
    await session.flush()

    uploaded_file = UploadedFile(
        id=uuid.uuid4(),
        workspace_id=ws.id,
        project_id=project.id,
        original_filename="gt_plant.xer",
        object_key="uploads/gt_plant.xer",
        source_format="xer",
        file_size_bytes=2048,
        sha256_checksum="hash123",
    )
    session.add(uploaded_file)
    await session.flush()

    job = ImportJob(
        id=uuid.uuid4(),
        workspace_id=ws.id,
        project_id=project.id,
        uploaded_file_id=uploaded_file.id,
        status="confirmed",
    )
    session.add(job)
    await session.flush()

    version = ProjectVersion(
        id=uuid.uuid4(),
        workspace_id=ws.id,
        project_id=project.id,
        import_job_id=job.id,
        version_number=1,
        version_label="V1",
        source_format="xer",
        data_date=date(2026, 11, 1),
        status="ready",
    )
    session.add(version)
    await session.flush()
    project.latest_version_id = version.id
    await session.flush()

    # WBS Nodes (Root and 2 children)
    wbs_root = WBSNode(
        id=uuid.uuid4(),
        workspace_id=ws.id,
        project_id=project.id,
        project_version_id=version.id,
        source_wbs_id="W-ROOT",
        wbs_code="GTPP",
        wbs_name="Power Plant",
    )
    wbs_eng = WBSNode(
        id=uuid.uuid4(),
        workspace_id=ws.id,
        project_id=project.id,
        project_version_id=version.id,
        source_wbs_id="W-ENG",
        wbs_code="GTPP.ENG",
        wbs_name="Engineering",
        parent_wbs_node_id=wbs_root.id,
    )
    wbs_proc = WBSNode(
        id=uuid.uuid4(),
        workspace_id=ws.id,
        project_id=project.id,
        project_version_id=version.id,
        source_wbs_id="W-PROC",
        wbs_code="GTPP.PROC",
        wbs_name="Procurement",
        parent_wbs_node_id=wbs_root.id,
    )
    session.add_all([wbs_root, wbs_eng, wbs_proc])
    await session.flush()

    # Calendar
    cal = Calendar(
        id=uuid.uuid4(),
        workspace_id=ws.id,
        project_id=project.id,
        project_version_id=version.id,
        source_calendar_id="C-1",
        calendar_name="Standard 5D",
    )
    session.add(cal)
    await session.flush()

    # Activities: 4 activities
    a1 = Activity(
        id=uuid.uuid4(),
        workspace_id=ws.id,
        project_id=project.id,
        project_version_id=version.id,
        source_activity_id="SRC-101",
        activity_code="ACT-ENG-01",
        activity_name="Turbine Civil Design",
        wbs_node_id=wbs_eng.id,
        calendar_id=cal.id,
        status="complete",
        start_date=date(2026, 1, 10),
        finish_date=date(2026, 2, 20),
        total_float_hours=0.0,
        physical_pct_complete=100.0,
        source_fields={"raw_status": "TK_Done", "p6_id": 101},
    )
    a2 = Activity(
        id=uuid.uuid4(),
        workspace_id=ws.id,
        project_id=project.id,
        project_version_id=version.id,
        source_activity_id="SRC-102",
        activity_code="ACT-ENG-02",
        activity_name="Electrical Single Line Diagram",
        wbs_node_id=wbs_eng.id,
        calendar_id=cal.id,
        status="in_progress",
        start_date=date(2026, 2, 21),
        finish_date=date(2026, 4, 30),
        total_float_hours=-24.0,  # Negative float!
        physical_pct_complete=45.0,
        source_fields={"raw_status": "TK_Active", "p6_id": 102},
    )
    a3 = Activity(
        id=uuid.uuid4(),
        workspace_id=ws.id,
        project_id=project.id,
        project_version_id=version.id,
        source_activity_id="SRC-201",
        activity_code="ACT-PROC-01",
        activity_name="Generator Procurement",
        wbs_node_id=wbs_proc.id,
        calendar_id=cal.id,
        status="not_started",
        start_date=date(2026, 5, 1),
        finish_date=date(2026, 9, 30),
        total_float_hours=120.0,
        physical_pct_complete=0.0,
        source_fields={"raw_status": "TK_NotStart", "p6_id": 201},
    )
    a4 = Activity(
        id=uuid.uuid4(),
        workspace_id=ws.id,
        project_id=project.id,
        project_version_id=version.id,
        source_activity_id="SRC-202",
        activity_code="ACT-PROC-02",
        activity_name="Transformer Logistics",
        wbs_node_id=wbs_proc.id,
        calendar_id=cal.id,
        status="not_started",
        start_date=date(2026, 7, 1),
        finish_date=date(2026, 11, 15),
        total_float_hours=80.0,
        physical_pct_complete=None,
        source_fields={"raw_status": "TK_NotStart", "p6_id": 202},
    )
    session.add_all([a1, a2, a3, a4])
    await session.flush()

    # Baseline for a1
    base_val = BaselineActivityValue(
        id=uuid.uuid4(),
        workspace_id=ws.id,
        project_id=project.id,
        project_version_id=version.id,
        baseline_source_id="B1",
        source_activity_id="SRC-101",
        baseline_start=date(2026, 1, 5),
        baseline_finish=date(2026, 2, 15),
        baseline_duration_hours=240.0,
        baseline_pct_complete=100.0,
        baseline_label="Initial Contract Baseline",
    )
    session.add(base_val)

    # Relationship: a1 -> a2 (FS, lag 0)
    rel1 = ActivityRelationship(
        id=uuid.uuid4(),
        workspace_id=ws.id,
        project_id=project.id,
        project_version_id=version.id,
        predecessor_activity_id=a1.id,
        successor_activity_id=a2.id,
        relationship_type="FS",
        lag_hours=0.0,
    )
    # Relationship: a2 -> a3 (SS, lag 40)
    rel2 = ActivityRelationship(
        id=uuid.uuid4(),
        workspace_id=ws.id,
        project_id=project.id,
        project_version_id=version.id,
        predecessor_activity_id=a2.id,
        successor_activity_id=a3.id,
        relationship_type="SS",
        lag_hours=40.0,
    )
    session.add_all([rel1, rel2])
    await session.commit()

    return project, version, [a1, a2, a3, a4], [wbs_root, wbs_eng, wbs_proc]


# --- Tests ---


async def test_list_activities_search_and_filter(session: AsyncSession) -> None:
    project, version, acts, wbss = await _seed_test_schedule(session)

    # 1. Unfiltered query
    all_res = await list_activities(session, project_id=project.id, version_id=version.id)
    assert all_res.total == 4
    assert len(all_res.items) == 4

    # 2. Text search (q) matching code or name
    q_res = await list_activities(
        session, project_id=project.id, version_id=version.id, q="Generator"
    )
    assert q_res.total == 1
    assert q_res.items[0].activity_code == "ACT-PROC-01"

    code_res = await list_activities(session, project_id=project.id, version_id=version.id, q="ENG")
    assert code_res.total == 2
    assert {i.activity_code for i in code_res.items} == {"ACT-ENG-01", "ACT-ENG-02"}

    # 3. Status filter
    stat_res = await list_activities(
        session, project_id=project.id, version_id=version.id, status="complete"
    )
    assert stat_res.total == 1
    assert stat_res.items[0].activity_code == "ACT-ENG-01"

    # 4. WBS filter
    wbs_res = await list_activities(
        session, project_id=project.id, version_id=version.id, wbs_id=wbss[2].id
    )
    assert wbs_res.total == 2
    assert {i.activity_code for i in wbs_res.items} == {"ACT-PROC-01", "ACT-PROC-02"}

    # 5. Float filter (critical / low float <= 0.0)
    float_res = await list_activities(
        session, project_id=project.id, version_id=version.id, float_max=0.0
    )
    assert float_res.total == 2
    assert {i.activity_code for i in float_res.items} == {"ACT-ENG-01", "ACT-ENG-02"}


async def test_list_activities_pagination(session: AsyncSession) -> None:
    project, version, _, _ = await _seed_test_schedule(session)

    # Page 1: limit 2, offset 0
    page1 = await list_activities(
        session, project_id=project.id, version_id=version.id, limit=2, offset=0
    )
    assert page1.total == 4
    assert len(page1.items) == 2
    assert page1.limit == 2
    assert page1.offset == 0
    first_codes = [i.activity_code for i in page1.items]

    # Page 2: limit 2, offset 2
    page2 = await list_activities(
        session, project_id=project.id, version_id=version.id, limit=2, offset=2
    )
    assert page2.total == 4
    assert len(page2.items) == 2
    assert page2.offset == 2
    second_codes = [i.activity_code for i in page2.items]

    # Pages must be disjoint
    assert set(first_codes).isdisjoint(set(second_codes))


async def test_get_activity_detail_provenance_and_baselines(session: AsyncSession) -> None:
    project, version, acts, _ = await _seed_test_schedule(session)
    target_act = acts[0]

    detail = await get_activity_detail(
        session, project_id=project.id, activity_id=target_act.id, version_id=version.id
    )
    assert detail is not None
    assert detail.id == target_act.id
    assert detail.source_activity_id == "SRC-101"
    assert detail.activity_code == "ACT-ENG-01"
    assert detail.wbs_name == "Engineering"
    assert detail.calendar_name == "Standard 5D"

    # Provenance fields preserved
    assert detail.source_fields["raw_status"] == "TK_Done"
    assert detail.source_fields["p6_id"] == 101

    # Baselines retrieved
    assert len(detail.baselines) == 1
    assert detail.baselines[0]["baseline_label"] == "Initial Contract Baseline"
    assert detail.baselines[0]["baseline_duration_hours"] == 240.0


async def test_get_activity_relationships_within_same_version(session: AsyncSession) -> None:
    project, version, acts, _ = await _seed_test_schedule(session)
    # a2 has predecessor a1 and successor a3
    a2 = acts[1]

    rels = await get_activity_relationships(
        session, project_id=project.id, activity_id=a2.id, version_id=version.id
    )
    assert rels is not None
    assert rels.activity_id == a2.id

    # Predecessor: a1
    assert len(rels.predecessors) == 1
    assert rels.predecessors[0].activity_code == "ACT-ENG-01"
    assert rels.predecessors[0].relationship_type == "FS"
    assert rels.predecessors[0].lag_hours == 0.0

    # Successor: a3
    assert len(rels.successors) == 1
    assert rels.successors[0].activity_code == "ACT-PROC-01"
    assert rels.successors[0].relationship_type == "SS"
    assert rels.successors[0].lag_hours == 40.0


async def test_get_wbs_tree_with_activity_counts(session: AsyncSession) -> None:
    project, version, _, wbss = await _seed_test_schedule(session)

    nodes = await get_wbs_tree(session, project_id=project.id, version_id=version.id)
    assert len(nodes) == 3

    node_map = {n.wbs_code: n for n in nodes}
    assert node_map["GTPP"].activity_count == 0  # root has 0 direct activities
    assert node_map["GTPP.ENG"].activity_count == 2
    assert node_map["GTPP.PROC"].activity_count == 2
