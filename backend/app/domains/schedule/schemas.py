"""Canonical Pydantic models for normalized schedule objects (PI-021).

Rules (02_SYSTEM_ARCHITECTURE.md, 03_DATA_MODEL.md):
- Decouples schedule engine calculations from parser-specific structures.
- Retains source IDs and source field references.
- Safe enum handling: unknown statuses or types map to 'unknown' with warnings.
"""

import uuid
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ActivityStatus = Literal[
    "not_started",
    "in_progress",
    "complete",
    "suspended",
    "unknown",
]

RelationshipType = Literal[
    "FS",
    "SS",
    "FF",
    "SF",
    "unknown",
]


class NormalizationWarning(BaseModel):
    """Diagnostic warning emitted during canonical normalization."""

    model_config = ConfigDict(frozen=True)

    code: str
    message: str
    entity_type: Literal["project", "wbs", "calendar", "activity", "relationship", "baseline"]
    entity_source_id: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class CanonicalWBS(BaseModel):
    """Normalized Work Breakdown Structure node."""

    model_config = ConfigDict(frozen=True)

    source_id: str
    wbs_code: str | None = None
    wbs_name: str
    parent_source_id: str | None = None
    sort_order: int | None = None
    source_fields: dict[str, Any] = Field(default_factory=dict)


class CanonicalCalendar(BaseModel):
    """Normalized project work calendar."""

    model_config = ConfigDict(frozen=True)

    source_id: str
    calendar_name: str
    calendar_type: str | None = None
    timezone: str | None = None
    fidelity_status: Literal["metadata_only", "partially_parsed", "fully_supported"] = (
        "metadata_only"
    )
    source_fields: dict[str, Any] = Field(default_factory=dict)


class CanonicalActivity(BaseModel):
    """Normalized schedule activity/task."""

    model_config = ConfigDict(frozen=True)

    source_id: str
    activity_code: str | None = None
    activity_name: str
    wbs_source_id: str | None = None
    calendar_source_id: str | None = None
    status: ActivityStatus = "unknown"
    source_status: str | None = None
    planned_start: date | None = None
    planned_finish: date | None = None
    start_date: date | None = None
    finish_date: date | None = None
    actual_start: date | None = None
    actual_finish: date | None = None
    remaining_duration_hours: float | None = None
    original_duration_hours: float | None = None
    actual_duration_hours: float | None = None
    total_float_hours: float | None = None
    free_float_hours: float | None = None
    physical_pct_complete: float | None = Field(default=None, ge=0.0, le=100.0)
    duration_pct_complete: float | None = Field(default=None, ge=0.0, le=100.0)
    units_pct_complete: float | None = Field(default=None, ge=0.0, le=100.0)
    percent_complete_type: str | None = None
    source_fields: dict[str, Any] = Field(default_factory=dict)


class CanonicalRelationship(BaseModel):
    """Normalized activity dependency relationship."""

    model_config = ConfigDict(frozen=True)

    predecessor_source_id: str
    successor_source_id: str
    relationship_type: RelationshipType = "unknown"
    source_relationship_type: str | None = None
    source_id: str | None = None
    lag_hours: float = 0.0
    is_external: bool = False
    source_fields: dict[str, Any] = Field(default_factory=dict)


class CanonicalBaseline(BaseModel):
    """Normalized baseline activity values."""

    model_config = ConfigDict(frozen=True)

    source_activity_id: str
    baseline_source_id: str | None = None
    baseline_start: date | None = None
    baseline_finish: date | None = None
    baseline_duration_hours: float | None = None
    baseline_pct_complete: float | None = None
    baseline_label: str | None = None
    source_fields: dict[str, Any] = Field(default_factory=dict)


