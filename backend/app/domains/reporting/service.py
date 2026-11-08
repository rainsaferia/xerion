"""Reporting domain service (PI-046).

Rules (01_PRD.md, 02_SYSTEM_ARCHITECTURE.md, 06_API_SPEC.md, 08_DEVELOPMENT_BACKLOG.md):
- Coordinates deterministic data gathering, PDF generation, and private storage persistence.
- Creates immutable Report rows in database and tracks report_export in usage_events.
- Issues and verifies short-lived signed download tokens.
- Hexagonal domain isolation: strictly zero web framework (FastAPI/Starlette)
  or storage adapter imports.
"""

import contextlib
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.reporting.pdf_generator import build_schedule_analysis_pdf
from app.domains.reporting.schemas import ActivityExportRow

# pyrefly: ignore[missing-import]
from app.domains.reporting.tabular_exporter import (
    export_activities_to_csv,
    export_activities_to_xlsx,
)
from app.domains.schedule.forecast import compute_milestone_forecast
from app.domains.schedule.metrics import compute_project_overview_metrics
from app.domains.schedule.quality import run_schedule_quality_checks
from app.models.project import Project, ProjectVersion
from app.models.reporting import Report, UsageEvent
from app.models.schedule import Activity, Calendar, WBSNode

# Type for injected async storage put callable: (object_key, bytes_data, content_type) -> None
StoragePutCallable = Callable[[str, bytes, str], Awaitable[None]]


async def generate_schedule_report(
    session: AsyncSession,
    storage_put_fn: StoragePutCallable,
    project_id: uuid.UUID,
    version_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    user_email: str | None = None,
    report_type: str = "schedule_analysis",
    output_format: str = "pdf",
    options: dict[str, Any] | None = None,
) -> Report:
    """Generate a schedule report, save to private storage, and update database record."""
    opts = options or {}

    # 1. Resolve project
    project = await session.get(Project, project_id)
    if not project:
        raise ValueError(f"Project '{project_id}' not found.")

    target_version_id = version_id or project.latest_version_id
    if not target_version_id:
        raise ValueError(f"Project '{project_id}' has no ready versions.")

    version = await session.get(ProjectVersion, target_version_id)
    if not version or version.project_id != project_id:
        raise ValueError(
            f"ProjectVersion '{target_version_id}' not found for project '{project_id}'."
        )

    # 2. Create preliminary Report record in generating state
    title = f"Schedule Analysis - {project.name}"
    report = Report(
        workspace_id=project.workspace_id,
        project_id=project.id,
        project_version_id=target_version_id,
        report_type=report_type,
        title=title,
        output_format=output_format,
        status="generating",
        parameters=opts,
        generated_by=user_id,
    )
    session.add(report)
    await session.flush()

    try:
        # 3. Gather deterministic schedule metrics
        metrics_dict: dict[str, Any] = {}
        try:
            overview = await compute_project_overview_metrics(
                session=session,
                project_id=project_id,
                version_id=target_version_id,
            )
            metrics_dict = {
                "total_activities": overview.total_activities,
                "not_started_count": overview.status_distribution.not_started,
                "in_progress_count": overview.status_distribution.in_progress,
                "completed_count": overview.status_distribution.complete,
                "critical_count": overview.critical_activities_count,
                "planned_start": str(overview.project_start_date)
                if overview.project_start_date
                else None,
                "planned_finish": str(overview.project_finish_date)
                if overview.project_finish_date
                else None,
            }
        except Exception:
            # Fallback if raw version has no import job join
            act_counts = await session.execute(
                select(
                    func.count(Activity.id),
                    func.count(Activity.id).filter(Activity.status == "not_started"),
                    func.count(Activity.id).filter(Activity.status == "in_progress"),
                    func.count(Activity.id).filter(Activity.status == "complete"),
                    func.count(Activity.id).filter(Activity.total_float_hours <= 0),
                    func.min(Activity.start_date),
                    func.max(Activity.finish_date),
                ).where(Activity.project_version_id == target_version_id)
            )
            row = act_counts.one()
            metrics_dict = {
                "total_activities": row[0],
                "not_started_count": row[1],
                "in_progress_count": row[2],
                "completed_count": row[3],
                "critical_count": row[4],
                "planned_start": str(row[5]) if row[5] else None,
                "planned_finish": str(row[6]) if row[6] else None,
            }

        # 4. Gather schedule quality findings
        quality_summary: dict[str, Any] = {
            "passed_checks": 0,
            "warning_checks": 0,
            "error_checks": 0,
            "findings": [],
        }
        with contextlib.suppress(Exception):
            quality_report = await run_schedule_quality_checks(
                session=session,
                project_id=project_id,
                version_id=target_version_id,
                persist=False,
            )
            findings_list = []
            for item in quality_report.findings:
                findings_list.append(
                    {
                        "category": item.category,
                        "severity": item.severity,
                        "rule_id": item.check_code,
                        "description": item.message,
                    }
                )
            quality_summary = {
                "passed_checks": len(quality_report.summary.checks_run),
                "warning_checks": quality_report.summary.by_severity.get("warning", 0),
                "error_checks": quality_report.summary.by_severity.get("error", 0),
                "findings": findings_list,
            }

        # 5. Gather milestone forecasts
        milestone_forecasts: list[dict[str, Any]] = []
        with contextlib.suppress(Exception):
            forecast_resp = await compute_milestone_forecast(
                session=session,
                project_id=project_id,
                version_id=target_version_id,
                method="imported_schedule_dates",
            )
            for m in forecast_resp.items:
                milestone_forecasts.append(
                    {
                        "activity_code": m.activity_code,
                        "activity_name": m.activity_name,
                        "source_finish_date": str(m.source_date) if m.source_date else None,
                        "forecast_finish_date": str(m.projected_date) if m.projected_date else None,
                        "variance_days": m.variance_days,
                        "float_indicator": m.critical_status,
                    }
                )

        # 6. Build PDF bytes
        generated_at = datetime.now(UTC)
        pdf_bytes = build_schedule_analysis_pdf(
            project_name=project.name,
            project_code=project.project_code or "",
            project_version_id=target_version_id,
            data_date=version.data_date,
            generated_at=generated_at,
            generated_by_email=user_email,
            metrics=metrics_dict,
            quality_summary=quality_summary,
            milestone_forecasts=milestone_forecasts,
            options=opts,
        )

        # 7. Write to private object storage
        object_key = (
            f"workspaces/{project.workspace_id}/projects/{project.id}/reports/{report.id}.pdf"
        )
        await storage_put_fn(object_key, pdf_bytes, "application/pdf")

        # 8. Update Report record to ready
        report.status = "ready"
        report.object_key = object_key
        report.completed_at = datetime.now(UTC)

        # 9. Log usage metering event
        usage_event = UsageEvent(
            workspace_id=project.workspace_id,
            user_id=user_id,
            project_id=project.id,
            event_type="report_export",
            quantity=1.0,
            unit="report",
            metadata_={
                "report_id": str(report.id),
                "project_version_id": str(target_version_id),
                "output_format": output_format,
                "file_size_bytes": len(pdf_bytes),
            },
        )
        session.add(usage_event)
        await session.flush()

        return report

    except Exception:
        report.status = "failed"
        await session.flush()
        raise


