"""Database schema, models, foreign keys, constraints and seed tests."""

import uuid
from collections.abc import Generator

import pytest
from app.db.seed import DEMO_PROJECT_ID, DEMO_USER_ID, DEMO_WORKSPACE_ID, seed_development_data
from app.models.auth import User, Workspace
from app.models.base import Base
from app.models.project import ImportJob, Project, ProjectVersion, UploadedFile
from app.models.schedule import Activity, ActivityRelationship
from sqlalchemy import Engine, create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


@pytest.fixture
def sync_engine() -> Generator[Engine, None, None]:
    """In-memory SQLite engine for fast model and constraint testing."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    # Enable SQLite foreign key constraints
    with engine.connect() as conn:
        conn.exec_driver_sql("PRAGMA foreign_keys = ON")
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def db_session(sync_engine: Engine) -> Generator[Session, None, None]:
    with Session(sync_engine) as session:
        yield session


def test_models_metadata_contains_all_core_tables() -> None:
    expected_tables = {
        "users",
        "workspaces",
        "workspace_members",
        "projects",
        "uploaded_files",
        "import_mappings",
        "import_jobs",
        "project_versions",
        "wbs_nodes",
        "calendars",
        "activities",
        "activity_relationships",
        "baseline_activity_values",
        "analysis_runs",
        "analysis_findings",
        "ai_conversations",
        "ai_messages",
        "ai_tool_executions",
        "reports",
        "usage_events",
    }
    actual_tables = set(Base.metadata.tables.keys())
    assert expected_tables.issubset(actual_tables)


def test_seed_development_data_is_idempotent(db_session: Session) -> None:
    res1 = seed_development_data(db_session)
    assert res1["user_id"] == DEMO_USER_ID
    assert res1["workspace_id"] == DEMO_WORKSPACE_ID
    assert res1["project_id"] == DEMO_PROJECT_ID

    # Second run should succeed without IntegrityError or duplication
    res2 = seed_development_data(db_session)
    assert res2 == res1

    # Verify rows exist
    user = db_session.get(User, DEMO_USER_ID)
    assert user is not None
    assert user.email == "planner.demo@projectintelligence.local"

    ws = db_session.get(Workspace, DEMO_WORKSPACE_ID)
    assert ws is not None
    assert ws.name == "Personal Workspace (Demo)"

    project = db_session.get(Project, DEMO_PROJECT_ID)
    assert project is not None
    assert project.project_code == "GPF-001"


def test_user_unique_auth_subject(db_session: Session) -> None:
    u1 = User(
        id=uuid.uuid4(),
        auth_subject="auth0|123",
        email="u1@example.com",
    )
    db_session.add(u1)
    db_session.commit()

    u2 = User(
        id=uuid.uuid4(),
        auth_subject="auth0|123",  # duplicate auth_subject
        email="u2@example.com",
    )
    db_session.add(u2)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_workspace_cascade_deletes_projects(db_session: Session) -> None:
    seed_development_data(db_session)
    ws = db_session.get(Workspace, DEMO_WORKSPACE_ID)
    assert ws is not None

    # Deleting workspace should cascade delete project
    db_session.delete(ws)
    db_session.commit()

    assert db_session.get(Project, DEMO_PROJECT_ID) is None


def test_activity_unique_per_version(db_session: Session) -> None:
    seed_development_data(db_session)

    # Create dummy upload and import job
    up_file = UploadedFile(
        id=uuid.uuid4(),
        workspace_id=DEMO_WORKSPACE_ID,
        project_id=DEMO_PROJECT_ID,
        original_filename="schedule.xer",
        object_key="storage/1.xer",
        source_format="xer",
        file_size_bytes=1024,
        sha256_checksum="a" * 64,
    )
    db_session.add(up_file)
    db_session.flush()

    job = ImportJob(
        id=uuid.uuid4(),
        workspace_id=DEMO_WORKSPACE_ID,
        project_id=DEMO_PROJECT_ID,
        uploaded_file_id=up_file.id,
        status="confirmed",
    )
    db_session.add(job)
    db_session.flush()

    version = ProjectVersion(
        id=uuid.uuid4(),
        workspace_id=DEMO_WORKSPACE_ID,
        project_id=DEMO_PROJECT_ID,
        import_job_id=job.id,
        version_number=1,
        source_format="xer",
    )
    db_session.add(version)
    db_session.flush()

    act1 = Activity(
        id=uuid.uuid4(),
        workspace_id=DEMO_WORKSPACE_ID,
        project_id=DEMO_PROJECT_ID,
        project_version_id=version.id,
        source_activity_id="ACT-100",
        activity_code="A100",
        activity_name="Engineering Phase 1",
    )
    db_session.add(act1)
    db_session.commit()

    # Adding duplicate source_activity_id in same version must fail
    act2 = Activity(
        id=uuid.uuid4(),
        workspace_id=DEMO_WORKSPACE_ID,
        project_id=DEMO_PROJECT_ID,
        project_version_id=version.id,
        source_activity_id="ACT-100",
        activity_code="A100_DUP",
        activity_name="Duplicate Activity",
    )
    db_session.add(act2)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_activity_relationship_self_loop_rejected(db_session: Session) -> None:
    seed_development_data(db_session)

    up_file = UploadedFile(
        id=uuid.uuid4(),
        workspace_id=DEMO_WORKSPACE_ID,
        project_id=DEMO_PROJECT_ID,
        original_filename="schedule.xer",
        object_key="storage/2.xer",
        source_format="xer",
        file_size_bytes=2048,
        sha256_checksum="b" * 64,
    )
    db_session.add(up_file)
    db_session.flush()

    job = ImportJob(
        id=uuid.uuid4(),
        workspace_id=DEMO_WORKSPACE_ID,
        project_id=DEMO_PROJECT_ID,
        uploaded_file_id=up_file.id,
        status="confirmed",
    )
    db_session.add(job)
    db_session.flush()

    version = ProjectVersion(
        id=uuid.uuid4(),
        workspace_id=DEMO_WORKSPACE_ID,
        project_id=DEMO_PROJECT_ID,
        import_job_id=job.id,
        version_number=1,
        source_format="xer",
    )
    db_session.add(version)
    db_session.flush()

    act = Activity(
        id=uuid.uuid4(),
        workspace_id=DEMO_WORKSPACE_ID,
        project_id=DEMO_PROJECT_ID,
        project_version_id=version.id,
        source_activity_id="ACT-100",
        activity_name="Task A",
    )
    db_session.add(act)
    db_session.commit()

    rel = ActivityRelationship(
        id=uuid.uuid4(),
        workspace_id=DEMO_WORKSPACE_ID,
        project_id=DEMO_PROJECT_ID,
        project_version_id=version.id,
        predecessor_activity_id=act.id,
        successor_activity_id=act.id,  # Self loop!
        relationship_type="FS",
    )
    db_session.add(rel)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()
