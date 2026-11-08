"""Unit tests for version comparison domain service (PI-034).

Acceptance criteria:
- Matching rule: Stable P6 source ID first, activity code second.
  Never match solely on activity name.
- Ambiguous matches (duplicate codes in either version) must be isolated into 'ambiguous' category.
- Exact count reconciliation:
  from_version_total == matched + removed + ambiguous_from
  to_version_total == matched + added + ambiguous_to
  matched == changed + unchanged
- Diffs identify added, removed, changed, unchanged, ambiguous activities.
- Field changes compute appropriate deltas (days for dates, numeric deltas for floats).
- Relationship changes (added, removed, modified) are tracked.
- CSV export generates valid CSV with correct headers and flattened rows.
- Domain isolation: zero dependencies on FastAPI, HTTP, AI, or Ingestion.
"""

import csv
import io
import uuid
from collections.abc import AsyncGenerator
from datetime import date

import pytest
from app.domains.schedule.comparison import (
    compare_versions,
    export_comparison_csv,
)
from app.domains.schedule.schemas import VersionComparisonReport
from app.models.auth import User, Workspace
from app.models.base import Base
from app.models.project import ImportJob, Project, ProjectVersion, UploadedFile
from app.models.schedule import Activity, ActivityRelationship
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


async def _seed_comparison_versions(
    session: AsyncSession,
) -> tuple[Project, ProjectVersion, ProjectVersion]:
    user = User(
        id=uuid.uuid4(),
        auth_subject="auth0|compare-user",
        email="compare.user@epc-intel.test",
        display_name="Compare Engineer",
    )
    workspace = Workspace(
        id=uuid.uuid4(),
        name="Compare Workspace",
        owner_user_id=user.id,
    )
    session.add_all([user, workspace])
    await session.flush()

    project = Project(
        id=uuid.uuid4(),
        workspace_id=workspace.id,
        name="Comparison Project",
        project_code="CMP-001",
    )
    session.add(project)
    await session.flush()

    file_a = UploadedFile(
        id=uuid.uuid4(),
        workspace_id=workspace.id,
        project_id=project.id,
        original_filename="rev1.xer",
        object_key="uploads/rev1.xer",
        source_format="xer",
        sha256_checksum="hash_rev1",
        file_size_bytes=1000,
    )
    file_b = UploadedFile(
        id=uuid.uuid4(),
        workspace_id=workspace.id,
        project_id=project.id,
        original_filename="rev2.xer",
        object_key="uploads/rev2.xer",
        source_format="xer",
        sha256_checksum="hash_rev2",
        file_size_bytes=1000,
    )
    session.add_all([file_a, file_b])
    await session.flush()

    job_a = ImportJob(
        id=uuid.uuid4(),
        workspace_id=workspace.id,
        project_id=project.id,
        uploaded_file_id=file_a.id,
        status="confirmed",
    )
    job_b = ImportJob(
        id=uuid.uuid4(),
        workspace_id=workspace.id,
        project_id=project.id,
        uploaded_file_id=file_b.id,
        status="confirmed",
    )
    session.add_all([job_a, job_b])
    await session.flush()

    version_a = ProjectVersion(
        id=uuid.uuid4(),
        workspace_id=workspace.id,
        project_id=project.id,
        import_job_id=job_a.id,
        version_number=1,
        source_format="xer",
        data_date=date(2026, 1, 1),
    )
    version_b = ProjectVersion(
        id=uuid.uuid4(),
        workspace_id=workspace.id,
        project_id=project.id,
        import_job_id=job_b.id,
        version_number=2,
        source_format="xer",
        data_date=date(2026, 2, 1),
    )
    session.add_all([version_a, version_b])
    await session.commit()
    return project, version_a, version_b


