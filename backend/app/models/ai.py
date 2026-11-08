"""AI orchestration persistence (conversations, messages, tool execution trace)."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, default_uuid
from app.models.project import JSONType


class AIConversation(Base, TimestampMixin):
    __tablename__ = "ai_conversations"

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
    created_by: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    selected_project_version_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("project_versions.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")

    messages: Mapped[list["AIMessage"]] = relationship(
        "AIMessage", back_populates="conversation", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("status IN ('active', 'archived')", name="check_ai_conversation_status"),
        Index("idx_ai_conversations_project", project_id, "updated_at"),
    )


class AIMessage(Base):
    __tablename__ = "ai_messages"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=default_uuid
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("ai_conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    project_version_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("project_versions.id"), nullable=True
    )
    role: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    structured_content: Mapped[dict[str, Any]] = mapped_column(
        JSONType, nullable=False, default=dict
    )
    provider: Mapped[str | None] = mapped_column(String, nullable=True)
    model: Mapped[str | None] = mapped_column(String, nullable=True)
    token_input: Mapped[int | None] = mapped_column(Integer, nullable=True)
    token_output: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    conversation: Mapped[AIConversation] = relationship("AIConversation", back_populates="messages")
    tool_executions: Mapped[list["AIToolExecution"]] = relationship(
        "AIToolExecution", back_populates="message", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            "role IN ('system', 'developer', 'user', 'assistant', 'tool')",
            name="check_ai_message_role",
        ),
        Index("idx_ai_messages_conversation", conversation_id, created_at),
    )


class AIToolExecution(Base):
    __tablename__ = "ai_tool_executions"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=default_uuid
    )
    message_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("ai_messages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    project_version_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("project_versions.id"), nullable=True
    )
    tool_name: Mapped[str] = mapped_column(String, nullable=False)
    arguments: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False, default=dict)
    output_summary: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False, default=dict)
    evidence_refs: Mapped[list[Any]] = mapped_column(JSONType, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String, nullable=False)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    message: Mapped[AIMessage] = relationship("AIMessage", back_populates="tool_executions")

    __table_args__ = (
        CheckConstraint(
            "status IN ('requested', 'completed', 'failed', 'rejected')",
            name="check_ai_tool_execution_status",
        ),
        Index("idx_ai_tool_exec_message", message_id),
    )