async def generate_activity_export(
    session: AsyncSession,
    storage_put_fn: StoragePutCallable,
    project_id: uuid.UUID,
    version_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    output_format: str = "csv",
    status_filter: str | None = None,
    wbs_code_filter: str | None = None,
    search_query: str | None = None,
    critical_only: bool = False,
) -> Report:
    """Generate filtered activity tabular export in CSV or XLSX format (PI-047)."""
    # 1. Resolve project and version
    project = await session.get(Project, project_id)
    if not project:
        raise ValueError(f"Project '{project_id}' not found.")

    target_version_id = version_id or project.latest_version_id
    if not target_version_id:
        raise ValueError(f"Project '{project_id}' has no ready versions.")

    version = await session.get(ProjectVersion, target_version_id)
    if not version or version.project_id != project_id:
        raise ValueError(
            f"ProjectVersion '{target_version_id}' not found for project '{project_id}'."
        )

    # 2. Record preliminary report record
    fmt = output_format.lower()
    if fmt not in ("csv", "xlsx"):
        raise ValueError(f"Unsupported output format: '{output_format}'. Must be 'csv' or 'xlsx'.")

    params: dict[str, Any] = {
        "status": status_filter,
        "wbs_code": wbs_code_filter,
        "search": search_query,
        "critical_only": critical_only,
    }
    title = f"Activity Export - {project.name} ({fmt.upper()})"
    report = Report(
        workspace_id=project.workspace_id,
        project_id=project.id,
        project_version_id=target_version_id,
        report_type="activity_export",
        title=title,
        output_format=fmt,
        status="generating",
        parameters=params,
        generated_by=user_id,
    )
    session.add(report)
    await session.flush()

    try:
        # 3. Query activities with filters
        stmt = (
            select(Activity, WBSNode.wbs_code, WBSNode.wbs_name, Calendar.calendar_name)
            .outerjoin(WBSNode, Activity.wbs_node_id == WBSNode.id)
            .outerjoin(Calendar, Activity.calendar_id == Calendar.id)
            .where(Activity.project_version_id == target_version_id)
        )
        if status_filter:
            stmt = stmt.where(Activity.status == status_filter)
        if wbs_code_filter:
            stmt = stmt.where(WBSNode.wbs_code.startswith(wbs_code_filter))
        if search_query:
            q = f"%{search_query}%"
            stmt = stmt.where(Activity.activity_code.ilike(q) | Activity.activity_name.ilike(q))
        if critical_only:
            stmt = stmt.where(Activity.total_float_hours <= 0)

        stmt = stmt.order_by(WBSNode.wbs_code.nulls_last(), Activity.activity_code.nulls_last())
        result = await session.execute(stmt)

        export_rows: list[ActivityExportRow] = []
        for act, wbs_code, wbs_name, cal_name in result.all():
            export_rows.append(
                ActivityExportRow(
                    source_activity_id=act.source_activity_id,
                    activity_code=act.activity_code,
                    activity_name=act.activity_name,
                    wbs_code=wbs_code,
                    wbs_name=wbs_name,
                    status=act.status,
                    activity_type=act.activity_type,
                    planned_start=act.planned_start,
                    planned_finish=act.planned_finish,
                    actual_start=act.actual_start,
                    actual_finish=act.actual_finish,
                    original_duration_hours=float(act.original_duration_hours)
                    if act.original_duration_hours is not None
                    else None,
                    remaining_duration_hours=float(act.remaining_duration_hours)
                    if act.remaining_duration_hours is not None
                    else None,
                    actual_duration_hours=float(act.actual_duration_hours)
                    if act.actual_duration_hours is not None
                    else None,
                    total_float_hours=float(act.total_float_hours)
                    if act.total_float_hours is not None
                    else None,
                    free_float_hours=float(act.free_float_hours)
                    if act.free_float_hours is not None
                    else None,
                    physical_pct_complete=float(act.physical_pct_complete)
                    if act.physical_pct_complete is not None
                    else None,
                    calendar_name=cal_name,
                )
            )

        # 4. Generate tabular file bytes
        if fmt == "csv":
            content_type = "text/csv; charset=utf-8"
            file_bytes = export_activities_to_csv(export_rows)
        else:
            content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            file_bytes = export_activities_to_xlsx(
                export_rows,
                project_code=project.project_code or "PROJECT",
                version_label=version.version_label or "v1",
            )

        # 5. Persist to private storage
        object_key = (
            f"workspaces/{project.workspace_id}/projects/{project.id}/exports/{report.id}.{fmt}"
        )
        await storage_put_fn(object_key, file_bytes, content_type)

        # 6. Update report record
        report.object_key = object_key
        report.status = "ready"
        report.completed_at = datetime.now(UTC)

        # 7. Record usage metering event
        usage_event = UsageEvent(
            workspace_id=project.workspace_id,
            user_id=user_id,
            project_id=project.id,
            event_type="report_export",
            quantity=1.0,
            unit="export",
            metadata_={
                "report_id": str(report.id),
                "project_version_id": str(target_version_id),
                "output_format": fmt,
                "file_size_bytes": len(file_bytes),
                "row_count": len(export_rows),
            },
        )
        session.add(usage_event)
        await session.flush()

        return report

    except Exception:
        report.status = "failed"
        await session.flush()
        raise


