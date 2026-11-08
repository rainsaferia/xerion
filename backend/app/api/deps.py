"""Authentication and tenant-guard dependencies.

Rule (06_API_SPEC.md): a client-supplied workspace_id/project_id is never sufficient
authorization. Access is always derived from the authenticated user's active membership.
Inaccessible and non-existent resources are indistinguishable (404) to avoid UUID probing.
"""

import uuid
from typing import Annotated

from fastapi import Depends, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import verify_access_token
from app.core.config import Settings, get_settings
from app.core.errors import ApiError
from app.db.session import get_session
from app.domains.workspaces.bootstrap import bootstrap_personal_workspace
from app.models.auth import User, Workspace, WorkspaceMember
from app.models.project import ImportJob, Project, UploadedFile
from app.models.reporting import Report

_bearer = HTTPBearer(auto_error=False)

SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


async def get_current_user(
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    token_query: Annotated[str | None, Query(alias="token")] = None,
) -> User:
    raw_token: str | None = None
    if credentials is not None:
        raw_token = credentials.credentials
    elif token_query is not None:
        raw_token = token_query
    else:
        raise ApiError(401, "UNAUTHENTICATED", "Authentication required.")

    identity = verify_access_token(raw_token, settings)
    if identity.scope == "report_download" and not request.url.path.startswith("/api/v1/reports/"):
        raise ApiError(403, "FORBIDDEN", "Download token cannot be used to access this resource.")
    user = (
        await session.execute(select(User).where(User.auth_subject == identity.subject))
    ).scalar_one_or_none()

    if user is not None and user.deleted_at is not None:
        raise ApiError(401, "UNAUTHENTICATED", "Account is deactivated.")

    if user is None:
        # Just-in-time bootstrap on first authenticated request (PI-010)
        derived_email = identity.email or f"{identity.subject}@users.projectintelligence.local"
        user, _ws, _member = await bootstrap_personal_workspace(
            session=session,
            auth_subject=identity.subject,
            email=derived_email,
            display_name=identity.display_name,
        )
        await session.commit()

    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def _not_found(what: str) -> ApiError:
    return ApiError(404, "NOT_FOUND", f"{what} not found.")


async def get_workspace_for_user(
    workspace_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> Workspace:
    workspace = (
        await session.execute(
            select(Workspace)
            .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
            .where(
                Workspace.id == workspace_id,
                Workspace.deleted_at.is_(None),
                WorkspaceMember.user_id == user.id,
                WorkspaceMember.status == "active",
            )
        )
    ).scalar_one_or_none()
    if workspace is None:
        raise _not_found("Workspace")
    return workspace


async def get_project_for_user(
    project_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> Project:
    project = (
        await session.execute(
            select(Project)
            .join(WorkspaceMember, WorkspaceMember.workspace_id == Project.workspace_id)
            .join(Workspace, Workspace.id == Project.workspace_id)
            .where(
                Project.id == project_id,
                Project.deleted_at.is_(None),
                Workspace.deleted_at.is_(None),
                WorkspaceMember.user_id == user.id,
                WorkspaceMember.status == "active",
            )
        )
    ).scalar_one_or_none()
    if project is None:
        raise _not_found("Project")
    return project


async def get_uploaded_file_for_user(
    file_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> UploadedFile:
    file = (
        await session.execute(
            select(UploadedFile)
            .join(WorkspaceMember, WorkspaceMember.workspace_id == UploadedFile.workspace_id)
            .join(Workspace, Workspace.id == UploadedFile.workspace_id)
            .where(
                UploadedFile.id == file_id,
                UploadedFile.deleted_at.is_(None),
                Workspace.deleted_at.is_(None),
                WorkspaceMember.user_id == user.id,
                WorkspaceMember.status == "active",
            )
        )
    ).scalar_one_or_none()
    if file is None:
        raise _not_found("File")
    return file


async def get_import_job_for_user(
    import_job_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> ImportJob:
    job = (
        await session.execute(
            select(ImportJob)
            .join(WorkspaceMember, WorkspaceMember.workspace_id == ImportJob.workspace_id)
            .join(Workspace, Workspace.id == ImportJob.workspace_id)
            .where(
                ImportJob.id == import_job_id,
                Workspace.deleted_at.is_(None),
                WorkspaceMember.user_id == user.id,
                WorkspaceMember.status == "active",
            )
        )
    ).scalar_one_or_none()
    if job is None:
        raise _not_found("Import job")
    return job


async def get_report_for_user(
    report_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> Report:
    report = (
        await session.execute(
            select(Report)
            .join(WorkspaceMember, WorkspaceMember.workspace_id == Report.workspace_id)
            .join(Workspace, Workspace.id == Report.workspace_id)
            .where(
                Report.id == report_id,
                Workspace.deleted_at.is_(None),
                WorkspaceMember.user_id == user.id,
                WorkspaceMember.status == "active",
            )
        )
    ).scalar_one_or_none()
    if report is None:
        raise _not_found("Report")
    return report


WorkspaceAccess = Annotated[Workspace, Depends(get_workspace_for_user)]
ProjectAccess = Annotated[Project, Depends(get_project_for_user)]
UploadedFileAccess = Annotated[UploadedFile, Depends(get_uploaded_file_for_user)]
ImportJobAccess = Annotated[ImportJob, Depends(get_import_job_for_user)]
ReportAccess = Annotated[Report, Depends(get_report_for_user)]