class CanonicalProjectSchedule(BaseModel):
    """Top-level normalized schedule bundle."""

    model_config = ConfigDict(frozen=True)

    source_format: str
    source_format_version: str | None = None
    source_project_key: str | None = None
    project_name: str | None = None
    data_date: date | None = None
    calendars: list[CanonicalCalendar] = Field(default_factory=list)
    wbs_nodes: list[CanonicalWBS] = Field(default_factory=list)
    activities: list[CanonicalActivity] = Field(default_factory=list)
    relationships: list[CanonicalRelationship] = Field(default_factory=list)
    baselines: list[CanonicalBaseline] = Field(default_factory=list)
    source_metadata: dict[str, Any] = Field(default_factory=dict)
    warnings: list[NormalizationWarning] = Field(default_factory=list)


class ActivityStatusDistribution(BaseModel):
    """Counts of activities across canonical status values."""

    model_config = ConfigDict(frozen=True)

    not_started: int = 0
    in_progress: int = 0
    complete: int = 0
    suspended: int = 0
    unknown: int = 0


class ProjectOverviewMetrics(BaseModel):
    """Deterministic schedule overview KPI metrics (PI-030).

    Rules:
    - Missing numerical/date fields (e.g., float, physical % complete) are None, not 0.0.
    """

    model_config = ConfigDict(frozen=True)

    project_id: uuid.UUID
    project_name: str
    version_id: uuid.UUID
    version_number: int
    version_label: str
    data_date: date | None = None
    project_start_date: date | None = None
    project_finish_date: date | None = None
    source_filename: str | None = None
    source_format: str | None = None
    total_activities: int
    status_distribution: ActivityStatusDistribution
    milestones_count: int
    critical_activities_count: int
    near_critical_activities_count: int
    min_total_float_hours: float | None = None
    max_total_float_hours: float | None = None
    avg_physical_pct_complete: float | None = None
    calendars_count: int
    wbs_nodes_count: int
    relationships_count: int
    warnings_count: int


class ActivityListItem(BaseModel):
    """Activity projection for table/grid explorer (PI-031)."""

    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    source_activity_id: str
    activity_code: str | None = None
    activity_name: str
    status: str
    activity_type: str | None = None
    wbs_node_id: uuid.UUID | None = None
    wbs_code: str | None = None
    wbs_name: str | None = None
    calendar_id: uuid.UUID | None = None
    calendar_name: str | None = None
    start_date: date | None = None
    finish_date: date | None = None
    planned_start: date | None = None
    planned_finish: date | None = None
    actual_start: date | None = None
    actual_finish: date | None = None
    remaining_duration_hours: float | None = None
    total_float_hours: float | None = None
    physical_pct_complete: float | None = None


class ActivityListResponse(BaseModel):
    """Server-side paginated list of activities (PI-031)."""

    model_config = ConfigDict(frozen=True)

    items: list[ActivityListItem]
    total: int
    limit: int
    offset: int


class RelationshipItem(BaseModel):
    """Resolved predecessor or successor activity relationship (PI-031)."""

    model_config = ConfigDict(frozen=True)

    relationship_id: uuid.UUID
    relationship_type: str
    lag_hours: float = 0.0
    is_external: bool = False
    activity_id: uuid.UUID
    activity_code: str | None = None
    activity_name: str
    status: str


class ActivityRelationshipsResponse(BaseModel):
    """Dependencies for a selected activity within the same version (PI-031)."""

    model_config = ConfigDict(frozen=True)

    activity_id: uuid.UUID
    predecessors: list[RelationshipItem] = Field(default_factory=list)
    successors: list[RelationshipItem] = Field(default_factory=list)


class ActivityDetail(ActivityListItem):
    """Detailed activity view with provenance and baselines (PI-031)."""

    source_status: str | None = None
    original_duration_hours: float | None = None
    actual_duration_hours: float | None = None
    free_float_hours: float | None = None
    duration_pct_complete: float | None = None
    units_pct_complete: float | None = None
    percent_complete_type: str | None = None
    source_fields: dict[str, Any] = Field(default_factory=dict)
    baselines: list[dict[str, Any]] = Field(default_factory=list)