def create_report_download_token(
    report_id: uuid.UUID,
    project_id: uuid.UUID,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    auth_subject: str,
    secret_key: str,
    expires_in_seconds: int = 900,
    issuer: str | None = None,
    audience: str | None = None,
) -> str:
    """Generate a signed, short-lived JWT download token for a report artifact."""
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": auth_subject,
        "report_id": str(report_id),
        "project_id": str(project_id),
        "workspace_id": str(workspace_id),
        "user_id": str(user_id),
        "scope": "report_download",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=expires_in_seconds)).timestamp()),
    }
    if issuer:
        payload["iss"] = issuer
    if audience:
        payload["aud"] = audience
    return jwt.encode(payload, secret_key, algorithm="HS256")


def verify_report_download_token(
    token: str,
    secret_key: str,
    issuer: str | None = None,
    audience: str | None = None,
) -> dict[str, Any]:
    """Verify and decode a short-lived download token."""
    try:
        kwargs: dict[str, Any] = {"algorithms": ["HS256"]}
        if issuer:
            kwargs["issuer"] = issuer
        if audience:
            kwargs["audience"] = audience
        payload = jwt.decode(token, secret_key, **kwargs)
    except jwt.PyJWTError as err:
        raise ValueError(f"Invalid or expired download token: {err}") from err

    if payload.get("scope") != "report_download":
        raise ValueError("Invalid token scope.")

    return payload
