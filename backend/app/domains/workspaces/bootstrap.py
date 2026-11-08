"""Personal workspace and user bootstrap domain logic.

Rules (02_SYSTEM_ARCHITECTURE.md & 08_DEVELOPMENT_BACKLOG.md PI-010):
- Pure domain logic. No framework dependencies (no FastAPI, Starlette).
- Signup/login maps auth subject to application user.
- Exactly one personal workspace is created idempotently.
- Workspace membership owner row is present.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import User, Workspace, WorkspaceMember


async def bootstrap_personal_workspace(
    session: AsyncSession,
    auth_subject: str,
    email: str,
    display_name: str | None = None,
    preferred_locale: str = "en",
    default_timezone: str = "Asia/Jakarta",
) -> tuple[User, Workspace, WorkspaceMember]:
    """Idempotently bootstrap an application user, personal workspace, and owner membership.

    Ensures that even under concurrent execution, exactly one user, exactly one
    personal workspace, and one owner membership record exist.
    """
    # 1. User resolution / creation
    user = (
        await session.execute(select(User).where(User.auth_subject == auth_subject))
    ).scalar_one_or_none()

    if user is None:
        user = User(
            id=uuid.uuid4(),
            auth_subject=auth_subject,
            email=email,
            display_name=display_name,
            preferred_locale=preferred_locale,
        )
        try:
            async with session.begin_nested():
                session.add(user)
                await session.flush()
        except IntegrityError:
            user = (
                await session.execute(select(User).where(User.auth_subject == auth_subject))
            ).scalar_one()
    else:
        # Existing user: update name or fallback email if real one now supplied
        if display_name and user.display_name != display_name:
            user.display_name = display_name
        if email and user.email != email and "@users.projectintelligence.local" in user.email:
            user.email = email

    # 2. Personal Workspace resolution / creation
    # Exactly one personal workspace per user
    workspace = (
        (
            await session.execute(
                select(Workspace).where(
                    Workspace.owner_user_id == user.id,
                    Workspace.workspace_type == "personal",
                    Workspace.deleted_at.is_(None),
                )
            )
        )
        .scalars()
        .first()
    )

    if workspace is None:
        ws_name = f"{user.display_name}'s Workspace" if user.display_name else "Personal Workspace"
        workspace = Workspace(
            id=uuid.uuid4(),
            name=ws_name,
            workspace_type="personal",
            owner_user_id=user.id,
            plan_code="free",
            timezone=default_timezone,
        )
        try:
            async with session.begin_nested():
                session.add(workspace)
                await session.flush()
        except IntegrityError:
            workspace = (
                (
                    await session.execute(
                        select(Workspace).where(
                            Workspace.owner_user_id == user.id,
                            Workspace.workspace_type == "personal",
                            Workspace.deleted_at.is_(None),
                        )
                    )
                )
                .scalars()
                .first()
            )
            if workspace is None:
                raise

    # 3. Workspace Member resolution / creation
    member = (
        await session.execute(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == workspace.id,
                WorkspaceMember.user_id == user.id,
            )
        )
    ).scalar_one_or_none()

    if member is None:
        member = WorkspaceMember(
            workspace_id=workspace.id,
            user_id=user.id,
            role="owner",
            status="active",
        )
        try:
            async with session.begin_nested():
                session.add(member)
                await session.flush()
        except IntegrityError:
            member = (
                await session.execute(
                    select(WorkspaceMember).where(
                        WorkspaceMember.workspace_id == workspace.id,
                        WorkspaceMember.user_id == user.id,
                    )
                )
            ).scalar_one()
    else:
        if member.role != "owner":
            member.role = "owner"
        if member.status != "active":
            member.status = "active"

    return user, workspace, member


async def get_personal_workspace(
    session: AsyncSession,
    user_id: uuid.UUID,
) -> Workspace | None:
    """Retrieve the active personal workspace owned by the user, if any."""
    return (
        (
            await session.execute(
                select(Workspace).where(
                    Workspace.owner_user_id == user_id,
                    Workspace.workspace_type == "personal",
                    Workspace.deleted_at.is_(None),
                )
            )
        )
        .scalars()
        .first()
    )
