"""Deterministic milestone forecast service (PI-044).

Rules (01_PRD.md, 02_SYSTEM_ARCHITECTURE.md, 05_AI_AGENT_SPEC.md, 08_DEVELOPMENT_BACKLOG.md):
- Forecast method is explicit ("imported_schedule_dates" or "deterministic_float_indicator").
- Source/imported date is strictly distinguished from calculated projection.
- Missing data/calendar/network limitations are returned.
- No unsupported probabilistic confidence claims (deterministic only, confidence_level=None).
- Hexagonal architecture: zero web, AI, or ingestion framework dependencies.
"""

import math
import uuid
from datetime import date, timedelta
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domains.schedule.schemas import (
    ForecastMethod,
    MilestoneForecastItem,
    MilestoneForecastResponse,
    MilestoneForecastSummary,
)
from app.models.project import Project, ProjectVersion
from app.models.schedule import Activity

# Standard EPC conversion defaults
DEFAULT_HOURS_PER_DAY = 8.0
CRITICAL_FLOAT_HOURS = 0.0
NEAR_CRITICAL_FLOAT_HOURS = 80.0

METHOD_DESCRIPTIONS: dict[ForecastMethod, str] = {
    "imported_schedule_dates": (
        "Imported schedule forecast dates directly from Primavera P6 schedule "
        "without recalculation."
    ),
    "deterministic_float_indicator": (
        "Deterministic slippage projection based on imported CPM total float and "
        "critical path status."
    ),
}

STANDARD_LIMITATIONS: list[str] = [
    (
        "Calendar exceptions, non-working days, and shift patterns were not re-simulated; "
        "working day conversions assume standard 8.0 hr/day and 5-day week ratio."
    ),
    (
        "Relationship lags and driving predecessor chains are preserved as imported from "
        "Primavera P6 without independent schedule leveling or recalculation."
    ),
    (
        "Deterministic projection does not simulate unmodelled future risks, resource "
        "availability constraints, or weather-induced disruptions."
    ),
]


async def _resolve_project_version(
    session: AsyncSession,
    project_id: uuid.UUID,
    version_id: uuid.UUID | None = None,
) -> tuple[uuid.UUID, date | None]:
    """Resolve and validate target project version id and data date."""
    project = await session.get(Project, project_id)
    if not project:
        raise ValueError(f"Project '{project_id}' not found.")

    target_version_id = version_id or project.latest_version_id
    if not target_version_id:
        raise ValueError(f"Project '{project_id}' has no ready versions.")

    version_query = select(ProjectVersion).where(
        ProjectVersion.project_id == project_id,
        ProjectVersion.id == target_version_id,
    )
    res = await session.scalar(version_query)
    if not res:
        raise ValueError(
            f"ProjectVersion '{target_version_id}' not found for project '{project_id}'."
        )
    return target_version_id, res.data_date


def _is_milestone_candidate(act: Activity) -> bool:
    """Determine whether an activity qualifies as a milestone."""
    if act.activity_type:
        norm_type = act.activity_type.lower()
        if "mile" in norm_type or norm_type in ("start_milestone", "finish_milestone"):
            return True
    if act.source_fields and isinstance(act.source_fields, dict):
        raw_type = str(act.source_fields.get("task_type", "")).lower()
        if "mile" in raw_type or raw_type in ("tt_mile", "tt_finmile"):
            return True
    if act.original_duration_hours is not None and float(act.original_duration_hours) == 0.0:
        return True
    return False


