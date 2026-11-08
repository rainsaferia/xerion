"""Project, upload, import and version entities."""

import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.models.base import Base, TimestampMixin, default_uuid

# Use JSONB for Postgres and fallback to standard JSON for SQLite tests
JSONType = JSON().with_variant(JSONB, "postgresql")


class Project(Base, TimestampMixin):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=default_uuid
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    project_code: Mapped[str | None] = mapped_column(String, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    industry: Mapped[str] = mapped_column(String, nullable=False, default="EPC")
    client_name: Mapped[str | None] = mapped_column(String, nullable=True)
    contractor_name: Mapped[str | None] = mapped_column(String, nullable=True)
    currency_code: Mapped[str | None] = mapped_column(String(3), nullable=True)
    timezone: Mapped[str] = mapped_column(String, nullable=False, default="Asia/Jakarta")
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    latest_version_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("project_versions.id", use_alter=True, name="fk_projects_latest_version"),
        nullable=True,
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    workspace: Mapped["Workspace"] = relationship("Workspace", back_populates="projects")  # type: ignore[name-defined] # noqa: F821
    versions: Mapped[list["ProjectVersion"]] = relationship(
        "ProjectVersion",
        back_populates="project",
        cascade="all, delete-orphan",
        foreign_keys="ProjectVersion.project_id",
    )
    uploaded_files: Mapped[list["UploadedFile"]] = relationship(
        "UploadedFile", back_populates="project", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'on_hold', 'completed', 'archived')",
            name="check_project_status",
        ),
        Index("idx_projects_workspace", workspace_id, status),
    )


class UploadedFile(Base):
    __tablename__ = "uploaded_files"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=default_uuid
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    original_filename: Mapped[str] = mapped_column(String, nullable=False)
    object_key: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    content_type: Mapped[str | None] = mapped_column(String, nullable=True)
    source_format: Mapped[str] = mapped_column(String, nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_status: Mapped[str] = mapped_column(String, nullable=False, default="private")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    project: Mapped[Project] = relationship("Project", back_populates="uploaded_files")

    __table_args__ = (
        CheckConstraint(
            "source_format IN ('xer', 'xlsx', 'csv', 'xml', 'other')",
            name="check_uploaded_file_source_format",
        ),
        CheckConstraint("file_size_bytes >= 0", name="check_uploaded_file_size"),
        CheckConstraint(
            "storage_status IN ('private', 'quarantined', 'deleted')",
            name="check_uploaded_file_storage_status",
        ),
        UniqueConstraint(
            "workspace_id", "project_id", "sha256_checksum", name="uq_uploaded_files_checksum"
        ),
        Index("idx_uploaded_files_project", project_id, created_at.desc()),
    )


class ImportMapping(Base, TimestampMixin):
    __tablename__ = "import_mappings"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=default_uuid
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    dataset_type: Mapped[str] = mapped_column(String, nullable=False)
    mapping_config: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False, default=dict)
    mapping_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "dataset_type IN ('activity_progress', 'cost', 'risk', 'procurement', 'custom')",
            name="check_import_mapping_dataset_type",
        ),
        UniqueConstraint(
            "workspace_id",
            "name",
            "mapping_version",
            name="uq_import_mappings_workspace_name_version",
        ),
    )


class ImportJob(Base, TimestampMixin):
    __tablename__ = "import_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=default_uuid
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    uploaded_file_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("uploaded_files.id"), nullable=False
    )
    mapping_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("import_mappings.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(String, nullable=False, default="queued")
    parser_name: Mapped[str | None] = mapped_column(String, nullable=True)
    parser_version: Mapped[str | None] = mapped_column(String, nullable=True)
    progress_pct: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False, default=0.0)
    detected_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONType, nullable=False, default=dict
    )
    preview_summary: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False, default=dict)
    warnings: Mapped[list[Any]] = mapped_column(JSONType, nullable=False, default=list)
    errors: Mapped[list[Any]] = mapped_column(JSONType, nullable=False, default=list)
    idempotency_key: Mapped[str | None] = mapped_column(String, nullable=True)
    requested_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'processing', 'preview_ready', "
            "'confirmed', 'failed', 'cancelled')",
            name="check_import_job_status",
        ),
        CheckConstraint("progress_pct BETWEEN 0 AND 100", name="check_import_job_progress"),
        UniqueConstraint("workspace_id", "idempotency_key", name="uq_import_jobs_idempotency"),
        Index("idx_import_jobs_status", status, "created_at"),
    )


class ProjectVersion(Base):
    __tablename__ = "project_versions"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=default_uuid
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    import_job_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("import_jobs.id"), unique=True, nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    version_label: Mapped[str | None] = mapped_column(String, nullable=True)
    source_project_id: Mapped[str | None] = mapped_column(String, nullable=True)
    source_project_code: Mapped[str | None] = mapped_column(String, nullable=True)
    source_project_name: Mapped[str | None] = mapped_column(String, nullable=True)
    source_format: Mapped[str] = mapped_column(String, nullable=False)
    source_format_version: Mapped[str | None] = mapped_column(String, nullable=True)
    parser_version: Mapped[str | None] = mapped_column(String, nullable=True)
    data_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    project_start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    project_finish_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    source_metadata: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False, default=dict)
    quality_summary: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String, nullable=False, default="ready")
    confirmed_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    project: Mapped[Project] = relationship(
        "Project", back_populates="versions", foreign_keys=[project_id]
    )

    __table_args__ = (
        CheckConstraint("version_number > 0", name="check_project_version_number"),
        CheckConstraint(
            "status IN ('staging', 'ready', 'failed', 'superseded')",
            name="check_project_version_status",
        ),
        UniqueConstraint("project_id", "version_number", name="uq_project_versions_project_number"),
        Index("idx_project_versions_project", project_id, version_number.desc()),
    )
