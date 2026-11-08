"""Deterministic activity and WBS explorer domain service (PI-031).

Rules (02_SYSTEM_ARCHITECTURE.md, 08_DEVELOPMENT_BACKLOG.md PI-031):
- Search, filter, and pagination executed server-side.
- Activity detail shows source identifier and provenance.
- Predecessor and successor links resolve strictly within the same version.
- Strict domain isolation: no web/API framework imports.
"""

import uuid
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.schedule.schemas import (
    ActivityDetail,
    ActivityListItem,
    ActivityListResponse,
    ActivityRelationshipsResponse,
    RelationshipItem,
    WBSNodeItem,
)
from app.models.project import Project, ProjectVersion
from app.models.schedule import (
    Activity,
    ActivityRelationship,
    BaselineActivityValue,
    Calendar,
    WBSNode,
)


async def _resolve_version_id(
    session: AsyncSession,
    project_id: uuid.UUID,
    version_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """Resolve and validate active version_id for project."""
    if version_id is not None:
        pv = await session.execute(
            select(ProjectVersion.id).where(
                ProjectVersion.project_id == project_id,
                ProjectVersion.id == version_id,
            )
        )
        if not pv.scalar_one_or_none():
            raise ValueError(f"ProjectVersion '{version_id}' not found for project '{project_id}'.")
        return version_id

    project = await session.get(Project, project_id)
    if not project:
        raise ValueError(f"Project '{project_id}' not found.")
    if not project.latest_version_id:
        raise ValueError(f"Project '{project_id}' has no ready versions.")
    return project.latest_version_id


async def list_activities(
    session: AsyncSession,
    project_id: uuid.UUID,
    version_id: uuid.UUID | None = None,
    q: str | None = None,
    status: str | None = None,
    wbs_id: uuid.UUID | None = None,
    float_max: float | None = None,
    limit: int = 50,
    offset: int = 0,
) -> ActivityListResponse:
    """Query activities with server-side search, filtering, and pagination."""
    target_version_id = await _resolve_version_id(session, project_id, version_id)

    # Base filters
    filters = [Activity.project_version_id == target_version_id]
    if q and q.strip():
        search_pattern = f"%{q.strip()}%"
        filters.append(
            or_(
                Activity.activity_code.ilike(search_pattern),
                Activity.activity_name.ilike(search_pattern),
                Activity.source_activity_id.ilike(search_pattern),
            )
        )
    if status and status.strip():
        filters.append(Activity.status == status.strip())
    if wbs_id is not None:
        filters.append(Activity.wbs_node_id == wbs_id)
    if float_max is not None:
        filters.append(Activity.total_float_hours <= float_max)

    # Total count query
    count_query = select(func.count(Activity.id)).where(*filters)
    total = (await session.execute(count_query)).scalar() or 0

    # Paginated item query joined with WBSNode and Calendar
    stmt = (
        select(
            Activity,
            WBSNode.wbs_code,
            WBSNode.wbs_name,
            Calendar.calendar_name,
        )
        .outerjoin(WBSNode, WBSNode.id == Activity.wbs_node_id)
        .outerjoin(Calendar, Calendar.id == Activity.calendar_id)
        .where(*filters)
        .order_by(Activity.activity_code.asc(), Activity.id.asc())
        .limit(limit)
        .offset(offset)
    )
    rows = (await session.execute(stmt)).all()

    items: list[ActivityListItem] = []
    for act, wbs_code, wbs_name, cal_name in rows:
        items.append(
            ActivityListItem(
                id=act.id,
                source_activity_id=act.source_activity_id,
                activity_code=act.activity_code,
                activity_name=act.activity_name,
                status=act.status,
                activity_type=act.activity_type,
                wbs_node_id=act.wbs_node_id,
                wbs_code=wbs_code,
                wbs_name=wbs_name,
                calendar_id=act.calendar_id,
                calendar_name=cal_name,
                start_date=act.start_date,
                finish_date=act.finish_date,
                planned_start=act.planned_start,
                planned_finish=act.planned_finish,
                actual_start=act.actual_start,
                actual_finish=act.actual_finish,
                remaining_duration_hours=(
                    float(act.remaining_duration_hours)
                    if act.remaining_duration_hours is not None
                    else None
                ),
                total_float_hours=(
                    float(act.total_float_hours) if act.total_float_hours is not None else None
                ),
                physical_pct_complete=(
                    float(act.physical_pct_complete)
                    if act.physical_pct_complete is not None
                    else None
                ),
            )
        )

    return ActivityListResponse(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
    )


async def get_activity_detail(
    session: AsyncSession,
    project_id: uuid.UUID,
    activity_id: uuid.UUID,
    version_id: uuid.UUID | None = None,
) -> ActivityDetail | None:
    """Retrieve full activity detail including raw provenance and baseline records."""
    target_version_id = await _resolve_version_id(session, project_id, version_id)

    stmt = (
        select(
            Activity,
            WBSNode.wbs_code,
            WBSNode.wbs_name,
            Calendar.calendar_name,
        )
        .outerjoin(WBSNode, WBSNode.id == Activity.wbs_node_id)
        .outerjoin(Calendar, Calendar.id == Activity.calendar_id)
        .where(
            Activity.id == activity_id,
            Activity.project_version_id == target_version_id,
        )
    )
    row = (await session.execute(stmt)).first()
    if not row:
        return None

    act, wbs_code, wbs_name, cal_name = row

    # Fetch baseline values for this activity in this version
    base_rows = (
        (
            await session.execute(
                select(BaselineActivityValue).where(
                    BaselineActivityValue.project_version_id == target_version_id,
                    BaselineActivityValue.source_activity_id == act.source_activity_id,
                )
            )
        )
        .scalars()
        .all()
    )

    baselines_data: list[dict[str, Any]] = []
    for b in base_rows:
        baselines_data.append(
            {
                "id": str(b.id),
                "baseline_source_id": b.baseline_source_id,
                "baseline_label": b.baseline_label,
                "baseline_start": b.baseline_start.isoformat() if b.baseline_start else None,
                "baseline_finish": b.baseline_finish.isoformat() if b.baseline_finish else None,
                "baseline_duration_hours": (
                    float(b.baseline_duration_hours)
                    if b.baseline_duration_hours is not None
                    else None
                ),
                "baseline_pct_complete": (
                    float(b.baseline_pct_complete) if b.baseline_pct_complete is not None else None
                ),
                "source_fields": b.source_fields,
            }
        )

    return ActivityDetail(
        id=act.id,
        source_activity_id=act.source_activity_id,
        activity_code=act.activity_code,
        activity_name=act.activity_name,
        status=act.status,
        source_status=act.source_status,
        activity_type=act.activity_type,
        wbs_node_id=act.wbs_node_id,
        wbs_code=wbs_code,
        wbs_name=wbs_name,
        calendar_id=act.calendar_id,
        calendar_name=cal_name,
        start_date=act.start_date,
        finish_date=act.finish_date,
        planned_start=act.planned_start,
        planned_finish=act.planned_finish,
        actual_start=act.actual_start,
        actual_finish=act.actual_finish,
        remaining_duration_hours=(
            float(act.remaining_duration_hours)
            if act.remaining_duration_hours is not None
            else None
        ),
        original_duration_hours=(
            float(act.original_duration_hours) if act.original_duration_hours is not None else None
        ),
        actual_duration_hours=(
            float(act.actual_duration_hours) if act.actual_duration_hours is not None else None
        ),
        total_float_hours=(
            float(act.total_float_hours) if act.total_float_hours is not None else None
        ),
        free_float_hours=(
            float(act.free_float_hours) if act.free_float_hours is not None else None
        ),
        physical_pct_complete=(
            float(act.physical_pct_complete) if act.physical_pct_complete is not None else None
        ),
        duration_pct_complete=(
            float(act.duration_pct_complete) if act.duration_pct_complete is not None else None
        ),
        units_pct_complete=(
            float(act.units_pct_complete) if act.units_pct_complete is not None else None
        ),
        percent_complete_type=act.percent_complete_type,
        source_fields=act.source_fields,
        baselines=baselines_data,
    )


async def get_activity_relationships(
    session: AsyncSession,
    project_id: uuid.UUID,
    activity_id: uuid.UUID,
    version_id: uuid.UUID | None = None,
) -> ActivityRelationshipsResponse | None:
    """Resolve predecessor and successor links strictly within the same version."""
    target_version_id = await _resolve_version_id(session, project_id, version_id)

    # Verify activity exists in target version
    act = (
        await session.execute(
            select(Activity.id).where(
                Activity.id == activity_id,
                Activity.project_version_id == target_version_id,
            )
        )
    ).scalar_one_or_none()
    if not act:
        return None

    # Predecessors: target activity is the successor
    pred_stmt = (
        select(ActivityRelationship, Activity)
        .join(Activity, Activity.id == ActivityRelationship.predecessor_activity_id)
        .where(
            ActivityRelationship.successor_activity_id == activity_id,
            ActivityRelationship.project_version_id == target_version_id,
            Activity.project_version_id == target_version_id,
        )
        .order_by(Activity.activity_code.asc())
    )
    pred_rows = (await session.execute(pred_stmt)).all()

    predecessors: list[RelationshipItem] = []
    for rel, other_act in pred_rows:
        predecessors.append(
            RelationshipItem(
                relationship_id=rel.id,
                relationship_type=rel.relationship_type,
                lag_hours=float(rel.lag_hours),
                is_external=rel.is_external,
                activity_id=other_act.id,
                activity_code=other_act.activity_code,
                activity_name=other_act.activity_name,
                status=other_act.status,
            )
        )

    # Successors: target activity is the predecessor
    succ_stmt = (
        select(ActivityRelationship, Activity)
        .join(Activity, Activity.id == ActivityRelationship.successor_activity_id)
        .where(
            ActivityRelationship.predecessor_activity_id == activity_id,
            ActivityRelationship.project_version_id == target_version_id,
            Activity.project_version_id == target_version_id,
        )
        .order_by(Activity.activity_code.asc())
    )
    succ_rows = (await session.execute(succ_stmt)).all()

    successors: list[RelationshipItem] = []
    for rel, other_act in succ_rows:
        successors.append(
            RelationshipItem(
                relationship_id=rel.id,
                relationship_type=rel.relationship_type,
                lag_hours=float(rel.lag_hours),
                is_external=rel.is_external,
                activity_id=other_act.id,
                activity_code=other_act.activity_code,
                activity_name=other_act.activity_name,
                status=other_act.status,
            )
        )

    return ActivityRelationshipsResponse(
        activity_id=activity_id,
        predecessors=predecessors,
        successors=successors,
    )


async def get_wbs_tree(
    session: AsyncSession,
    project_id: uuid.UUID,
    version_id: uuid.UUID | None = None,
) -> list[WBSNodeItem]:
    """Retrieve WBS nodes with direct activity counts for the version."""
    target_version_id = await _resolve_version_id(session, project_id, version_id)

    # Query WBS nodes left joined with activity count
    stmt = (
        select(
            WBSNode,
            func.count(Activity.id).label("act_count"),
        )
        .outerjoin(
            Activity,
            (Activity.wbs_node_id == WBSNode.id)
            & (Activity.project_version_id == target_version_id),
        )
        .where(WBSNode.project_version_id == target_version_id)
        .group_by(WBSNode.id)
        .order_by(WBSNode.sort_order.asc().nulls_last(), WBSNode.wbs_code.asc())
    )
    rows = (await session.execute(stmt)).all()

    nodes: list[WBSNodeItem] = []
    for wbs, count in rows:
        nodes.append(
            WBSNodeItem(
                id=wbs.id,
                source_wbs_id=wbs.source_wbs_id,
                wbs_code=wbs.wbs_code,
                wbs_name=wbs.wbs_name,
                parent_wbs_node_id=wbs.parent_wbs_node_id,
                sort_order=wbs.sort_order,
                activity_count=count or 0,
            )
        )

    return nodes