async def compute_milestone_forecast(
    session: AsyncSession,
    project_id: uuid.UUID,
    version_id: uuid.UUID | None = None,
    method: ForecastMethod = "imported_schedule_dates",
    milestone_id: str | None = None,
    hours_per_day: float = DEFAULT_HOURS_PER_DAY,
) -> MilestoneForecastResponse:
    """Compute milestone forecast with explicit methodology and transparent limitations (PI-044)."""
    if method not in METHOD_DESCRIPTIONS:
        raise ValueError(
            f"Unsupported forecast method '{method}'. "
            f"Must be one of: {list(METHOD_DESCRIPTIONS.keys())}"
        )

    target_version_id, data_date = await _resolve_project_version(session, project_id, version_id)

    # Base query for activities in version
    stmt = (
        select(Activity)
        .options(selectinload(Activity.wbs_node))
        .where(
            Activity.project_id == project_id,
            Activity.project_version_id == target_version_id,
        )
    )

    # If specific milestone requested by ID, code, or source ID
    target_uuid: uuid.UUID | None = None
    if milestone_id:
        try:
            target_uuid = uuid.UUID(milestone_id)
        except ValueError:
            target_uuid = None

        if target_uuid:
            stmt = stmt.where(
                or_(
                    Activity.id == target_uuid,
                    Activity.source_activity_id == milestone_id,
                    Activity.activity_code == milestone_id,
                )
            )
        else:
            stmt = stmt.where(
                or_(
                    Activity.source_activity_id == milestone_id,
                    Activity.activity_code == milestone_id,
                )
            )

    result = await session.scalars(stmt)
    activities = list(result.all())

    # If no specific milestone was filtered, select only milestone candidates
    if not milestone_id:
        activities = [act for act in activities if _is_milestone_candidate(act)]

    # Sort stably by finish date, then code
    activities.sort(
        key=lambda a: (
            a.actual_finish or a.finish_date or a.planned_finish or date.max,
            a.activity_code or a.source_activity_id,
        )
    )

    items: list[MilestoneForecastItem] = []
    completed_cnt = 0
    in_progress_cnt = 0
    not_started_cnt = 0
    critical_cnt = 0
    slipping_cnt = 0

    for act in activities:
        warnings: list[str] = []

        # Determine source date and date type
        source_date: date | None = None
        source_date_type: Any = "unavailable"
        if act.actual_finish:
            source_date = act.actual_finish
            source_date_type = "actual_finish"
        elif act.finish_date:
            source_date = act.finish_date
            source_date_type = "finish_date"
        elif act.planned_finish:
            source_date = act.planned_finish
            source_date_type = "planned_finish"
        else:
            source_date = None
            source_date_type = "unavailable"
            warnings.append("Milestone has no scheduled or actual finish date.")

        # Determine float metrics
        tf_hours: float | None = None
        tf_days: float | None = None
        if act.total_float_hours is not None:
            tf_hours = round(float(act.total_float_hours), 2)
            tf_days = round(tf_hours / hours_per_day, 2)
        else:
            warnings.append("Total float value is missing or not computed in schedule.")

        # Determine critical status
        critical_status: Any = "unknown"
        if tf_hours is None:
            critical_status = "unknown"
        elif tf_hours <= CRITICAL_FLOAT_HOURS:
            critical_status = "critical"
            critical_cnt += 1
        elif tf_hours <= NEAR_CRITICAL_FLOAT_HOURS:
            critical_status = "near_critical"
        else:
            critical_status = "non_critical"

        # Update status counters
        status_norm = (act.status or "unknown").lower()
        if status_norm in ("complete", "completed") or act.actual_finish is not None:
            completed_cnt += 1
        elif status_norm in ("in_progress", "active"):
            in_progress_cnt += 1
        else:
            not_started_cnt += 1

        # Forecast calculation by selected method
        projected_date: date | None = None
        is_calculated: bool = False
        variance_days: float | None = None
        driving_notes: str | None = None

        if method == "imported_schedule_dates":
            projected_date = source_date
            is_calculated = False
            driving_notes = (
                "Imported schedule date directly from Primavera P6 without recalculation."
            )
            # Baseline variance if both planned_finish and finish_date exist
            if act.planned_finish and act.finish_date:
                variance_days = float((act.finish_date - act.planned_finish).days)
                if variance_days > 0:
                    slipping_cnt += 1
            else:
                variance_days = 0.0

        elif method == "deterministic_float_indicator":
            if act.status in ("complete", "completed") or act.actual_finish:
                projected_date = source_date
                is_calculated = False
                variance_days = 0.0
                driving_notes = "Milestone is completed; projection matches actual finish."
            elif tf_hours is None:
                projected_date = source_date
                is_calculated = False
                variance_days = None
                driving_notes = "Total float unavailable; cannot project deterministic slippage."
                warnings.append("Cannot compute deterministic projection due to missing float.")
            elif tf_hours < 0:
                # Negative float indicates contractual completion slippage
                working_slip = round(abs(tf_hours) / hours_per_day, 1)
                # Convert working days to calendar days using standard 7/5 EPC factor
                cal_slip = math.ceil(working_slip * (7.0 / 5.0))
                projected_date = source_date + timedelta(days=cal_slip) if source_date else None
                is_calculated = True
                variance_days = working_slip
                slipping_cnt += 1
                driving_notes = (
                    f"Negative total float ({tf_hours}h / {working_slip} working days) "
                    f"projects deterministic completion slip of {cal_slip} calendar days."
                )
            else:
                projected_date = source_date
                is_calculated = False
                variance_days = 0.0
                driving_notes = (
                    f"Non-negative float ({tf_hours}h); milestone is on schedule per CPM network."
                )

        item = MilestoneForecastItem(
            activity_id=act.id,
            source_activity_id=act.source_activity_id,
            activity_code=act.activity_code,
            activity_name=act.activity_name,
            wbs_code=act.wbs_node.wbs_code if act.wbs_node else None,
            wbs_name=act.wbs_node.wbs_name if act.wbs_node else None,
            activity_type=act.activity_type,
            status=act.status,
            source_date=source_date,
            source_date_type=source_date_type,
            projected_date=projected_date,
            is_calculated_projection=is_calculated,
            variance_days=variance_days,
            total_float_hours=tf_hours,
            total_float_days=tf_days,
            critical_status=critical_status,
            driving_notes=driving_notes,
            warnings=warnings,
        )
        items.append(item)

    summary = MilestoneForecastSummary(
        total_milestones=len(items),
        completed_milestones=completed_cnt,
        in_progress_milestones=in_progress_cnt,
        not_started_milestones=not_started_cnt,
        critical_milestones=critical_cnt,
        delayed_or_slipping_milestones=slipping_cnt,
    )

    return MilestoneForecastResponse(
        project_id=project_id,
        project_version_id=target_version_id,
        data_date=data_date,
        method=method,
        method_description=METHOD_DESCRIPTIONS[method],
        summary=summary,
        items=items,
        limitations=STANDARD_LIMITATIONS,
    )
