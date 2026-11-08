"""Deterministic schedule metrics service (PI-030).

Rules (02_SYSTEM_ARCHITECTURE.md, 08_DEVELOPMENT_BACKLOG.md PI-030):
- Activity counts and status distribution computed from selected version.
- Data date and source finish information shown.
- Missing fields display as unavailable (None), never coerced to 0 or 0.0.
- Strict domain isolation: no web/API framework imports.
"""

import uuid

from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.schedule.schemas import (
    ActivityStatusDistribution,
    ProjectOverviewMetrics,
)
from app.models.project import ImportJob, Project, ProjectVersion, UploadedFile
from app.models.schedule import (
    Activity,
    ActivityRelationship,
    Calendar,
    WBSNode,
)


async def compute_project_overview_metrics(
    session: AsyncSession,
    project_id: uuid.UUID,
    version_id: uuid.UUID | None = None,
    critical_float_threshold_hours: float = 0.0,
    near_critical_float_threshold_hours: float = 80.0,
) -> ProjectOverviewMetrics:
    """Compute deterministic project overview KPIs from normalized schedule data."""
    # 1. Fetch project
    project = await session.get(Project, project_id)
    if not project:
        raise ValueError(f"Project '{project_id}' not found.")

    target_version_id = version_id or project.latest_version_id
    if not target_version_id:
        raise ValueError(f"Project '{project_id}' has no ready versions.")

    # 2. Query ProjectVersion joined with UploadedFile to get source filename
    version_query = (
        select(ProjectVersion, UploadedFile.original_filename)
        .join(ImportJob, ImportJob.id == ProjectVersion.import_job_id)
        .join(UploadedFile, UploadedFile.id == ImportJob.uploaded_file_id)
        .where(
            ProjectVersion.project_id == project_id,
            ProjectVersion.id == target_version_id,
        )
    )
    version_row = (await session.execute(version_query)).first()
    if not version_row:
        raise ValueError(
            f"ProjectVersion '{target_version_id}' not found for project '{project_id}'."
        )

    pv, original_filename = version_row

    # 3. Aggregate activity metrics
    act_stats_query = select(
        func.count(Activity.id).label("total"),
        func.count(case((Activity.status == "not_started", 1))).label("not_started"),
        func.count(case((Activity.status == "in_progress", 1))).label("in_progress"),
        func.count(case((Activity.status == "complete", 1))).label("complete"),
        func.count(case((Activity.status == "suspended", 1))).label("suspended"),
        func.count(case((Activity.status == "unknown", 1))).label("unknown"),
        func.count(
            case(
                (
                    or_(
                        Activity.activity_type.in_(("start_milestone", "finish_milestone")),
                        Activity.original_duration_hours == 0.0,
                    ),
                    1,
                )
            )
        ).label("milestones"),
        func.count(
            case(
                (
                    Activity.total_float_hours.is_not(None)
                    & (Activity.total_float_hours <= critical_float_threshold_hours),
                    1,
                )
            )
        ).label("critical"),
        func.count(
            case(
                (
                    Activity.total_float_hours.is_not(None)
                    & (Activity.total_float_hours > critical_float_threshold_hours)
                    & (Activity.total_float_hours <= near_critical_float_threshold_hours),
                    1,
                )
            )
        ).label("near_critical"),
        func.min(Activity.total_float_hours).label("min_float"),
        func.max(Activity.total_float_hours).label("max_float"),
        func.avg(Activity.physical_pct_complete).label("avg_physical_pct"),
        func.min(Activity.start_date).label("earliest_start"),
        func.max(Activity.finish_date).label("latest_finish"),
    ).where(Activity.project_version_id == target_version_id)

    stats_row = (await session.execute(act_stats_query)).one()

    (
        total_act,
        not_started,
        in_progress,
        complete,
        suspended,
        unknown,
        milestones,
        critical,
        near_critical,
        min_float,
        max_float,
        avg_physical_pct,
        earliest_start,
        latest_finish,
    ) = stats_row

    # 4. Count structural entities
    calendars_count = (
        await session.execute(
            select(func.count(Calendar.id)).where(Calendar.project_version_id == target_version_id)
        )
    ).scalar() or 0

    wbs_count = (
        await session.execute(
            select(func.count(WBSNode.id)).where(WBSNode.project_version_id == target_version_id)
        )
    ).scalar() or 0

    relationships_count = (
        await session.execute(
            select(func.count(ActivityRelationship.id)).where(
                ActivityRelationship.project_version_id == target_version_id
            )
        )
    ).scalar() or 0

    # 5. Determine project dates (prefer version level, fallback to activities)
    start_date = pv.project_start_date or earliest_start
    finish_date = pv.project_finish_date or latest_finish

    # 6. Build and return ProjectOverviewMetrics
    min_float_val = float(min_float) if min_float is not None else None
    max_float_val = float(max_float) if max_float is not None else None
    avg_phys_val = float(round(avg_physical_pct, 2)) if avg_physical_pct is not None else None

    warnings_count = 0
    if isinstance(pv.quality_summary, dict):
        warnings_count = int(pv.quality_summary.get("warnings_count", 0))

    return ProjectOverviewMetrics(
        project_id=project.id,
        project_name=project.name,
        version_id=pv.id,
        version_number=pv.version_number,
        version_label=pv.version_label or f"V{pv.version_number}",
        data_date=pv.data_date,
        project_start_date=start_date,
        project_finish_date=finish_date,
        source_filename=original_filename,
        source_format=pv.source_format,
        total_activities=total_act or 0,
        status_distribution=ActivityStatusDistribution(
            not_started=not_started or 0,
            in_progress=in_progress or 0,
            complete=complete or 0,
            suspended=suspended or 0,
            unknown=unknown or 0,
        ),
        milestones_count=milestones or 0,
        critical_activities_count=critical or 0,
        near_critical_activities_count=near_critical or 0,
        min_total_float_hours=min_float_val,
        max_total_float_hours=max_float_val,
        avg_physical_pct_complete=avg_phys_val,
        calendars_count=calendars_count,
        wbs_nodes_count=wbs_count,
        relationships_count=relationships_count,
        warnings_count=warnings_count,
    )
