"""SQLAlchemy declarative base and common column types/mixins."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy domain models."""

    type_annotation_map = {
        dict[str, Any]: Uuid,  # default placeholder if needed
    }


class TimestampMixin:
    """Standard audit timestamps in UTC."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )


def default_uuid() -> uuid.UUID:
    return uuid.uuid4()