@pytest.mark.asyncio
async def test_compare_versions_matching_and_reconciliation(session: AsyncSession) -> None:
    """Test 2-stage matching (source ID -> activity code) and exact reconciliation counts."""
    project, v_a, v_b = await _seed_comparison_versions(session)

    # Version A:
    # 1. Matched by source_id: A100 (source: SRC-100) -> unchanged
    act_a1 = Activity(
        id=uuid.uuid4(),
        workspace_id=project.workspace_id,
        project_id=project.id,
        project_version_id=v_a.id,
        source_activity_id="SRC-100",
        activity_code="A100",
        activity_name="Site Prep",
        status="not_started",
        planned_start=date(2026, 1, 10),
        planned_finish=date(2026, 1, 20),
        total_float_hours=16.0,
    )
    # 2. Matched by source_id: A200 (source: SRC-200) -> changed (date & float & status changed)
    act_a2 = Activity(
        id=uuid.uuid4(),
        workspace_id=project.workspace_id,
        project_id=project.id,
        project_version_id=v_a.id,
        source_activity_id="SRC-200",
        activity_code="A200",
        activity_name="Foundation",
        status="not_started",
        planned_start=date(2026, 1, 21),
        planned_finish=date(2026, 2, 10),
        total_float_hours=8.0,
        physical_pct_complete=0.0,
    )
    # 3. Matched by code fallback: A300 (source: SRC-300 in A, SRC-999 in B) -> changed name
    act_a3 = Activity(
        id=uuid.uuid4(),
        workspace_id=project.workspace_id,
        project_id=project.id,
        project_version_id=v_a.id,
        source_activity_id="SRC-300",
        activity_code="A300",
        activity_name="Old Structural Steel",
        status="in_progress",
    )
    # 4. Removed activity in A only: A400
    act_a4 = Activity(
        id=uuid.uuid4(),
        workspace_id=project.workspace_id,
        project_id=project.id,
        project_version_id=v_a.id,
        source_activity_id="SRC-400",
        activity_code="A400",
        activity_name="Cancelled Activity",
        status="not_started",
    )
    # 5. Ambiguous in A: Duplicate code DUP-1 (two activities with same code in A)
    act_a5a = Activity(
        id=uuid.uuid4(),
        workspace_id=project.workspace_id,
        project_id=project.id,
        project_version_id=v_a.id,
        source_activity_id="SRC-D1A",
        activity_code="DUP-1",
        activity_name="Duplicate Code 1A",
        status="not_started",
    )
    act_a5b = Activity(
        id=uuid.uuid4(),
        workspace_id=project.workspace_id,
        project_id=project.id,
        project_version_id=v_a.id,
        source_activity_id="SRC-D1B",
        activity_code="DUP-1",
        activity_name="Duplicate Code 1B",
        status="not_started",
    )

    # Version B:
    # 1. Matching A100 by source_id -> identical values
    act_b1 = Activity(
        id=uuid.uuid4(),
        workspace_id=project.workspace_id,
        project_id=project.id,
        project_version_id=v_b.id,
        source_activity_id="SRC-100",
        activity_code="A100",
        activity_name="Site Prep",
        status="not_started",
        planned_start=date(2026, 1, 10),
        planned_finish=date(2026, 1, 20),
        total_float_hours=16.0,
    )
    # 2. Matching A200 by source_id -> changed
    act_b2 = Activity(
        id=uuid.uuid4(),
        workspace_id=project.workspace_id,
        project_id=project.id,
        project_version_id=v_b.id,
        source_activity_id="SRC-200",
        activity_code="A200",
        activity_name="Foundation",
        status="in_progress",
        planned_start=date(2026, 1, 25),  # slipped 4 days
        planned_finish=date(2026, 2, 15),  # slipped 5 days
        total_float_hours=0.0,  # float reduced by 8h
        physical_pct_complete=30.0,
    )
    # 3. Matching A300 by code fallback -> source_id is different (SRC-999)
    act_b3 = Activity(
        id=uuid.uuid4(),
        workspace_id=project.workspace_id,
        project_id=project.id,
        project_version_id=v_b.id,
        source_activity_id="SRC-999",
        activity_code="A300",
        activity_name="New Structural Steel",
        status="in_progress",
    )
    # 4. Added activity in B only: A500
    act_b4 = Activity(
        id=uuid.uuid4(),
        workspace_id=project.workspace_id,
        project_id=project.id,
        project_version_id=v_b.id,
        source_activity_id="SRC-500",
        activity_code="A500",
        activity_name="Added Piping Works",
        status="not_started",
    )
    # 5. Activity with DUP-1 in B (cannot reliably match because A had duplicates)
    act_b5 = Activity(
        id=uuid.uuid4(),
        workspace_id=project.workspace_id,
        project_id=project.id,
        project_version_id=v_b.id,
        source_activity_id="SRC-D1-NEW",
        activity_code="DUP-1",
        activity_name="Duplicate Target in B",
        status="not_started",
    )

    session.add_all(
        [
            act_a1,
            act_a2,
            act_a3,
            act_a4,
            act_a5a,
            act_a5b,
            act_b1,
            act_b2,
            act_b3,
            act_b4,
            act_b5,
        ]
    )
    await session.commit()

    report = await compare_versions(
        session=session,
        project_id=project.id,
        from_version_id=v_a.id,
        to_version_id=v_b.id,
    )

    # Reconciliation check:
    # Version A has 6 activities: A100, A200, A300, A400, DUP-1 (2x)
    # Version B has 5 activities: A100, A200, A300, A500, DUP-1 (1x)
    assert report.summary.from_version_total == 6
    assert report.summary.to_version_total == 5

    # Matched = 3 (A100 unchanged, A200 changed, A300 changed)
    assert report.summary.matched == 3
    assert report.summary.unchanged == 1  # A100
    assert report.summary.changed == 2  # A200, A300

    # Added = 1 (A500)
    assert report.summary.added == 1

    # Removed = 1 (A400)
    assert report.summary.removed == 1

    # Ambiguous = 3 (2 from A, 1 from B)
    assert report.summary.ambiguous == 3

    # Exact reconciliation invariant:
    # from_total == matched + removed + ambiguous_from (3 + 1 + 2 = 6)
    # to_total == matched + added + ambiguous_to (3 + 1 + 1 = 5)
    assert report.summary.from_version_total == report.summary.matched + report.summary.removed + 2
    assert report.summary.to_version_total == report.summary.matched + report.summary.added + 1

    # Detailed item checks
    item_a200 = next(i for i in report.items if i.activity_code == "A200")
    assert item_a200.diff_category == "changed"
    assert item_a200.match_key == "source_id:SRC-200"

    # Verify field diffs on A200
    status_diff = next(d for d in item_a200.field_changes if d.field_name == "status")
    assert status_diff.old_value == "not_started"
    assert status_diff.new_value == "in_progress"

    date_diff = next(d for d in item_a200.field_changes if d.field_name == "planned_start")
    assert str(date_diff.old_value) == "2026-01-21"
    assert str(date_diff.new_value) == "2026-01-25"
    assert date_diff.delta == 4  # +4 days

    float_diff = next(d for d in item_a200.field_changes if d.field_name == "total_float_hours")
    assert float_diff.old_value == 8.0
    assert float_diff.new_value == 0.0
    assert float_diff.delta == -8.0

    # Verify A300 matched by activity_code
    item_a300 = next(i for i in report.items if i.activity_code == "A300")
    assert item_a300.diff_category == "changed"
    assert item_a300.match_key == "activity_code:A300"
    name_diff = next(d for d in item_a300.field_changes if d.field_name == "activity_name")
    assert name_diff.old_value == "Old Structural Steel"
    assert name_diff.new_value == "New Structural Steel"


