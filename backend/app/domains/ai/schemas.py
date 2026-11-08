"""Schemas and contracts for AI domain orchestration and tools (PI-041).

Rules (02_SYSTEM_ARCHITECTURE.md, 05_AI_AGENT_SPEC.md):
- Decouples AI domain logic from HTTP routers and external LLM SDKs.
- Strictly validates tool parameters before schedule domain execution.
- Retains tool execution traces, summaries, and evidence references.
"""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# ============================================================================
# Tool Input Argument Schemas
# ============================================================================


class GetOverviewArgs(BaseModel):
    """Arguments for get_project_overview tool."""

    model_config = ConfigDict(extra="ignore")

    version_id: uuid.UUID | None = None


class ListActivitiesArgs(BaseModel):
    """Arguments for list_activities tool."""

    model_config = ConfigDict(extra="ignore")

    q: str | None = None
    status: str | None = None
    wbs_id: uuid.UUID | None = None
    float_max: float | None = None
    limit: int = Field(default=50, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class GetActivityDetailArgs(BaseModel):
    """Arguments for get_activity_detail tool."""

    model_config = ConfigDict(extra="ignore")

    activity_id: uuid.UUID | None = None
    activity_code: str | None = None
    source_activity_id: str | None = None


class GetRelationshipsArgs(BaseModel):
    """Arguments for get_activity_relationships tool."""

    model_config = ConfigDict(extra="ignore")

    activity_id: uuid.UUID | None = None
    activity_code: str | None = None
    source_activity_id: str | None = None


class GetCriticalActivitiesArgs(BaseModel):
    """Arguments for get_critical_activities tool."""

    model_config = ConfigDict(extra="ignore")

    float_threshold_hours: float = 0.0
    near_critical_threshold_hours: float = 80.0
    band: str | None = None
    limit: int = Field(default=50, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class GetFloatDistributionArgs(BaseModel):
    """Arguments for get_float_distribution tool."""

    model_config = ConfigDict(extra="ignore")

    critical_threshold_hours: float = 0.0
    near_critical_threshold_hours: float = 80.0


class AnalyzeQualityArgs(BaseModel):
    """Arguments for analyze_schedule_quality tool."""

    model_config = ConfigDict(extra="ignore")

    selected_checks: list[str] | None = None
    category: str | None = None


class CompareVersionsArgs(BaseModel):
    """Arguments for compare_project_versions tool."""

    model_config = ConfigDict(extra="ignore")

    from_version_id: uuid.UUID
    to_version_id: uuid.UUID
    category_filter: str | None = None
    limit: int = Field(default=100, ge=1, le=200)
    offset: int = Field(default=0, ge=0)


class GetMilestoneForecastArgs(BaseModel):
    """Arguments for get_milestone_forecast tool (PI-044)."""

    model_config = ConfigDict(extra="ignore")

    method: Literal[
        "imported_schedule_dates",
        "deterministic_float_indicator",
    ] = "imported_schedule_dates"
    milestone_id: str | None = None


class SimulateActivityDelayArgs(BaseModel):
    """Arguments for simulate_activity_delay tool (PI-045)."""

    model_config = ConfigDict(extra="ignore")

    activity_source_id: str
    delay_value: float = Field(gt=0, description="Delay magnitude, must be positive.")
    delay_unit: Literal["working_days", "calendar_days", "hours"] = "working_days"
    scenario_name: str = "Delay Simulation"


class GenerateScheduleReportArgs(BaseModel):
    """Arguments for generate_schedule_report tool (PI-046)."""

    model_config = ConfigDict(extra="ignore")

    format: Literal["pdf"] = "pdf"
    include_activity_appendix: bool = False


class ExportActivityDataArgs(BaseModel):
    """Arguments for export_activity_data tool (PI-047)."""

    model_config = ConfigDict(extra="ignore")

    format: Literal["csv", "xlsx"] = "csv"
    status: str | None = None
    wbs_code: str | None = None
    search: str | None = None
    critical_only: bool = False


# ============================================================================
# Tool Execution Result
# ============================================================================


class ToolExecutionResult(BaseModel):
    """Result returned by tool execution dispatcher."""

    model_config = ConfigDict(frozen=True)

    status: Literal["completed", "failed"]
    tool_name: str
    summary: dict[str, Any] = Field(default_factory=dict)
    data: Any = Field(default_factory=dict)
    evidence_refs: list[dict[str, Any]] = Field(default_factory=list)
    duration_ms: int = 0
    error: str | None = None


# ============================================================================
# Conversation & Message API Schemas
# ============================================================================


class CreateConversationRequest(BaseModel):
    """Payload to initiate a new AI conversation."""

    model_config = ConfigDict(frozen=True)

    title: str | None = None
    version_id: uuid.UUID | None = None


class SendMessageRequest(BaseModel):
    """Payload to send a message to the Project AI Assistant."""

    model_config = ConfigDict(frozen=True)

    message: str
    version_id: uuid.UUID | None = None


class ToolExecutionItem(BaseModel):
    """Tool execution audit item for UI display and history."""

    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: uuid.UUID
    tool_name: str
    arguments: dict[str, Any]
    output_summary: dict[str, Any]
    status: str
    duration_ms: int | None = None
    evidence_refs: list[dict[str, Any]] = Field(default_factory=list)


class MessageItem(BaseModel):
    """Single chat message in conversation history."""

    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: uuid.UUID
    role: str
    content: str | None = None
    tool_executions: list[ToolExecutionItem] = Field(default_factory=list)
    created_at: datetime


class ConversationResponse(BaseModel):
    """AI conversation metadata and message history."""

    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: uuid.UUID
    project_id: uuid.UUID
    title: str | None = None
    selected_project_version_id: uuid.UUID | None = None
    status: str
    messages: list[MessageItem] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class AgentTurnResponse(BaseModel):
    """Response returned upon completing an agent turn."""

    model_config = ConfigDict(frozen=True)

    conversation_id: uuid.UUID
    message: MessageItem
    tool_executions: list[ToolExecutionItem] = Field(default_factory=list)
    provider: str
    model: str
    validation_status: str = "verified"
    evidence_citations: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    tokens_used: int | None = None
    latency_ms: int | None = None