class WBSNodeItem(BaseModel):
    """Work breakdown node with direct activity count (PI-031)."""

    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    source_wbs_id: str | None = None
    wbs_code: str | None = None
    wbs_name: str
    parent_wbs_node_id: uuid.UUID | None = None
    sort_order: int | None = None
    activity_count: int = 0


# ---------------------------------------------------------------------------
# Float & Critical Exposure Schemas (PI-032)
# ---------------------------------------------------------------------------

FloatBandName = Literal[
    "negative",
    "zero",
    "near_critical",
    "low_float",
    "high_float",
    "missing",
]


class FloatBandSummary(BaseModel):
    """Summary metrics for a total float duration band (PI-032)."""

    model_config = ConfigDict(frozen=True)

    name: FloatBandName
    label: str
    min_hours: float | None = None
    max_hours: float | None = None
    count: int = 0
    percentage: float = 0.0


class FloatDistributionResponse(BaseModel):
    """Deterministic float band histogram and provenance metadata (PI-032)."""

    model_config = ConfigDict(frozen=True)

    project_id: uuid.UUID
    version_id: uuid.UUID
    float_source: Literal["imported_source", "recalculated"] = "imported_source"
    method: str = "source_total_float_threshold"
    critical_threshold_hours: float = 0.0
    near_critical_threshold_hours: float = 80.0
    hours_per_day: float = 8.0
    total_activities: int
    activities_with_float: int
    activities_missing_float: int
    min_float_hours: float | None = None
    max_float_hours: float | None = None
    bands: list[FloatBandSummary]


class CriticalExposureItem(BaseModel):
    """Activity item classified into a critical/near-critical exposure band (PI-032)."""

    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    source_activity_id: str | None = None
    activity_code: str | None = None
    activity_name: str
    status: str
    total_float_hours: float | None = None
    total_float_days: float | None = None
    free_float_hours: float | None = None
    free_float_days: float | None = None
    start_date: date | None = None
    finish_date: date | None = None
    float_band: str
    is_critical: bool = False


class CriticalExposureResponse(BaseModel):
    """Filterable list of critical and near-critical exposed activities (PI-032)."""

    model_config = ConfigDict(frozen=True)

    project_id: uuid.UUID
    version_id: uuid.UUID
    float_source: Literal["imported_source", "recalculated"] = "imported_source"
    method: str = "source_total_float_threshold"
    critical_threshold_hours: float = 0.0
    near_critical_threshold_hours: float = 80.0
    hours_per_day: float = 8.0
    band: str | None = None
    total_exposed: int
    items: list[CriticalExposureItem]
    limit: int
    offset: int


# ---------------------------------------------------------------------------
# Schedule Quality Checks Schemas (PI-033)
# ---------------------------------------------------------------------------

QualityFindingCategory = Literal["data_quality", "schedule_performance"]
QualityFindingSeverity = Literal["info", "low", "medium", "high", "critical"]


class QualityFindingItem(BaseModel):
    """Normalized finding from schedule quality checks (PI-033)."""

    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    check_code: str
    category: QualityFindingCategory
    title: str
    severity: QualityFindingSeverity
    method: str
    limitation: str
    entity_type: str
    entity_id: uuid.UUID | None = None
    entity_source_id: str | None = None
    entity_code: str | None = None
    message: str
    evidence: list[dict[str, Any]] = Field(default_factory=list)


class QualityCheckSummary(BaseModel):
    """Aggregated summary of quality findings (PI-033)."""

    model_config = ConfigDict(frozen=True)

    total_findings: int
    data_quality_count: int
    schedule_performance_count: int
    by_severity: dict[str, int]
    checks_run: list[str]