@pytest.mark.asyncio
async def test_compare_versions_relationship_diffs(session: AsyncSession) -> None:
    """Test tracking added, removed, and modified logic links between versions."""
    project, v_a, v_b = await _seed_comparison_versions(session)

    # Activities present in both versions
    act_a1 = Activity(
        id=uuid.uuid4(),
        workspace_id=project.workspace_id,
        project_id=project.id,
        project_version_id=v_a.id,
        source_activity_id="ACT-1",
        activity_code="ACT-1",
        activity_name="Civil Works",
    )
    act_a2 = Activity(
        id=uuid.uuid4(),
        workspace_id=project.workspace_id,
        project_id=project.id,
        project_version_id=v_a.id,
        source_activity_id="ACT-2",
        activity_code="ACT-2",
        activity_name="Mechanical Works",
    )
    act_a3 = Activity(
        id=uuid.uuid4(),
        workspace_id=project.workspace_id,
        project_id=project.id,
        project_version_id=v_a.id,
        source_activity_id="ACT-3",
        activity_code="ACT-3",
        activity_name="Electrical Works",
    )

    act_b1 = Activity(
        id=uuid.uuid4(),
        workspace_id=project.workspace_id,
        project_id=project.id,
        project_version_id=v_b.id,
        source_activity_id="ACT-1",
        activity_code="ACT-1",
        activity_name="Civil Works",
    )
    act_b2 = Activity(
        id=uuid.uuid4(),
        workspace_id=project.workspace_id,
        project_id=project.id,
        project_version_id=v_b.id,
        source_activity_id="ACT-2",
        activity_code="ACT-2",
        activity_name="Mechanical Works",
    )
    act_b3 = Activity(
        id=uuid.uuid4(),
        workspace_id=project.workspace_id,
        project_id=project.id,
        project_version_id=v_b.id,
        source_activity_id="ACT-3",
        activity_code="ACT-3",
        activity_name="Electrical Works",
    )

    session.add_all([act_a1, act_a2, act_a3, act_b1, act_b2, act_b3])
    await session.commit()

    # In version A:
    # 1. ACT-1 -> ACT-2 (FS, lag 0)
    # 2. ACT-1 -> ACT-3 (SS, lag 10)  (will be removed in B)
    rel_a1 = ActivityRelationship(
        workspace_id=project.workspace_id,
        project_id=project.id,
        project_version_id=v_a.id,
        predecessor_activity_id=act_a1.id,
        successor_activity_id=act_a2.id,
        relationship_type="FS",
        lag_hours=0.0,
    )
    rel_a2 = ActivityRelationship(
        workspace_id=project.workspace_id,
        project_id=project.id,
        project_version_id=v_a.id,
        predecessor_activity_id=act_a1.id,
        successor_activity_id=act_a3.id,
        relationship_type="SS",
        lag_hours=10.0,
    )

    # In version B:
    # 1. ACT-1 -> ACT-2 (FS, lag 24) (lag modified from 0 to 24)
    # 2. ACT-2 -> ACT-3 (FS, lag 0)  (newly added relationship)
    rel_b1 = ActivityRelationship(
        workspace_id=project.workspace_id,
        project_id=project.id,
        project_version_id=v_b.id,
        predecessor_activity_id=act_b1.id,
        successor_activity_id=act_b2.id,
        relationship_type="FS",
        lag_hours=24.0,
    )
    rel_b2 = ActivityRelationship(
        workspace_id=project.workspace_id,
        project_id=project.id,
        project_version_id=v_b.id,
        predecessor_activity_id=act_b2.id,
        successor_activity_id=act_b3.id,
        relationship_type="FS",
        lag_hours=0.0,
    )

    session.add_all([rel_a1, rel_a2, rel_b1, rel_b2])
    await session.commit()

    report = await compare_versions(
        session=session,
        project_id=project.id,
        from_version_id=v_a.id,
        to_version_id=v_b.id,
    )

    assert report.summary.matched == 3
    # ACT-1 has modified link to ACT-2 and removed link to ACT-3
    act1_item = next(i for i in report.items if i.activity_code == "ACT-1")
    assert act1_item.diff_category == "changed"
    assert len(act1_item.relationship_changes) >= 1

    # ACT-2 has modified predecessor ACT-1 and added successor ACT-3
    act2_item = next(i for i in report.items if i.activity_code == "ACT-2")
    assert act2_item.diff_category == "changed"

    # ACT-3 has removed predecessor ACT-1 and added predecessor ACT-2
    act3_item = next(i for i in report.items if i.activity_code == "ACT-3")
    assert act3_item.diff_category == "changed"


