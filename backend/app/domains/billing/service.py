"""Usage metering, plan limit enforcement, and summary services (PI-050)."""

import calendar
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import Workspace
from app.models.project import Project
from app.models.reporting import UsageEvent

from .plans import get_plan_definition
from .schemas import (
    PlanLimitExceededError,
    UsageMetricSummary,
    UsageSummaryResponse,
)


def get_billing_period(now: datetime | None = None) -> tuple[datetime, datetime, datetime]:
    """Calculate current billing cycle start, end, and reset date (calendar month basis)."""
    current = now or datetime.now(UTC)
    year = current.year
    month = current.month

    period_start = datetime(year, month, 1, 0, 0, 0, tzinfo=UTC)
    _, last_day = calendar.monthrange(year, month)
    period_end = datetime(year, month, last_day, 23, 59, 59, 999999, tzinfo=UTC)

    if month == 12:
        reset_date = datetime(year + 1, 1, 1, 0, 0, 0, tzinfo=UTC)
    else:
        reset_date = datetime(year, month + 1, 1, 0, 0, 0, tzinfo=UTC)

    return period_start, period_end, reset_date


async def record_usage_event(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    event_type: str,
    quantity: float = 1.0,
    unit: str = "count",
    user_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    metadata: dict[str, Any] | None = None,
    estimated_cost_usd: float | None = None,
) -> UsageEvent:
    """Record a platform usage metering event."""
    event = UsageEvent(
        workspace_id=workspace_id,
        user_id=user_id,
        project_id=project_id,
        event_type=event_type,
        quantity=quantity,
        unit=unit,
        estimated_cost_usd=estimated_cost_usd,
        metadata_=metadata or {},
        created_at=datetime.now(UTC),
    )
    session.add(event)
    await session.flush()
    return event


async def enforce_plan_limit(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    metric_name: str,
    incoming_quantity: float = 1.0,
) -> None:
    """Check workspace quota before operation. Raises PlanLimitExceededError if limit is reached."""
    workspace = await session.get(Workspace, workspace_id)
    if not workspace:
        raise ValueError(f"Workspace '{workspace_id}' not found.")

    plan = get_plan_definition(workspace.plan_code)

    if metric_name == "active_projects":
        limit = float(plan.quotas.max_projects)
        active_count_res = await session.execute(
            select(func.count(Project.id)).where(
                Project.workspace_id == workspace_id,
                Project.status == "active",
            )
        )
        current_active = float(active_count_res.scalar_one())
        if current_active + incoming_quantity > limit:
            raise PlanLimitExceededError(
                metric_name=metric_name,
                current_usage=current_active,
                limit=limit,
                plan_code=plan.code,
                message=(
                    f"Active project limit exceeded: workspace currently has {int(current_active)} "
                    f"active project(s), which reaches the limit of {int(limit)} for the "
                    f"{plan.name} plan. Upgrade to create more projects."
                ),
            )
        return

    # Monthly usage event limits
    quota_map: dict[str, int] = {
        "file_upload": plan.quotas.max_file_uploads_per_month,
        "file_import": plan.quotas.max_imports_per_month,
        "ai_query": plan.quotas.max_ai_queries_per_month,
        "scenario": plan.quotas.max_scenarios_per_month,
        "report_export": plan.quotas.max_reports_per_month,
    }

    if metric_name not in quota_map:
        return

    limit = float(quota_map[metric_name])
    period_start, period_end, _ = get_billing_period()

    stmt = select(func.coalesce(func.sum(UsageEvent.quantity), 0.0)).where(
        UsageEvent.workspace_id == workspace_id,
        UsageEvent.event_type == metric_name,
        UsageEvent.created_at >= period_start,
        UsageEvent.created_at <= period_end,
    )
    current_used = float((await session.execute(stmt)).scalar_one())

    if current_used + incoming_quantity > limit:
        raise PlanLimitExceededError(
            metric_name=metric_name,
            current_usage=current_used,
            limit=limit,
            plan_code=plan.code,
        )


async def get_workspace_usage_summary(
    session: AsyncSession,
    workspace_id: uuid.UUID,
) -> UsageSummaryResponse:
    """Retrieve full usage and plan limit summary for the active billing cycle."""
    workspace = await session.get(Workspace, workspace_id)
    if not workspace:
        raise ValueError(f"Workspace '{workspace_id}' not found.")

    plan = get_plan_definition(workspace.plan_code)
    period_start, period_end, reset_date = get_billing_period()

    # 1. Active Projects Count
    active_count_res = await session.execute(
        select(func.count(Project.id)).where(
            Project.workspace_id == workspace_id,
            Project.status == "active",
        )
    )
    active_projects = float(active_count_res.scalar_one())

    # 2. Aggregated Monthly Usage Events
    stmt = (
        select(UsageEvent.event_type, func.coalesce(func.sum(UsageEvent.quantity), 0.0))
        .where(
            UsageEvent.workspace_id == workspace_id,
            UsageEvent.created_at >= period_start,
            UsageEvent.created_at <= period_end,
        )
        .group_by(UsageEvent.event_type)
    )
    usage_rows = (await session.execute(stmt)).all()
    usage_by_type: dict[str, float] = {row[0]: float(row[1]) for row in usage_rows}

    # 3. Construct Metric Summaries
    metrics_config: list[tuple[str, str, float, float, str]] = [
        (
            "active_projects",
            "Active Projects",
            active_projects,
            float(plan.quotas.max_projects),
            "projects",
        ),
        (
            "file_upload",
            "File Uploads",
            usage_by_type.get("file_upload", 0.0),
            float(plan.quotas.max_file_uploads_per_month),
            "uploads",
        ),
        (
            "file_import",
            "Schedule Imports",
            usage_by_type.get("file_import", 0.0),
            float(plan.quotas.max_imports_per_month),
            "imports",
        ),
        (
            "ai_query",
            "AI Assistant Inquiries",
            usage_by_type.get("ai_query", 0.0),
            float(plan.quotas.max_ai_queries_per_month),
            "queries",
        ),
        (
            "scenario",
            "What-If Simulations",
            usage_by_type.get("scenario", 0.0),
            float(plan.quotas.max_scenarios_per_month),
            "simulations",
        ),
        (
            "report_export",
            "Reports & Tabular Exports",
            usage_by_type.get("report_export", 0.0),
            float(plan.quotas.max_reports_per_month),
            "exports",
        ),
    ]

    metrics: list[UsageMetricSummary] = []
    for m_name, label, used, limit, unit in metrics_config:
        remaining = max(0.0, limit - used) if limit > 0 else 0.0
        pct = round(min(100.0, (used / limit) * 100.0), 1) if limit > 0 else 0.0
        metrics.append(
            UsageMetricSummary(
                metric_name=m_name,
                display_label=label,
                used=used,
                limit=limit,
                remaining=remaining,
                unit=unit,
                percent_used=pct,
            )
        )

    return UsageSummaryResponse(
        workspace_id=workspace_id,
        plan_code=plan.code,
        plan_name=plan.name,
        billing_period_start=period_start,
        billing_period_end=period_end,
        reset_date=reset_date,
        metrics=metrics,
    )
