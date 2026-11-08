"""Initial baseline schema (PI-002)

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-11-03

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    json_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")

    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("auth_subject", sa.String(), nullable=False, unique=True),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=True),
        sa.Column("preferred_locale", sa.String(), nullable=False, server_default="en"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_users_email", "users", [sa.text("lower(email)")])

    op.create_table(
        "workspaces",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("workspace_type", sa.String(), nullable=False, server_default="personal"),
        sa.Column("owner_user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("plan_code", sa.String(), nullable=False, server_default="free"),
        sa.Column("timezone", sa.String(), nullable=False, server_default="Asia/Jakarta"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "workspace_type IN ('personal', 'team', 'organization')", name="check_workspace_type"
        ),
    )
    op.create_index("idx_workspaces_owner", "workspaces", ["owner_user_id"])

    op.create_table(
        "workspace_members",
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("role", sa.String(), nullable=False, server_default="owner"),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "role IN ('owner', 'admin', 'member', 'viewer')", name="check_workspace_member_role"
        ),
        sa.CheckConstraint(
            "status IN ('invited', 'active', 'suspended')", name="check_workspace_member_status"
        ),
    )
    op.create_index("idx_workspace_members_user", "workspace_members", ["user_id"])

    op.create_table(
        "projects",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("project_code", sa.String(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("industry", sa.String(), nullable=False, server_default="EPC"),
        sa.Column("client_name", sa.String(), nullable=True),
        sa.Column("contractor_name", sa.String(), nullable=True),
        sa.Column("currency_code", sa.String(length=3), nullable=True),
        sa.Column("timezone", sa.String(), nullable=False, server_default="Asia/Jakarta"),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("latest_version_id", sa.Uuid(), nullable=True),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('active', 'on_hold', 'completed', 'archived')", name="check_project_status"
        ),
    )
    op.create_index("idx_projects_workspace", "projects", ["workspace_id", "status"])
    op.create_index("idx_projects_created_by", "projects", ["created_by"])

    op.create_table(
        "uploaded_files",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("uploaded_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("original_filename", sa.String(), nullable=False),
        sa.Column("object_key", sa.String(), unique=True, nullable=False),
        sa.Column("content_type", sa.String(), nullable=True),
        sa.Column("source_format", sa.String(), nullable=False),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256_checksum", sa.String(length=64), nullable=False),
        sa.Column("storage_status", sa.String(), nullable=False, server_default="private"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "source_format IN ('xer', 'xlsx', 'csv', 'xml', 'other')",
            name="check_uploaded_file_source_format",
        ),
        sa.CheckConstraint("file_size_bytes >= 0", name="check_uploaded_file_size"),
        sa.CheckConstraint(
            "storage_status IN ('private', 'quarantined', 'deleted')",
            name="check_uploaded_file_storage_status",
        ),
        sa.UniqueConstraint(
            "workspace_id", "project_id", "sha256_checksum", name="uq_uploaded_files_checksum"
        ),
    )
    op.create_index("idx_uploaded_files_project", "uploaded_files", ["project_id", "created_at"])

    op.create_table(
        "import_mappings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("dataset_type", sa.String(), nullable=False),
        sa.Column("mapping_config", json_type, nullable=False),
        sa.Column("mapping_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "dataset_type IN ('activity_progress', 'cost', 'risk', 'procurement', 'custom')",
            name="check_import_mapping_dataset_type",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "name",
            "mapping_version",
            name="uq_import_mappings_workspace_name_version",
        ),
    )

    op.create_table(
        "import_jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "uploaded_file_id", sa.Uuid(), sa.ForeignKey("uploaded_files.id"), nullable=False
        ),
        sa.Column("mapping_id", sa.Uuid(), sa.ForeignKey("import_mappings.id"), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="queued"),
        sa.Column("parser_name", sa.String(), nullable=True),
        sa.Column("parser_version", sa.String(), nullable=True),
        sa.Column(
            "progress_pct", sa.Numeric(precision=5, scale=2), nullable=False, server_default="0"
        ),
        sa.Column("detected_metadata", json_type, nullable=False),
        sa.Column("preview_summary", json_type, nullable=False),
        sa.Column("warnings", json_type, nullable=False),
        sa.Column("errors", json_type, nullable=False),
        sa.Column("idempotency_key", sa.String(), nullable=True),
        sa.Column("requested_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'processing', 'preview_ready', 'confirmed', 'failed', 'cancelled')",
            name="check_import_job_status",
        ),
        sa.CheckConstraint("progress_pct BETWEEN 0 AND 100", name="check_import_job_progress"),
        sa.UniqueConstraint("workspace_id", "idempotency_key", name="uq_import_jobs_idempotency"),
    )
    op.create_index("idx_import_jobs_project", "import_jobs", ["project_id", "created_at"])
    op.create_index("idx_import_jobs_status", "import_jobs", ["status", "created_at"])

    op.create_table(
        "project_versions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "import_job_id", sa.Uuid(), sa.ForeignKey("import_jobs.id"), unique=True, nullable=False
        ),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("version_label", sa.String(), nullable=True),
        sa.Column("source_project_id", sa.String(), nullable=True),
        sa.Column("source_project_code", sa.String(), nullable=True),
        sa.Column("source_project_name", sa.String(), nullable=True),
        sa.Column("source_format", sa.String(), nullable=False),
        sa.Column("source_format_version", sa.String(), nullable=True),
        sa.Column("parser_version", sa.String(), nullable=True),
        sa.Column("data_date", sa.Date(), nullable=True),
        sa.Column("project_start_date", sa.Date(), nullable=True),
        sa.Column("project_finish_date", sa.Date(), nullable=True),
        sa.Column("source_metadata", json_type, nullable=False),
        sa.Column("quality_summary", json_type, nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="ready"),
        sa.Column("confirmed_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("version_number > 0", name="check_project_version_number"),
        sa.CheckConstraint(
            "status IN ('staging', 'ready', 'failed', 'superseded')",
            name="check_project_version_status",
        ),
        sa.UniqueConstraint(
            "project_id", "version_number", name="uq_project_versions_project_number"
        ),
    )
    op.create_index(
        "idx_project_versions_project", "project_versions", ["project_id", "version_number"]
    )

    # Deferred foreign key for latest_version_id
    op.create_foreign_key(
        "fk_projects_latest_version",
        "projects",
        "project_versions",
        ["latest_version_id"],
        ["id"],
    )

    op.create_table(
        "wbs_nodes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_version_id",
            sa.Uuid(),
            sa.ForeignKey("project_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_wbs_id", sa.String(), nullable=True),
        sa.Column("wbs_code", sa.String(), nullable=True),
        sa.Column("wbs_name", sa.String(), nullable=False),
        sa.Column(
            "parent_wbs_node_id",
            sa.Uuid(),
            sa.ForeignKey("wbs_nodes.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("sort_order", sa.Integer(), nullable=True),
        sa.Column("source_fields", json_type, nullable=False),
        sa.UniqueConstraint("project_version_id", "source_wbs_id", name="uq_wbs_version_source_id"),
    )
    op.create_index(
        "idx_wbs_version_parent", "wbs_nodes", ["project_version_id", "parent_wbs_node_id"]
    )

    op.create_table(
        "calendars",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_version_id",
            sa.Uuid(),
            sa.ForeignKey("project_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_calendar_id", sa.String(), nullable=True),
        sa.Column("calendar_name", sa.String(), nullable=False),
        sa.Column("calendar_type", sa.String(), nullable=True),
        sa.Column("timezone", sa.String(), nullable=True),
        sa.Column("calendar_definition", json_type, nullable=False),
        sa.Column("fidelity_status", sa.String(), nullable=False, server_default="metadata_only"),
        sa.Column("source_fields", json_type, nullable=False),
        sa.CheckConstraint(
            "fidelity_status IN ('metadata_only', 'partially_parsed', 'fully_supported')",
            name="check_calendar_fidelity_status",
        ),
        sa.UniqueConstraint(
            "project_version_id", "source_calendar_id", name="uq_calendars_version_source_id"
        ),
    )
    op.create_index("idx_calendars_version", "calendars", ["project_version_id"])

    op.create_table(
        "activities",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_version_id",
            sa.Uuid(),
            sa.ForeignKey("project_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_activity_id", sa.String(), nullable=False),
        sa.Column("activity_code", sa.String(), nullable=True),
        sa.Column("activity_name", sa.String(), nullable=False),
        sa.Column(
            "wbs_node_id",
            sa.Uuid(),
            sa.ForeignKey("wbs_nodes.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "calendar_id",
            sa.Uuid(),
            sa.ForeignKey("calendars.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("activity_type", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="unknown"),
        sa.Column("source_status", sa.String(), nullable=True),
        sa.Column("planned_start", sa.Date(), nullable=True),
        sa.Column("planned_finish", sa.Date(), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("finish_date", sa.Date(), nullable=True),
        sa.Column("actual_start", sa.Date(), nullable=True),
        sa.Column("actual_finish", sa.Date(), nullable=True),
        sa.Column("remaining_duration_hours", sa.Numeric(precision=16, scale=4), nullable=True),
        sa.Column("original_duration_hours", sa.Numeric(precision=16, scale=4), nullable=True),
        sa.Column("actual_duration_hours", sa.Numeric(precision=16, scale=4), nullable=True),
        sa.Column("total_float_hours", sa.Numeric(precision=16, scale=4), nullable=True),
        sa.Column("free_float_hours", sa.Numeric(precision=16, scale=4), nullable=True),
        sa.Column("physical_pct_complete", sa.Numeric(precision=7, scale=4), nullable=True),
        sa.Column("duration_pct_complete", sa.Numeric(precision=7, scale=4), nullable=True),
        sa.Column("units_pct_complete", sa.Numeric(precision=7, scale=4), nullable=True),
        sa.Column("percent_complete_type", sa.String(), nullable=True),
        sa.Column("source_fields", json_type, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "status IN ('not_started', 'in_progress', 'complete', 'suspended', 'unknown')",
            name="check_activity_status",
        ),
        sa.CheckConstraint(
            "physical_pct_complete IS NULL OR physical_pct_complete BETWEEN 0 AND 100",
            name="check_activity_physical_pct",
        ),
        sa.CheckConstraint(
            "duration_pct_complete IS NULL OR duration_pct_complete BETWEEN 0 AND 100",
            name="check_activity_duration_pct",
        ),
        sa.CheckConstraint(
            "units_pct_complete IS NULL OR units_pct_complete BETWEEN 0 AND 100",
            name="check_activity_units_pct",
        ),
        sa.UniqueConstraint(
            "project_version_id", "source_activity_id", name="uq_activities_version_source_id"
        ),
    )
    op.create_index("idx_activities_version", "activities", ["project_version_id"])
    op.create_index(
        "idx_activities_version_wbs", "activities", ["project_version_id", "wbs_node_id"]
    )
    op.create_index(
        "idx_activities_version_code", "activities", ["project_version_id", "activity_code"]
    )
    op.create_index(
        "idx_activities_version_float", "activities", ["project_version_id", "total_float_hours"]
    )
    op.create_index(
        "idx_activities_version_dates",
        "activities",
        ["project_version_id", "start_date", "finish_date"],
    )

    op.create_table(
        "activity_relationships",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_version_id",
            sa.Uuid(),
            sa.ForeignKey("project_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_relationship_id", sa.String(), nullable=True),
        sa.Column(
            "predecessor_activity_id",
            sa.Uuid(),
            sa.ForeignKey("activities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "successor_activity_id",
            sa.Uuid(),
            sa.ForeignKey("activities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("relationship_type", sa.String(), nullable=False),
        sa.Column(
            "lag_hours", sa.Numeric(precision=16, scale=4), nullable=False, server_default="0"
        ),
        sa.Column("is_external", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("source_fields", json_type, nullable=False),
        sa.CheckConstraint(
            "predecessor_activity_id <> successor_activity_id",
            name="check_relationship_no_self_loop",
        ),
    )
    op.create_index(
        "idx_relationships_version_pred",
        "activity_relationships",
        ["project_version_id", "predecessor_activity_id"],
    )
    op.create_index(
        "idx_relationships_version_succ",
        "activity_relationships",
        ["project_version_id", "successor_activity_id"],
    )

    op.create_table(
        "baseline_activity_values",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_version_id",
            sa.Uuid(),
            sa.ForeignKey("project_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("baseline_source_id", sa.String(), nullable=True),
        sa.Column("source_activity_id", sa.String(), nullable=False),
        sa.Column("baseline_start", sa.Date(), nullable=True),
        sa.Column("baseline_finish", sa.Date(), nullable=True),
        sa.Column("baseline_duration_hours", sa.Numeric(precision=16, scale=4), nullable=True),
        sa.Column("baseline_pct_complete", sa.Numeric(precision=7, scale=4), nullable=True),
        sa.Column("baseline_label", sa.String(), nullable=True),
        sa.Column("source_fields", json_type, nullable=False),
        sa.UniqueConstraint(
            "project_version_id",
            "baseline_source_id",
            "source_activity_id",
            name="uq_baseline_version_source_activity",
        ),
    )
    op.create_index(
        "idx_baseline_version_activity",
        "baseline_activity_values",
        ["project_version_id", "source_activity_id"],
    )

    op.create_table(
        "analysis_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_version_id",
            sa.Uuid(),
            sa.ForeignKey("project_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("analysis_type", sa.String(), nullable=False),
        sa.Column("engine_name", sa.String(), nullable=False),
        sa.Column("engine_version", sa.String(), nullable=False),
        sa.Column("method", sa.String(), nullable=False),
        sa.Column("parameters", json_type, nullable=False),
        sa.Column("result", json_type, nullable=False),
        sa.Column("warnings", json_type, nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="completed"),
        sa.Column("requested_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed')",
            name="check_analysis_run_status",
        ),
    )
    op.create_index(
        "idx_analysis_runs_project_version", "analysis_runs", ["project_version_id", "created_at"]
    )

    op.create_table(
        "analysis_findings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "analysis_run_id",
            sa.Uuid(),
            sa.ForeignKey("analysis_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_version_id",
            sa.Uuid(),
            sa.ForeignKey("project_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("finding_code", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("severity", sa.String(), nullable=False),
        sa.Column("entity_type", sa.String(), nullable=True),
        sa.Column("entity_source_id", sa.String(), nullable=True),
        sa.Column("evidence", json_type, nullable=False),
        sa.Column("recommendation", json_type, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "severity IN ('info', 'low', 'medium', 'high', 'critical')",
            name="check_analysis_finding_severity",
        ),
    )
    op.create_index(
        "idx_findings_version_severity", "analysis_findings", ["project_version_id", "severity"]
    )

    op.create_table(
        "ai_conversations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column(
            "selected_project_version_id",
            sa.Uuid(),
            sa.ForeignKey("project_versions.id"),
            nullable=True,
        ),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("status IN ('active', 'archived')", name="check_ai_conversation_status"),
    )
    op.create_index(
        "idx_ai_conversations_project", "ai_conversations", ["project_id", "updated_at"]
    )

    op.create_table(
        "ai_messages",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.Uuid(),
            sa.ForeignKey("ai_conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_version_id", sa.Uuid(), sa.ForeignKey("project_versions.id"), nullable=True
        ),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("structured_content", json_type, nullable=False),
        sa.Column("provider", sa.String(), nullable=True),
        sa.Column("model", sa.String(), nullable=True),
        sa.Column("token_input", sa.Integer(), nullable=True),
        sa.Column("token_output", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "role IN ('system', 'developer', 'user', 'assistant', 'tool')",
            name="check_ai_message_role",
        ),
    )
    op.create_index(
        "idx_ai_messages_conversation", "ai_messages", ["conversation_id", "created_at"]
    )

    op.create_table(
        "ai_tool_executions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "message_id",
            sa.Uuid(),
            sa.ForeignKey("ai_messages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_version_id", sa.Uuid(), sa.ForeignKey("project_versions.id"), nullable=True
        ),
        sa.Column("tool_name", sa.String(), nullable=False),
        sa.Column("arguments", json_type, nullable=False),
        sa.Column("output_summary", json_type, nullable=False),
        sa.Column("evidence_refs", json_type, nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "status IN ('requested', 'completed', 'failed', 'rejected')",
            name="check_ai_tool_execution_status",
        ),
    )
    op.create_index("idx_ai_tool_exec_message", "ai_tool_executions", ["message_id"])

    op.create_table(
        "reports",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_version_id",
            sa.Uuid(),
            sa.ForeignKey("project_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("report_type", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("output_format", sa.String(), nullable=False),
        sa.Column("object_key", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="queued"),
        sa.Column("parameters", json_type, nullable=False),
        sa.Column("generated_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "output_format IN ('pdf', 'xlsx', 'csv', 'docx')", name="check_report_output_format"
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'generating', 'ready', 'failed')", name="check_report_status"
        ),
    )
    op.create_index("idx_reports_project", "reports", ["project_id", "created_at"])

    op.create_table(
        "usage_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column(
            "quantity", sa.Numeric(precision=18, scale=4), nullable=False, server_default="1"
        ),
        sa.Column("unit", sa.String(), nullable=False, server_default="count"),
        sa.Column("estimated_cost_usd", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("metadata", json_type, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "event_type IN ('file_upload', 'file_import', 'analysis', 'ai_query', 'scenario', 'report_export')",
            name="check_usage_event_type",
        ),
    )
    op.create_index("idx_usage_workspace_time", "usage_events", ["workspace_id", "created_at"])


def downgrade() -> None:
    op.drop_table("usage_events")
    op.drop_table("reports")
    op.drop_table("ai_tool_executions")
    op.drop_table("ai_messages")
    op.drop_table("ai_conversations")
    op.drop_table("analysis_findings")
    op.drop_table("analysis_runs")
    op.drop_table("baseline_activity_values")
    op.drop_table("activity_relationships")
    op.drop_table("activities")
    op.drop_table("calendars")
    op.drop_table("wbs_nodes")
    op.drop_constraint("fk_projects_latest_version", "projects", type_="foreignkey")
    op.drop_table("project_versions")
    op.drop_table("import_jobs")
    op.drop_table("import_mappings")
    op.drop_table("uploaded_files")
    op.drop_table("projects")
    op.drop_table("workspace_members")
    op.drop_table("workspaces")
    op.drop_table("users")
