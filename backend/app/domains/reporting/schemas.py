"""Pydantic schemas for the reporting domain (PI-046, PI-047)."""

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ReportType = Literal["schedule_analysis", "variance_comparison", "quality_audit", "activity_export"]
ReportOutputFormat = Literal["pdf", "xlsx", "csv", "docx"]
ReportStatus = Literal["queued", "generating", "ready", "failed"]


class ReportCreateRequest(BaseModel):
    """Payload to request generation of a project schedule report."""

    version_id: uuid.UUID
    report_type: ReportType = "schedule_analysis"
    format: ReportOutputFormat = "pdf"
    options: dict[str, Any] = Field(default_factory=dict)


class ActivityExportRow(BaseModel):
    """Normalized activity row for tabular export."""

    model_config = ConfigDict(from_attributes=True)

    source_activity_id: str
    activity_code: str | None = None
    activity_name: str
    wbs_code: str | None = None
    wbs_name: str | None = None
    status: str
    activity_type: str | None = None
    planned_start: date | None = None
    planned_finish: date | None = None
    actual_start: date | None = None
    actual_finish: date | None = None
    original_duration_hours: float | None = None
    remaining_duration_hours: float | None = None
    actual_duration_hours: float | None = None
    total_float_hours: float | None = None
    free_float_hours: float | None = None
    physical_pct_complete: float | None = None
    calendar_name: str | None = None


class ActivityExportRequest(BaseModel):
    """Payload to request an activity tabular export (PI-047)."""

    version_id: uuid.UUID
    format: Literal["csv", "xlsx"] = "csv"
    status: str | None = None
    wbs_code: str | None = None
    search: str | None = None
    critical_only: bool = False


class ReportResponse(BaseModel):
    """Serialized report metadata and state."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    project_version_id: uuid.UUID
    report_type: str
    title: str
    output_format: str
    status: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    completed_at: datetime | None = None
    download_url: str | None = None


class ReportDownloadUrlResponse(BaseModel):
    """Short-lived download URL response."""

    download_url: str
    expires_at: datetime
