"""Deterministic float and critical exposure analysis service (PI-032).

Rules (02_SYSTEM_ARCHITECTURE.md, 08_DEVELOPMENT_BACKLOG.md PI-032):
- Threshold is explicit/configurable.
- Negative, zero, and near-critical bands are separated.
- Output labels imported source float vs recalculated value.
- Safe unit conversion between hours and days using hours_per_day (default 8.0).
- Missing float fields are tracked as unavailable/missing, never coerced to 0 or 0.0.
- Strict domain isolation: no web/API framework imports.
"""

import uuid
from typing import Literal

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.schedule.schemas import (
    CriticalExposureItem,
    CriticalExposureResponse,
    FloatBandSummary,
    FloatDistributionResponse,
)
from app.models.project import Project, ProjectVersion
from app.models.schedule import Activity


async def _resolve_project_version(
    session: AsyncSession,
    project_id: uuid.UUID,
    version_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """Resolve and validate target project version id."""
    project = await session.get(Project, project_id)
    if not project:
        raise ValueError(f"Project '{project_id}' not found.")

    target_version_id = version_id or project.latest_version_id
    if not target_version_id:
        raise ValueError(f"Project '{project_id}' has no ready versions.")

    version_query = select(ProjectVersion.id).where(
        ProjectVersion.project_id == project_id,
        ProjectVersion.id == target_version_id,
    )
    res = await session.scalar(version_query)
    if not res:
        raise ValueError(
            f"ProjectVersion '{target_version_id}' not found for project '{project_id}'."
        )
    return target_version_id


async def compute_float_distribution(
    session: AsyncSession,
    project_id: uuid.UUID,
    version_id: uuid.UUID | None = None,
    critical_threshold_hours: float = 0.0,
    near_critical_threshold_hours: float = 80.0,
    hours_per_day: float = 8.0,
) -> FloatDistributionResponse:
    """Compute deterministic total float histogram and band distribution."""
    if hours_per_day <= 0:
        raise ValueError("hours_per_day must be strictly positive.")

    target_version_id = await _resolve_project_version(session, project_id, version_id)

    low_float_upper = max(160.0, near_critical_threshold_hours * 2.0)

    # 1. Aggregate statistics in a single SQL query
    stats_query = select(
        func.count(Activity.id).label("total"),
        func.count(case((Activity.total_float_hours.is_not(None), 1))).label("with_float"),
        func.count(case((Activity.total_float_hours.is_(None), 1))).label("missing_float"),
        func.min(Activity.total_float_hours).label("min_float"),
        func.max(Activity.total_float_hours).label("max_float"),
        # Bands
        func.count(
            case(
                (
                    Activity.total_float_hours.is_not(None) & (Activity.total_float_hours < 0.0),
                    1,
                )
            )
        ).label("negative_count"),
        func.count(
            case(
                (
                    Activity.total_float_hours.is_not(None) & (Activity.total_float_hours == 0.0),
                    1,
                )
            )
        ).label("zero_count"),
        func.count(
            case(
                (
                    Activity.total_float_hours.is_not(None)
                    & (Activity.total_float_hours > 0.0)
                    & (Activity.total_float_hours <= near_critical_threshold_hours),
                    1,
                )
            )
        ).label("near_critical_count"),
        func.count(
            case(
                (
                    Activity.total_float_hours.is_not(None)
                    & (Activity.total_float_hours > near_critical_threshold_hours)
                    & (Activity.total_float_hours <= low_float_upper),
                    1,
                )
            )
        ).label("low_float_count"),
        func.count(
            case(
                (
                    Activity.total_float_hours.is_not(None)
                    & (Activity.total_float_hours > low_float_upper),
                    1,
                )
            )
        ).label("high_float_count"),
    ).where(Activity.project_version_id == target_version_id)

    row = (await session.execute(stats_query)).one()

    total_activities = row.total or 0
    with_float = row.with_float or 0
    missing_float = row.missing_float or 0
    min_float = float(row.min_float) if row.min_float is not None else None
    max_float = float(row.max_float) if row.max_float is not None else None

    def _pct(count: int) -> float:
        if total_activities == 0:
            return 0.0
        return round((count / total_activities) * 100.0, 2)

    negative_cnt = row.negative_count or 0
    zero_cnt = row.zero_count or 0
    near_crit_cnt = row.near_critical_count or 0
    low_float_cnt = row.low_float_count or 0
    high_float_cnt = row.high_float_count or 0

    bands = [
        FloatBandSummary(
            name="negative",
            label="Negative (< 0h)",
            min_hours=None,
            max_hours=0.0,
            count=negative_cnt,
            percentage=_pct(negative_cnt),
        ),
        FloatBandSummary(
            name="zero",
            label="Zero Float (0h)",
            min_hours=0.0,
            max_hours=0.0,
            count=zero_cnt,
            percentage=_pct(zero_cnt),
        ),
        FloatBandSummary(
            name="near_critical",
            label=f"Near-Critical (0h - {near_critical_threshold_hours:g}h)",
            min_hours=0.0,
            max_hours=near_critical_threshold_hours,
            count=near_crit_cnt,
            percentage=_pct(near_crit_cnt),
        ),
        FloatBandSummary(
            name="low_float",
            label=f"Low Float ({near_critical_threshold_hours:g}h - {low_float_upper:g}h)",
            min_hours=near_critical_threshold_hours,
            max_hours=low_float_upper,
            count=low_float_cnt,
            percentage=_pct(low_float_cnt),
        ),
        FloatBandSummary(
            name="high_float",
            label=f"High Float (> {low_float_upper:g}h)",
            min_hours=low_float_upper,
            max_hours=None,
            count=high_float_cnt,
            percentage=_pct(high_float_cnt),
        ),
        FloatBandSummary(
            name="missing",
            label="Missing / Unavailable",
            min_hours=None,
            max_hours=None,
            count=missing_float,
            percentage=_pct(missing_float),
        ),
    ]

    return FloatDistributionResponse(
        project_id=project_id,
        version_id=target_version_id,
        float_source="imported_source",
        method="source_total_float_threshold",
        critical_threshold_hours=critical_threshold_hours,
        near_critical_threshold_hours=near_critical_threshold_hours,
        hours_per_day=hours_per_day,
        total_activities=total_activities,
        activities_with_float=with_float,
        activities_missing_float=missing_float,
        min_float_hours=min_float,
        max_float_hours=max_float,
        bands=bands,
    )


ExposureBand = Literal["negative", "zero", "critical", "near_critical", "all_exposed"]


async def get_critical_exposure_activities(
    session: AsyncSession,
    project_id: uuid.UUID,
    version_id: uuid.UUID | None = None,
    band: ExposureBand | str | None = None,
    critical_threshold_hours: float = 0.0,
    near_critical_threshold_hours: float = 80.0,
    hours_per_day: float = 8.0,
    limit: int = 50,
    offset: int = 0,
) -> CriticalExposureResponse:
    """Retrieve and paginate activities within critical/near-critical exposure bands."""
    if hours_per_day <= 0:
        raise ValueError("hours_per_day must be strictly positive.")

    target_version_id = await _resolve_project_version(session, project_id, version_id)

    # Base filter: exclude missing float
    conditions = [
        Activity.project_version_id == target_version_id,
        Activity.total_float_hours.is_not(None),
    ]

    effective_band = band or "all_exposed"
    if effective_band == "negative":
        conditions.append(Activity.total_float_hours < 0.0)
    elif effective_band == "zero":
        conditions.append(Activity.total_float_hours == 0.0)
    elif effective_band == "critical":
        conditions.append(Activity.total_float_hours <= critical_threshold_hours)
    elif effective_band == "near_critical":
        conditions.append(Activity.total_float_hours > 0.0)
        conditions.append(Activity.total_float_hours <= near_critical_threshold_hours)
    elif effective_band == "all_exposed":
        cutoff = max(critical_threshold_hours, near_critical_threshold_hours)
        conditions.append(Activity.total_float_hours <= cutoff)
    else:
        raise ValueError(
            f"Invalid exposure band '{effective_band}'. Must be one of: "
            "negative, zero, critical, near_critical, all_exposed."
        )

    # Count total exposed matching condition
    count_query = select(func.count(Activity.id)).where(*conditions)
    total_exposed = await session.scalar(count_query) or 0

    # Query items ordered by total_float_hours asc, then code
    items_query = (
        select(Activity)
        .where(*conditions)
        .order_by(Activity.total_float_hours.asc(), Activity.activity_code.asc())
        .limit(limit)
        .offset(offset)
    )

    rows = (await session.scalars(items_query)).all()

    items: list[CriticalExposureItem] = []
    for act in rows:
        tf_h = float(act.total_float_hours) if act.total_float_hours is not None else None
        tf_d = round(tf_h / hours_per_day, 2) if tf_h is not None else None

        ff_h = float(act.free_float_hours) if act.free_float_hours is not None else None
        ff_d = round(ff_h / hours_per_day, 2) if ff_h is not None else None

        if tf_h is None:
            act_band = "missing"
        elif tf_h < 0.0:
            act_band = "negative"
        elif tf_h == 0.0:
            act_band = "zero"
        elif tf_h <= near_critical_threshold_hours:
            act_band = "near_critical"
        else:
            act_band = "low_float"

        is_crit = tf_h is not None and tf_h <= critical_threshold_hours

        items.append(
            CriticalExposureItem(
                id=act.id,
                source_activity_id=act.source_activity_id,
                activity_code=act.activity_code,
                activity_name=act.activity_name,
                status=act.status,
                total_float_hours=tf_h,
                total_float_days=tf_d,
                free_float_hours=ff_h,
                free_float_days=ff_d,
                start_date=act.actual_start or act.planned_start or act.start_date,
                finish_date=act.actual_finish or act.planned_finish or act.finish_date,
                float_band=act_band,
                is_critical=is_crit,
            )
        )

    return CriticalExposureResponse(
        project_id=project_id,
        version_id=target_version_id,
        float_source="imported_source",
        method="source_total_float_threshold",
        critical_threshold_hours=critical_threshold_hours,
        near_critical_threshold_hours=near_critical_threshold_hours,
        hours_per_day=hours_per_day,
        band=effective_band,
        total_exposed=total_exposed,
        items=items,
        limit=limit,
        offset=offset,
    )
