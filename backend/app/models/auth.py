"""User and workspace identity models (multi-tenant boundary)."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, default_uuid


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=default_uuid
    )
    auth_subject: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    email: Mapped[str] = mapped_column(String, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String, nullable=True)
    preferred_locale: Mapped[str] = mapped_column(String, nullable=False, default="en")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    owned_workspaces: Mapped[list["Workspace"]] = relationship(
        "Workspace", back_populates="owner", foreign_keys="Workspace.owner_user_id"
    )
    memberships: Mapped[list["WorkspaceMember"]] = relationship(
        "WorkspaceMember", back_populates="user", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("idx_users_email", func.lower(email)),)


class Workspace(Base, TimestampMixin):
    __tablename__ = "workspaces"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=default_uuid
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    workspace_type: Mapped[str] = mapped_column(String, nullable=False, default="personal")
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    plan_code: Mapped[str] = mapped_column(String, nullable=False, default="free")
    timezone: Mapped[str] = mapped_column(String, nullable=False, default="Asia/Jakarta")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    owner: Mapped[User] = relationship(
        "User", back_populates="owned_workspaces", foreign_keys=[owner_user_id]
    )
    members: Mapped[list["WorkspaceMember"]] = relationship(
        "WorkspaceMember", back_populates="workspace", cascade="all, delete-orphan"
    )
    projects: Mapped[list["Project"]] = relationship(  # type: ignore[name-defined] # noqa: F821
        "Project", back_populates="workspace", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            "workspace_type IN ('personal', 'team', 'organization')",
            name="check_workspace_type",
        ),
    )


class WorkspaceMember(Base):
    __tablename__ = "workspace_members"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    role: Mapped[str] = mapped_column(String, nullable=False, default="owner")
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    workspace: Mapped[Workspace] = relationship("Workspace", back_populates="members")
    user: Mapped[User] = relationship("User", back_populates="memberships")

    __table_args__ = (
        CheckConstraint(
            "role IN ('owner', 'admin', 'member', 'viewer')",
            name="check_workspace_member_role",
        ),
        CheckConstraint(
            "status IN ('invited', 'active', 'suspended')",
            name="check_workspace_member_status",
        ),
    )
