"""Projects domain service.

Rules (02_SYSTEM_ARCHITECTURE.md, 03_DATA_MODEL.md, 08_DEVELOPMENT_BACKLOG.md PI-011):
- Pure domain logic. No framework dependencies (no FastAPI, Starlette).
- All project queries are tenant-scoped via workspace membership.
- User cannot read or modify another workspace/project.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.projects.validation import (
    validate_currency_code,
    validate_project_name,
    validate_timezone,
)
from app.models.auth import Workspace, WorkspaceMember
from app.models.project import Project


async def create_project(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    name: str,
    timezone: str = "Asia/Jakarta",
    project_code: str | None = None,
    description: str | None = None,
    industry: str = "EPC",
    client_name: str | None = None,
    contractor_name: str | None = None,
    currency_code: str | None = None,
) -> Project:
    """Create a project in the target workspace."""
    valid_name = validate_project_name(name)
    valid_tz = validate_timezone(timezone)
    valid_currency = validate_currency_code(currency_code)

    project = Project(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        name=valid_name,
        project_code=project_code.strip() if project_code else None,
        description=description.strip() if description else None,
        industry=industry.strip() if industry else "EPC",
        client_name=client_name.strip() if client_name else None,
        contractor_name=contractor_name.strip() if contractor_name else None,
        currency_code=valid_currency,
        timezone=valid_tz,
        status="active",
        created_by=user_id,
    )
    session.add(project)
    await session.flush()
    return project


async def list_projects_for_user(
    session: AsyncSession,
    user_id: uuid.UUID,
    workspace_id: uuid.UUID | None = None,
    include_archived: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> list[Project]:
    """List projects accessible to user via active workspace memberships."""
    stmt = (
        select(Project)
        .join(WorkspaceMember, WorkspaceMember.workspace_id == Project.workspace_id)
        .join(Workspace, Workspace.id == Project.workspace_id)
        .where(
            WorkspaceMember.user_id == user_id,
            WorkspaceMember.status == "active",
            Workspace.deleted_at.is_(None),
            Project.deleted_at.is_(None),
        )
    )

    if workspace_id is not None:
        stmt = stmt.where(Project.workspace_id == workspace_id)

    if not include_archived:
        stmt = stmt.where(Project.status != "archived")

    stmt = stmt.order_by(Project.created_at.desc()).limit(limit).offset(offset)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def update_project(
    session: AsyncSession,
    project: Project,
    name: str | None = None,
    timezone: str | None = None,
    project_code: str | None = None,
    description: str | None = None,
    industry: str | None = None,
    client_name: str | None = None,
    contractor_name: str | None = None,
    currency_code: str | None = None,
) -> Project:
    """Update mutable project attributes."""
    if name is not None:
        project.name = validate_project_name(name)
    if timezone is not None:
        project.timezone = validate_timezone(timezone)
    if currency_code is not None:
        project.currency_code = validate_currency_code(currency_code)
    if project_code is not None:
        project.project_code = project_code.strip() if project_code else None
    if description is not None:
        project.description = description.strip() if description else None
    if industry is not None:
        project.industry = industry.strip() if industry else "EPC"
    if client_name is not None:
        project.client_name = client_name.strip() if client_name else None
    if contractor_name is not None:
        project.contractor_name = contractor_name.strip() if contractor_name else None

    await session.flush()
    return project


async def archive_project(
    session: AsyncSession,
    project: Project,
) -> Project:
    """Archive a project."""
    project.status = "archived"
    project.archived_at = datetime.now(UTC)
    await session.flush()
    return project
