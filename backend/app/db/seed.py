"""Development-only seed data for local testing and demonstration."""

import uuid

from sqlalchemy.orm import Session

from app.models.auth import User, Workspace, WorkspaceMember
from app.models.project import Project

DEMO_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
DEMO_WORKSPACE_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")
DEMO_PROJECT_ID = uuid.UUID("00000000-0000-0000-0000-000000000003")


def seed_development_data(session: Session) -> dict[str, uuid.UUID]:
    """Idempotently seed demo user, personal workspace, and sample project for local dev."""
    user = session.get(User, DEMO_USER_ID)
    if not user:
        user = User(
            id=DEMO_USER_ID,
            auth_subject="dev|demo-planner-01",
            email="planner.demo@projectintelligence.local",
            display_name="Demo Planner (EPC)",
            preferred_locale="en",
        )
        session.add(user)
        session.flush()

    workspace = session.get(Workspace, DEMO_WORKSPACE_ID)
    if not workspace:
        workspace = Workspace(
            id=DEMO_WORKSPACE_ID,
            name="Personal Workspace (Demo)",
            workspace_type="personal",
            owner_user_id=user.id,
            plan_code="pro",
            timezone="Asia/Jakarta",
        )
        session.add(workspace)
        session.flush()

    member = session.get(WorkspaceMember, (DEMO_WORKSPACE_ID, DEMO_USER_ID))
    if not member:
        member = WorkspaceMember(
            workspace_id=workspace.id,
            user_id=user.id,
            role="owner",
            status="active",
        )
        session.add(member)
        session.flush()

    project = session.get(Project, DEMO_PROJECT_ID)
    if not project:
        project = Project(
            id=DEMO_PROJECT_ID,
            workspace_id=workspace.id,
            name="Gas Processing Facility EPC Demo",
            project_code="GPF-001",
            description="Gas Processing Facility Expansion Project (Sprint 0 Baseline Demo)",
            industry="EPC",
            client_name="PT Nusantara Energi",
            contractor_name="Konsorsium Rekayasa Prima",
            currency_code="USD",
            timezone="Asia/Makassar",
            status="active",
            created_by=user.id,
        )
        session.add(project)
        session.flush()

    session.commit()
    return {
        "user_id": user.id,
        "workspace_id": workspace.id,
        "project_id": project.id,
    }