class QualityCheckReport(BaseModel):
    """Schedule quality audit report for a project version (PI-033)."""

    model_config = ConfigDict(frozen=True)

    project_id: uuid.UUID
    version_id: uuid.UUID
    run_id: uuid.UUID | None = None
    data_date: date | None = None
    summary: QualityCheckSummary
    findings: list[QualityFindingItem]


class RunQualityChecksRequest(BaseModel):
    """Request payload to trigger schedule quality checks (PI-033)."""

    model_config = ConfigDict(frozen=True)

    version_id: uuid.UUID | None = None
    selected_checks: list[str] | None = None
    persist: bool = True


# ============================================================================
# PI-034: Version Comparison Schemas
# ============================================================================

DiffCategory = Literal[
    "added",
    "removed",
    "changed",
    "unchanged",
    "ambiguous",
]

RelationshipChangeType = Literal[
    "added",
    "removed",
    "modified",
]


class FieldDiff(BaseModel):
    """Detailed difference for a single field between two activity versions (PI-034)."""

    model_config = ConfigDict(frozen=True)

    field_name: str
    old_value: Any
    new_value: Any
    delta: Any | None = None


class RelationshipDiff(BaseModel):
    """Difference in predecessor/successor logic links (PI-034)."""

    model_config = ConfigDict(frozen=True)

    direction: Literal["predecessor", "successor"]
    relationship_type: str
    other_activity_code: str | None = None
    other_activity_name: str | None = None
    change_type: RelationshipChangeType
    old_lag_hours: float | None = None
    new_lag_hours: float | None = None


class ActivityDiffItem(BaseModel):
    """Comparison item for an activity between two schedule versions (PI-034)."""

    model_config = ConfigDict(frozen=True)

    diff_category: DiffCategory
    activity_code: str | None = None
    activity_name: str
    source_activity_id: str | None = None
    match_key: str
    from_activity_id: uuid.UUID | None = None
    to_activity_id: uuid.UUID | None = None
    field_changes: list[FieldDiff] = Field(default_factory=list)
    relationship_changes: list[RelationshipDiff] = Field(default_factory=list)
    ambiguous_reason: str | None = None


class ComparisonSummary(BaseModel):
    """High-level summary counts and reconciliation for version comparison (PI-034)."""

    model_config = ConfigDict(frozen=True)

    from_version_total: int
    to_version_total: int
    matched: int
    added: int
    removed: int
    changed: int
    unchanged: int
    ambiguous: int
    change_categories: dict[str, int] = Field(default_factory=dict)


class VersionComparisonReport(BaseModel):
    """Complete version comparison report (PI-034)."""

    model_config = ConfigDict(frozen=True)

    project_id: uuid.UUID
    from_version_id: uuid.UUID
    to_version_id: uuid.UUID
    from_version_number: int | None = None
    to_version_number: int | None = None
    from_data_date: date | None = None
    to_data_date: date | None = None
    summary: ComparisonSummary
    items: list[ActivityDiffItem]
    total_items: int
    limit: int = 100
    offset: int = 0


class CompareVersionsRequest(BaseModel):
    """Request payload to compare two project versions (PI-034)."""

    model_config = ConfigDict(frozen=True)

    from_version_id: uuid.UUID
    to_version_id: uuid.UUID
    fields: list[str] | None = None
    category_filter: DiffCategory | None = None
    limit: int = 100
    offset: int = 0


# ==============================================================================
# Milestone Forecast v1 (PI-044)
# ==============================================================================

ForecastMethod = Literal[
    "imported_schedule_dates",
    "deterministic_float_indicator",
]


class MilestoneForecastItem(BaseModel):
    """Forecast representation for an individual milestone activity (PI-044)."""

    model_config = ConfigDict(frozen=True)

    activity_id: uuid.UUID
    source_activity_id: str
    activity_code: str | None = None
    activity_name: str
    wbs_code: str | None = None
    wbs_name: str | None = None
    activity_type: str | None = None
    status: str
    source_date: date | None = None
    source_date_type: Literal["actual_finish", "finish_date", "planned_finish", "unavailable"]
    projected_date: date | None = None
    is_calculated_projection: bool
    variance_days: float | None = None
    total_float_hours: float | None = None
    total_float_days: float | None = None
    critical_status: Literal["critical", "near_critical", "non_critical", "unknown"]
    driving_notes: str | None = None
    warnings: list[str] = Field(default_factory=list)


