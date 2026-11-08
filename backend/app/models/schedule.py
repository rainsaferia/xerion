"""Canonical schedule domain models (WBS, calendars, activities, logic links, baselines)."""

import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, default_uuid
from app.models.project import JSONType


class WBSNode(Base):
    __tablename__ = "wbs_nodes"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=default_uuid
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    project_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("project_versions.id", ondelete="CASCADE"), nullable=False
    )
    source_wbs_id: Mapped[str | None] = mapped_column(String, nullable=True)
    wbs_code: Mapped[str | None] = mapped_column(String, nullable=True)
    wbs_name: Mapped[str] = mapped_column(String, nullable=False)
    parent_wbs_node_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("wbs_nodes.id", ondelete="SET NULL"), nullable=True
    )
    sort_order: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_fields: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False, default=dict)

    parent: Mapped["WBSNode | None"] = relationship("WBSNode", remote_side=[id], backref="children")

    __table_args__ = (
        UniqueConstraint("project_version_id", "source_wbs_id", name="uq_wbs_version_source_id"),
        Index("idx_wbs_version_parent", project_version_id, parent_wbs_node_id),
    )


class Calendar(Base):
    __tablename__ = "calendars"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=default_uuid
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    project_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("project_versions.id", ondelete="CASCADE"), nullable=False
    )
    source_calendar_id: Mapped[str | None] = mapped_column(String, nullable=True)
    calendar_name: Mapped[str] = mapped_column(String, nullable=False)
    calendar_type: Mapped[str | None] = mapped_column(String, nullable=True)
    timezone: Mapped[str | None] = mapped_column(String, nullable=True)
    calendar_definition: Mapped[dict[str, Any]] = mapped_column(
        JSONType, nullable=False, default=dict
    )
    fidelity_status: Mapped[str] = mapped_column(String, nullable=False, default="metadata_only")
    source_fields: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False, default=dict)

    __table_args__ = (
        CheckConstraint(
            "fidelity_status IN ('metadata_only', 'partially_parsed', 'fully_supported')",
            name="check_calendar_fidelity_status",
        ),
        UniqueConstraint(
            "project_version_id", "source_calendar_id", name="uq_calendars_version_source_id"
        ),
        Index("idx_calendars_version", project_version_id),
    )


class Activity(Base):
    __tablename__ = "activities"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=default_uuid
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    project_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("project_versions.id", ondelete="CASCADE"), nullable=False
    )
    source_activity_id: Mapped[str] = mapped_column(String, nullable=False)
    activity_code: Mapped[str | None] = mapped_column(String, nullable=True)
    activity_name: Mapped[str] = mapped_column(String, nullable=False)
    wbs_node_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("wbs_nodes.id", ondelete="SET NULL"), nullable=True
    )
    calendar_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("calendars.id", ondelete="SET NULL"), nullable=True
    )
    activity_type: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="unknown")
    source_status: Mapped[str | None] = mapped_column(String, nullable=True)
    planned_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    planned_finish: Mapped[date | None] = mapped_column(Date, nullable=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    finish_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    actual_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    actual_finish: Mapped[date | None] = mapped_column(Date, nullable=True)
    remaining_duration_hours: Mapped[float | None] = mapped_column(Numeric(16, 4), nullable=True)
    original_duration_hours: Mapped[float | None] = mapped_column(Numeric(16, 4), nullable=True)
    actual_duration_hours: Mapped[float | None] = mapped_column(Numeric(16, 4), nullable=True)
    total_float_hours: Mapped[float | None] = mapped_column(Numeric(16, 4), nullable=True)
    free_float_hours: Mapped[float | None] = mapped_column(Numeric(16, 4), nullable=True)
    physical_pct_complete: Mapped[float | None] = mapped_column(Numeric(7, 4), nullable=True)
    duration_pct_complete: Mapped[float | None] = mapped_column(Numeric(7, 4), nullable=True)
    units_pct_complete: Mapped[float | None] = mapped_column(Numeric(7, 4), nullable=True)
    percent_complete_type: Mapped[str | None] = mapped_column(String, nullable=True)
    source_fields: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    wbs_node: Mapped[WBSNode | None] = relationship("WBSNode")
    calendar: Mapped[Calendar | None] = relationship("Calendar")

    __table_args__ = (
        CheckConstraint(
            "status IN ('not_started', 'in_progress', 'complete', 'suspended', 'unknown')",
            name="check_activity_status",
        ),
        CheckConstraint(
            "physical_pct_complete IS NULL OR physical_pct_complete BETWEEN 0 AND 100",
            name="check_activity_physical_pct",
        ),
        CheckConstraint(
            "duration_pct_complete IS NULL OR duration_pct_complete BETWEEN 0 AND 100",
            name="check_activity_duration_pct",
        ),
        CheckConstraint(
            "units_pct_complete IS NULL OR units_pct_complete BETWEEN 0 AND 100",
            name="check_activity_units_pct",
        ),
        UniqueConstraint(
            "project_version_id", "source_activity_id", name="uq_activities_version_source_id"
        ),
        Index("idx_activities_version", project_version_id),
        Index("idx_activities_version_wbs", project_version_id, wbs_node_id),
        Index("idx_activities_version_code", project_version_id, activity_code),
        Index("idx_activities_version_float", project_version_id, total_float_hours),
        Index("idx_activities_version_dates", project_version_id, start_date, finish_date),
    )


class ActivityRelationship(Base):
    __tablename__ = "activity_relationships"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=default_uuid
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    project_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("project_versions.id", ondelete="CASCADE"), nullable=False
    )
    source_relationship_id: Mapped[str | None] = mapped_column(String, nullable=True)
    predecessor_activity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("activities.id", ondelete="CASCADE"), nullable=False
    )
    successor_activity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("activities.id", ondelete="CASCADE"), nullable=False
    )
    relationship_type: Mapped[str] = mapped_column(String, nullable=False)
    lag_hours: Mapped[float] = mapped_column(Numeric(16, 4), nullable=False, default=0.0)
    is_external: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source_fields: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False, default=dict)

    predecessor: Mapped[Activity] = relationship("Activity", foreign_keys=[predecessor_activity_id])
    successor: Mapped[Activity] = relationship("Activity", foreign_keys=[successor_activity_id])

    __table_args__ = (
        CheckConstraint(
            "predecessor_activity_id <> successor_activity_id",
            name="check_relationship_no_self_loop",
        ),
        Index("idx_relationships_version_pred", project_version_id, predecessor_activity_id),
        Index("idx_relationships_version_succ", project_version_id, successor_activity_id),
    )


class BaselineActivityValue(Base):
    __tablename__ = "baseline_activity_values"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=default_uuid
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    project_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("project_versions.id", ondelete="CASCADE"), nullable=False
    )
    baseline_source_id: Mapped[str | None] = mapped_column(String, nullable=True)
    source_activity_id: Mapped[str] = mapped_column(String, nullable=False)
    baseline_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    baseline_finish: Mapped[date | None] = mapped_column(Date, nullable=True)
    baseline_duration_hours: Mapped[float | None] = mapped_column(Numeric(16, 4), nullable=True)
    baseline_pct_complete: Mapped[float | None] = mapped_column(Numeric(7, 4), nullable=True)
    baseline_label: Mapped[str | None] = mapped_column(String, nullable=True)
    source_fields: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False, default=dict)

    __table_args__ = (
        UniqueConstraint(
            "project_version_id",
            "baseline_source_id",
            "source_activity_id",
            name="uq_baseline_version_source_activity",
        ),
        Index("idx_baseline_version_activity", project_version_id, source_activity_id),
    )
