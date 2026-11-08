"""Pydantic schemas and exceptions for the billing domain (PI-050)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PlanQuotasOut(BaseModel):
    """Quota limits serialized for API presentation."""

    model_config = ConfigDict(frozen=True)

    max_projects: int
    max_file_uploads_per_month: int
    max_imports_per_month: int
    max_ai_queries_per_month: int
    max_scenarios_per_month: int
    max_reports_per_month: int
    max_upload_size_bytes: int


class PlanInfo(BaseModel):
    """Public plan description and features."""

    model_config = ConfigDict(frozen=True)

    code: str
    name: str
    description: str
    monthly_price_usd: float
    quotas: PlanQuotasOut
    features: list[str] = Field(default_factory=list)


class UsageMetricSummary(BaseModel):
    """Aggregated usage metric for a specific capability in the current billing period."""

    model_config = ConfigDict(frozen=True)

    metric_name: str
    display_label: str
    used: float
    limit: float | None = None
    remaining: float | None = None
    unit: str
    percent_used: float | None = None


class UsageSummaryResponse(BaseModel):
    """Current billing period usage summary for an authenticated workspace."""

    model_config = ConfigDict(frozen=True)

    workspace_id: uuid.UUID
    plan_code: str
    plan_name: str
    billing_period_start: datetime
    billing_period_end: datetime
    reset_date: datetime
    metrics: list[UsageMetricSummary]


class PlanLimitExceededError(Exception):
    """Raised when a billable operation exceeds the workspace plan quota."""

    def __init__(
        self,
        metric_name: str,
        current_usage: float,
        limit: float,
        plan_code: str,
        message: str | None = None,
    ) -> None:
        self.metric_name = metric_name
        self.current_usage = current_usage
        self.limit = limit
        self.plan_code = plan_code
        self.message = (
            message
            or f"Plan limit exceeded for '{metric_name}': current usage {current_usage} "
            f"has reached the {plan_code.upper()} plan limit of {limit}. "
            f"Upgrade to a higher plan to continue."
        )
        super().__init__(self.message)
