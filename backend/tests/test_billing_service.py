"""Unit tests for billing domain service (PI-050)."""

import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any

import pytest
from app.domains.billing import (
    FREE_PLAN,
    PlanLimitExceededError,
    enforce_plan_limit,
    get_billing_period,
    get_workspace_usage_summary,
    record_usage_event,
)
from app.models.auth import User, Workspace, WorkspaceMember
from app.models.base import Base
from app.models.project import Project
from app.models.reporting import UsageEvent
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine.sync_engine, "connect")
    def _fk_on(dbapi_conn, _record) -> None:  # type: ignore[no-untyped-def]
        dbapi_conn.execute("PRAGMA foreign_keys = ON")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


@pytest.fixture
async def billing_test_data(session: AsyncSession) -> dict[str, Any]:
    user = User(
        auth_subject=f"sub_{uuid.uuid4().hex[:8]}",
        email=f"billing_user_{uuid.uuid4().hex[:6]}@example.com",
        display_name="Billing Tester",
    )
    session.add(user)
    await session.flush()

    workspace = Workspace(
        name="Billing Test Workspace",
        owner_user_id=user.id,
        plan_code="free",
    )
    session.add(workspace)
    await session.flush()

    member = WorkspaceMember(
        workspace_id=workspace.id,
        user_id=user.id,
        role="owner",
    )
    session.add(member)
    await session.commit()

    return {"user": user, "workspace": workspace}


def test_get_billing_period() -> None:
    fixed_date = datetime(2026, 6, 15, 12, 0, 0, tzinfo=UTC)
    start, end, reset = get_billing_period(fixed_date)

    assert start == datetime(2026, 6, 1, 0, 0, 0, tzinfo=UTC)
    assert end == datetime(2026, 6, 30, 23, 59, 59, 999999, tzinfo=UTC)
    assert reset == datetime(2026, 7, 1, 0, 0, 0, tzinfo=UTC)


async def test_record_usage_event(
    session: AsyncSession,
    billing_test_data: dict[str, Any],
) -> None:
    ws = billing_test_data["workspace"]
    user = billing_test_data["user"]

    event = await record_usage_event(
        session=session,
        workspace_id=ws.id,
        event_type="ai_query",
        quantity=1.0,
        unit="query",
        user_id=user.id,
        metadata={"tokens": 120},
    )

    assert event.id is not None
    assert event.event_type == "ai_query"
    assert event.quantity == 1.0

    # Query from db
    saved = (
        await session.execute(select(UsageEvent).where(UsageEvent.id == event.id))
    ).scalar_one()
    assert saved.workspace_id == ws.id
    assert saved.metadata_["tokens"] == 120


async def test_enforce_plan_limit_allows_then_blocks(
    session: AsyncSession,
    billing_test_data: dict[str, Any],
) -> None:
    ws = billing_test_data["workspace"]
    user = billing_test_data["user"]

    # Free plan allows 5 reports per month
    limit = FREE_PLAN.quotas.max_reports_per_month

    # Under limit: should pass cleanly
    await enforce_plan_limit(session, ws.id, "report_export", 1.0)

    # Record 5 reports
    for _ in range(limit):
        await record_usage_event(
            session=session,
            workspace_id=ws.id,
            user_id=user.id,
            event_type="report_export",
            quantity=1.0,
            unit="export",
        )

    # Now enforce again with 1.0 -> should raise PlanLimitExceededError
    with pytest.raises(PlanLimitExceededError) as exc_info:
        await enforce_plan_limit(session, ws.id, "report_export", 1.0)

    err = exc_info.value
    assert err.metric_name == "report_export"
    assert err.current_usage == float(limit)
    assert err.limit == float(limit)


async def test_enforce_active_projects_limit(
    session: AsyncSession,
    billing_test_data: dict[str, Any],
) -> None:
    ws = billing_test_data["workspace"]

    # Free plan allows 2 projects
    p1 = Project(workspace_id=ws.id, name="Project 1", status="active")
    p2 = Project(workspace_id=ws.id, name="Project 2", status="active")
    session.add_all([p1, p2])
    await session.commit()

    # Attempting to add 1 more active project should be blocked
    with pytest.raises(PlanLimitExceededError) as exc_info:
        await enforce_plan_limit(session, ws.id, "active_projects", 1.0)

    assert exc_info.value.metric_name == "active_projects"


async def test_get_workspace_usage_summary(
    session: AsyncSession,
    billing_test_data: dict[str, Any],
) -> None:
    ws = billing_test_data["workspace"]
    user = billing_test_data["user"]

    # Record some usage
    await record_usage_event(session, ws.id, "file_upload", 2.0, "upload", user.id)
    await record_usage_event(session, ws.id, "ai_query", 5.0, "query", user.id)

    summary = await get_workspace_usage_summary(session, ws.id)

    assert summary.workspace_id == ws.id
    assert summary.plan_code == "free"
    assert summary.plan_name == FREE_PLAN.name
    assert summary.billing_period_start is not None
    assert summary.reset_date is not None

    metrics_dict = {m.metric_name: m for m in summary.metrics}
    assert "file_upload" in metrics_dict
    assert metrics_dict["file_upload"].used == 2.0
    assert metrics_dict["file_upload"].limit == 10.0
    assert metrics_dict["file_upload"].remaining == 8.0
    assert metrics_dict["file_upload"].percent_used == 20.0

    assert "ai_query" in metrics_dict
    assert metrics_dict["ai_query"].used == 5.0
    assert metrics_dict["ai_query"].limit == 30.0
    assert metrics_dict["ai_query"].remaining == 25.0
