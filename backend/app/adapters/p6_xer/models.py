"""Canonical intermediate representations for parsed Primavera P6 schedules (PI-020).

These models decouple downstream schedule analytics from raw P6 XER table/column names.
Rules (02_SYSTEM_ARCHITECTURE.md Section 4 & 5, 03_DATA_MODEL.md):
- Keep raw source identifiers and lineage.
- Preserve source fields for diagnostic purposes.
- Retain unknown statuses or relationship types with warnings; never silently coerce.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class ParseWarning:
    """Non-blocking parser diagnostic warning."""

    code: str
    message: str
    table: str | None = None
    row_identifier: str | None = None


@dataclass(slots=True)
class ParsedCalendar:
    """Intermediate representation of a work calendar."""

    source_id: str
    name: str
    is_default: bool = False
    calendar_type: str | None = None
    source_fields: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ParsedWBS:
    """Intermediate representation of a Work Breakdown Structure (WBS) node."""

    source_id: str
    parent_source_id: str | None = None
    code: str | None = None
    name: str | None = None
    source_fields: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ParsedActivity:
    """Intermediate representation of a schedule activity/task."""

    source_id: str
    code: str
    name: str
    status: str  # "not_started" | "in_progress" | "completed" | raw string
    wbs_source_id: str | None = None
    calendar_source_id: str | None = None
    planned_start: datetime | None = None
    planned_finish: datetime | None = None
    actual_start: datetime | None = None
    actual_finish: datetime | None = None
    remaining_duration_hours: float | None = None
    original_duration_hours: float | None = None
    actual_duration_hours: float | None = None
    total_float_hours: float | None = None
    free_float_hours: float | None = None
    physical_pct_complete: float | None = None
    duration_pct_complete: float | None = None
    units_pct_complete: float | None = None
    percent_complete_type: str | None = None
    source_fields: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ParsedRelationship:
    """Intermediate representation of an activity dependency."""

    predecessor_source_id: str
    successor_source_id: str
    relationship_type: str  # "FS" | "SS" | "FF" | "SF" | raw string
    source_id: str | None = None
    lag_hours: float = 0.0
    is_external: bool = False
    source_fields: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ParsedBaselineActivity:
    """Intermediate representation of a baseline record."""

    activity_source_id: str
    baseline_type: str = "project"
    planned_start: datetime | None = None
    planned_finish: datetime | None = None
    duration_hours: float | None = None
    source_fields: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ParsedProjectBundle:
    """Source-independent intermediate bundle returned by the XER parser."""

    source_format: str = "xer"
    source_format_version: str | None = None
    source_project_key: str | None = None
    project_name: str | None = None
    data_date: datetime | None = None
    calendars: list[ParsedCalendar] = field(default_factory=list)
    wbs_nodes: list[ParsedWBS] = field(default_factory=list)
    activities: list[ParsedActivity] = field(default_factory=list)
    relationships: list[ParsedRelationship] = field(default_factory=list)
    baselines: list[ParsedBaselineActivity] = field(default_factory=list)
    source_metadata: dict[str, Any] = field(default_factory=dict)
    unknown_tables: dict[str, list[dict[str, str]]] = field(default_factory=dict)
    warnings: list[ParseWarning] = field(default_factory=list)