def test_export_comparison_csv() -> None:
    """Test generating CSV export from VersionComparisonReport."""
    report = VersionComparisonReport(
        project_id=uuid.uuid4(),
        from_version_id=uuid.uuid4(),
        to_version_id=uuid.uuid4(),
        from_version_number=1,
        to_version_number=2,
        from_data_date=date(2026, 1, 1),
        to_data_date=date(2026, 2, 1),
        summary={
            "from_version_total": 2,
            "to_version_total": 2,
            "matched": 2,
            "added": 0,
            "removed": 0,
            "changed": 1,
            "unchanged": 1,
            "ambiguous": 0,
            "change_categories": {"changed": 1, "unchanged": 1},
        },
        items=[
            {
                "diff_category": "changed",
                "activity_code": "A100",
                "activity_name": "Site Works",
                "match_key": "source_id:SRC-100",
                "field_changes": [
                    {
                        "field_name": "planned_start",
                        "old_value": "2026-01-10",
                        "new_value": "2026-01-15",
                        "delta": 5,
                    }
                ],
                "relationship_changes": [],
            },
            {
                "diff_category": "unchanged",
                "activity_code": "A200",
                "activity_name": "Piping",
                "match_key": "source_id:SRC-200",
                "field_changes": [],
                "relationship_changes": [],
            },
        ],
        total_items=2,
    )

    csv_data = export_comparison_csv(report)
    reader = csv.reader(io.StringIO(csv_data))
    rows = list(reader)

    assert len(rows) >= 3  # Header + 2 data rows
    header = rows[0]
    assert "diff_category" in header
    assert "activity_code" in header
    assert "field_name" in header
    assert "delta" in header

    a100_row = next(r for r in rows if len(r) > 1 and r[1] == "A100")
    assert a100_row[0] == "changed"