class MilestoneForecastSummary(BaseModel):
    """High-level aggregate metrics for milestone forecast analysis (PI-044)."""

    model_config = ConfigDict(frozen=True)

    total_milestones: int
    completed_milestones: int
    in_progress_milestones: int
    not_started_milestones: int
    critical_milestones: int
    delayed_or_slipping_milestones: int


class MilestoneForecastResponse(BaseModel):
    """Structured response for milestone forecasting (PI-044)."""

    model_config = ConfigDict(frozen=True)

    project_id: uuid.UUID
    project_version_id: uuid.UUID
    data_date: date | None = None
    method: ForecastMethod
    method_description: str
    summary: MilestoneForecastSummary
    items: list[MilestoneForecastItem]
    limitations: list[str] = Field(default_factory=list)
    deterministic_disclaimer: str = (
        "Deterministic schedule projection only. No probabilistic Monte Carlo simulation "
        "or statistical confidence distribution is implied."
    )
    confidence_level: str | None = None


# ==============================================================================
# Delay Scenario v1 (PI-045)
# ==============================================================================

DelayUnit = Literal["working_days", "calendar_days", "hours"]
ImpactType = Literal[
    "primary_delay",
    "direct_successor_push",
    "float_consumption",
    "critical_milestone_slip",
]


class DelayScenarioRequest(BaseModel):
    """Request payload to simulate what-if activity delay (PI-045)."""

    model_config = ConfigDict(frozen=True)

    activity_source_id: str
    delay_value: float = Field(gt=0, description="Delay magnitude, must be positive.")
    delay_unit: DelayUnit = "working_days"
    version_id: uuid.UUID | None = None
    scenario_name: str = "Delay Simulation"
    hours_per_day: float = 8.0
    persist: bool = True


class AffectedScheduleItem(BaseModel):
    """Impact representation for an affected activity or milestone in scenario (PI-045)."""

    model_config = ConfigDict(frozen=True)

    activity_id: uuid.UUID
    source_activity_id: str
    activity_code: str | None = None
    activity_name: str
    wbs_code: str | None = None
    wbs_name: str | None = None
    is_milestone: bool
    is_target: bool
    impact_type: ImpactType
    source_start_date: date | None = None
    source_finish_date: date | None = None
    scenario_start_date: date | None = None
    scenario_finish_date: date | None = None
    delay_working_days: float
    delay_calendar_days: int
    original_total_float_hours: float | None = None
    scenario_remaining_total_float_hours: float | None = None
    notes: str


class DelayScenarioSummary(BaseModel):
    """Summary metrics of delay simulation (PI-045)."""

    model_config = ConfigDict(frozen=True)

    target_activity_id: uuid.UUID
    target_activity_code: str | None = None
    delay_applied_working_days: float
    delay_applied_hours: float
    delay_applied_calendar_days: int
    free_float_absorbed_hours: float
    total_float_absorbed_hours: float
    critical_path_breached: bool
    net_project_delay_working_days: float
    net_project_delay_calendar_days: int
    total_affected_activities: int
    total_affected_milestones: int


class DelayScenarioResponse(BaseModel):
    """Complete result of delay scenario simulation (PI-045)."""

    model_config = ConfigDict(frozen=True)

    scenario_id: uuid.UUID | None = None
    scenario_name: str
    project_id: uuid.UUID
    project_version_id: uuid.UUID
    status: Literal["completed", "insufficient_data"]
    summary: DelayScenarioSummary
    affected_items: list[AffectedScheduleItem]
    assumptions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    source_unaltered: bool = True
