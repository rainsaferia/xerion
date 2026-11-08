"""v1 identity and tenant-scoped routes."""

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.adapters.ai import get_ai_adapter
from app.adapters.p6_xer import parse_xer_bytes
from app.adapters.queue import get_queue_adapter
from app.adapters.storage import get_storage_adapter
from app.adapters.tabular import inspect_tabular_bytes, read_tabular_rows
from app.api.deps import (
    CurrentUser,
    ImportJobAccess,
    ProjectAccess,
    ReportAccess,
    SessionDep,
    SettingsDep,
    UploadedFileAccess,
    WorkspaceAccess,
    get_project_for_user,
    get_workspace_for_user,
)
from app.core.errors import ApiError
from app.domains.ai.orchestrator import (
    create_conversation,
    get_conversation,
    list_conversations,
    run_agent_turn,
)
from app.domains.ai.schemas import (
    AgentTurnResponse,
    ConversationResponse,
    CreateConversationRequest,
    SendMessageRequest,
)

# pyrefly: ignore[missing-import]
from app.domains.billing.plans import get_plan_definition, list_available_plans

# pyrefly: ignore[missing-import]
from app.domains.billing.schemas import (
    PlanInfo,
    PlanLimitExceededError,
    PlanQuotasOut,
    UsageSummaryResponse,
)

# pyrefly: ignore[missing-import]
from app.domains.billing.service import (
    enforce_plan_limit,
    get_workspace_usage_summary,
    record_usage_event,
)
from app.domains.ingestion.job_service import (
    confirm_import_job,
    create_import_job,
    retry_import_job,
)
from app.domains.ingestion.mapping import (
    ColumnMappingConfig,
    MappingValidationError,
    get_mapping_profile,
    list_mapping_profiles,
    save_mapping_profile,
    validate_and_normalize_tabular,
)
from app.domains.ingestion.normalization import normalize_schedule_bundle
from app.domains.ingestion.safety import (
    sanitize_upload_filename,
    validate_file_payload,
)
from app.domains.projects.service import (
    archive_project,
    create_project,
    list_projects_for_user,
    update_project,
)
from app.domains.projects.version_service import (
    create_version_from_confirmed_job,
    get_project_version_detail,
    list_project_versions,
)
from app.domains.reporting.schemas import (
    ActivityExportRequest,
    ReportCreateRequest,
    ReportDownloadUrlResponse,
    ReportResponse,
)
from app.domains.reporting.service import (
    create_report_download_token,
    # pyrefly: ignore[missing-module-attribute]
    generate_activity_export,
    generate_schedule_report,
    verify_report_download_token,
)
from app.domains.schedule.comparison import (
    compare_versions,
    export_comparison_csv,
)
from app.domains.schedule.explorer import (
    get_activity_detail,
    get_activity_relationships,
    get_wbs_tree,
    list_activities,
)
from app.domains.schedule.float_analysis import (
    compute_float_distribution,
    get_critical_exposure_activities,
)
from app.domains.schedule.forecast import compute_milestone_forecast
from app.domains.schedule.metrics import compute_project_overview_metrics
from app.domains.schedule.quality import run_schedule_quality_checks
from app.domains.schedule.scenario import simulate_activity_delay
from app.domains.schedule.schemas import (
    ActivityDetail,
    ActivityListResponse,
    ActivityRelationshipsResponse,
    CompareVersionsRequest,
    CriticalExposureResponse,
    DelayScenarioRequest,
    DelayScenarioResponse,
    DiffCategory,
    FloatDistributionResponse,
    ForecastMethod,
    MilestoneForecastResponse,
    ProjectOverviewMetrics,
    QualityCheckReport,
    RunQualityChecksRequest,
    VersionComparisonReport,
    WBSNodeItem,
)
from app.domains.workspaces.bootstrap import get_personal_workspace
from app.models.auth import Workspace, WorkspaceMember
from app.models.project import UploadedFile
from app.models.reporting import Report

router = APIRouter(prefix="/api/v1")


class MeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    display_name: str | None
    preferred_locale: str
    personal_workspace_id: uuid.UUID | None = None


class MeUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=255)
    preferred_locale: str | None = Field(default=None, max_length=10)


class WorkspaceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    workspace_type: str
    plan_code: str


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    timezone: str = Field(default="Asia/Jakarta", max_length=64)


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workspace_id: uuid.UUID
    name: str
    project_code: str | None = None
    description: str | None = None
    industry: str
    client_name: str | None = None
    contractor_name: str | None = None
    currency_code: str | None = None
    timezone: str
    status: str
    latest_version_id: uuid.UUID | None = None
    created_at: datetime
    archived_at: datetime | None = None


class ProjectCreate(BaseModel):
    workspace_id: uuid.UUID | None = None
    name: str = Field(min_length=1, max_length=255)
    project_code: str | None = Field(default=None, max_length=50)
    description: str | None = None
    industry: str = Field(default="EPC", max_length=100)
    client_name: str | None = Field(default=None, max_length=255)
    contractor_name: str | None = Field(default=None, max_length=255)
    currency_code: str | None = Field(default=None, max_length=3)
    timezone: str = Field(default="Asia/Jakarta", max_length=64)


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    project_code: str | None = Field(default=None, max_length=50)
    description: str | None = None
    industry: str | None = Field(default=None, max_length=100)
    client_name: str | None = Field(default=None, max_length=255)
    contractor_name: str | None = Field(default=None, max_length=255)
    currency_code: str | None = Field(default=None, max_length=3)
    timezone: str | None = Field(default=None, max_length=64)


class UploadSessionCreate(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    file_size_bytes: int | None = Field(default=None, gt=0)
    content_type: str | None = None


class UploadSessionOut(BaseModel):
    file_id: uuid.UUID
    project_id: uuid.UUID
    upload_method: str = "direct"
    upload_url: str
    expires_at: datetime
    required_headers: dict[str, str] = Field(default_factory=dict)
    max_size_bytes: int


class TabularInspectionOut(BaseModel):
    format: str
    sheet_names: list[str]
    active_sheet: str
    headers: list[str]
    sample_rows: list[dict[str, Any]]
    total_rows: int


class MappingProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workspace_id: uuid.UUID
    name: str
    dataset_type: str
    mapping_config: dict[str, Any]
    mapping_version: int


class MappingProfileCreateIn(BaseModel):
    name: str
    dataset_type: str = "activity_progress"
    mapping_config: dict[str, Any]


class ApplyMappingIn(BaseModel):
    mapping: ColumnMappingConfig | None = None
    mapping_profile_id: uuid.UUID | None = None
    save_profile_name: str | None = None


class UploadCompleteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workspace_id: uuid.UUID
    project_id: uuid.UUID
    original_filename: str
    source_format: str
    file_size_bytes: int
    sha256_checksum: str
    storage_status: str
    created_at: datetime
    import_job_id: uuid.UUID | None = None


class ProjectVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    version_number: int
    version_label: str | None = None
    data_date: date | None = None
    project_start_date: date | None = None
    project_finish_date: date | None = None
    source_filename: str
    source_format: str
    parser_version: str | None = None
    status: str
    activity_count: int
    created_at: datetime


class ProjectVersionDetailOut(ProjectVersionOut):
    source_format_version: str | None = None
    source_metadata: dict[str, Any] = Field(default_factory=dict)
    quality_summary: dict[str, Any] = Field(default_factory=dict)


class ImportJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workspace_id: uuid.UUID
    project_id: uuid.UUID
    uploaded_file_id: uuid.UUID
    status: str
    progress_pct: float
    detected_metadata: dict[str, Any]
    preview_summary: dict[str, Any]
    warnings: list[Any]
    errors: list[Any]
    started_at: datetime | None = None
    finished_at: datetime | None = None
    project_version_id: uuid.UUID | None = None


@router.get("/me", response_model=MeOut)
async def get_me(user: CurrentUser, session: SessionDep) -> MeOut:
    ws = await get_personal_workspace(session, user.id)
    return MeOut(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        preferred_locale=user.preferred_locale,
        personal_workspace_id=ws.id if ws else None,
    )


@router.patch("/me", response_model=MeOut)
async def update_me(update: MeUpdate, user: CurrentUser, session: SessionDep) -> MeOut:
    if update.display_name is not None:
        user.display_name = update.display_name
    if update.preferred_locale is not None:
        user.preferred_locale = update.preferred_locale
    await session.commit()
    ws = await get_personal_workspace(session, user.id)
    return MeOut(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        preferred_locale=user.preferred_locale,
        personal_workspace_id=ws.id if ws else None,
    )


@router.delete("/me")
async def delete_me(user: CurrentUser, session: SessionDep) -> dict[str, object]:
    """Self-serve account deactivation (PI-051).

    Marks user as deleted and deactivates all active workspace memberships.
    Subsequent authenticated requests from this identity fail closed with 401.
    """
    user.deleted_at = datetime.now(UTC)
    memberships = (
        (
            await session.execute(
                select(WorkspaceMember).where(
                    WorkspaceMember.user_id == user.id,
                    WorkspaceMember.status == "active",
                )
            )
        )
        .scalars()
        .all()
    )
    for m in memberships:
        m.status = "suspended"
    await session.commit()
    return {"status": "deactivated", "user_id": user.id}


@router.get("/workspaces", response_model=list[WorkspaceOut])
async def list_workspaces(user: CurrentUser, session: SessionDep) -> list[WorkspaceOut]:
    rows = (
        await session.execute(
            select(Workspace)
            .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
            .where(
                WorkspaceMember.user_id == user.id,
                WorkspaceMember.status == "active",
                Workspace.deleted_at.is_(None),
            )
            .order_by(Workspace.created_at)
        )
    ).scalars()
    return [
        WorkspaceOut(id=w.id, name=w.name, workspace_type=w.workspace_type, plan_code=w.plan_code)
        for w in rows
    ]


@router.post("/workspaces", response_model=WorkspaceOut, status_code=201)
async def create_workspace(
    data: WorkspaceCreate,
    user: CurrentUser,
    session: SessionDep,
) -> WorkspaceOut:
    ws = Workspace(
        id=uuid.uuid4(),
        name=data.name,
        workspace_type="team",
        owner_user_id=user.id,
        plan_code="free",
        timezone=data.timezone,
    )
    session.add(ws)
    await session.flush()
    member = WorkspaceMember(
        workspace_id=ws.id,
        user_id=user.id,
        role="owner",
        status="active",
    )
    session.add(member)
    await session.commit()
    return WorkspaceOut(
        id=ws.id,
        name=ws.name,
        workspace_type=ws.workspace_type,
        plan_code=ws.plan_code,
    )


@router.get("/workspaces/{workspace_id}", response_model=WorkspaceOut)
async def get_workspace(workspace: WorkspaceAccess) -> WorkspaceOut:
    return WorkspaceOut(
        id=workspace.id,
        name=workspace.name,
        workspace_type=workspace.workspace_type,
        plan_code=workspace.plan_code,
    )


# ============================================================================
# Plans & Usage (PI-050)
# ============================================================================


@router.get("/plans", response_model=list[PlanInfo])
async def get_plans(user: CurrentUser) -> list[PlanInfo]:
    """List available subscription plans, quotas, and feature tiers (PI-050)."""
    plans = list_available_plans()
    return [
        PlanInfo(
            code=p.code,
            name=p.name,
            description=p.description,
            monthly_price_usd=p.monthly_price_usd,
            quotas=PlanQuotasOut(
                max_projects=p.quotas.max_projects,
                max_file_uploads_per_month=p.quotas.max_file_uploads_per_month,
                max_imports_per_month=p.quotas.max_imports_per_month,
                max_ai_queries_per_month=p.quotas.max_ai_queries_per_month,
                max_scenarios_per_month=p.quotas.max_scenarios_per_month,
                max_reports_per_month=p.quotas.max_reports_per_month,
                max_upload_size_bytes=p.quotas.max_upload_size_bytes,
            ),
            features=p.features,
        )
        for p in plans
    ]


@router.get("/usage/summary", response_model=UsageSummaryResponse)
async def get_usage_summary_endpoint(
    user: CurrentUser,
    session: SessionDep,
    workspace_id: uuid.UUID | None = None,
) -> UsageSummaryResponse:
    """Retrieve active billing period usage summary and plan limits (PI-050)."""
    if workspace_id is not None:
        ws = await get_workspace_for_user(workspace_id, user, session)
    else:
        personal_ws = await get_personal_workspace(session, user.id)
        if not personal_ws:
            raise ApiError(404, "NOT_FOUND", "No active workspace found for user.")
        ws = personal_ws

    return await get_workspace_usage_summary(session, ws.id)


@router.get("/projects", response_model=list[ProjectOut])
async def list_projects(
    user: CurrentUser,
    session: SessionDep,
    workspace_id: uuid.UUID | None = None,
    include_archived: bool = False,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[ProjectOut]:
    if workspace_id is not None:
        # Validate that workspace exists and current user has active membership
        await get_workspace_for_user(workspace_id, user, session)
    projects = await list_projects_for_user(
        session=session,
        user_id=user.id,
        workspace_id=workspace_id,
        include_archived=include_archived,
        limit=limit,
        offset=offset,
    )
    return [ProjectOut.model_validate(p) for p in projects]


@router.post("/projects", response_model=ProjectOut, status_code=201)
async def create_new_project(
    data: ProjectCreate,
    user: CurrentUser,
    session: SessionDep,
) -> ProjectOut:
    if data.workspace_id is not None:
        ws = await get_workspace_for_user(data.workspace_id, user, session)
        target_ws_id = ws.id
    else:
        personal_ws = await get_personal_workspace(session, user.id)
        if not personal_ws:
            raise ApiError(400, "BAD_REQUEST", "Personal workspace not found.")
        target_ws_id = personal_ws.id

    try:
        await enforce_plan_limit(session, target_ws_id, "active_projects", 1.0)
    except PlanLimitExceededError as err:
        raise ApiError(403, "PLAN_LIMIT_EXCEEDED", err.message) from err

    try:
        project = await create_project(
            session=session,
            workspace_id=target_ws_id,
            user_id=user.id,
            name=data.name,
            timezone=data.timezone,
            project_code=data.project_code,
            description=data.description,
            industry=data.industry,
            client_name=data.client_name,
            contractor_name=data.contractor_name,
            currency_code=data.currency_code,
        )
        await session.commit()
    except ValueError as e:
        raise ApiError(422, "VALIDATION_ERROR", str(e)) from e

    return ProjectOut.model_validate(project)


@router.get("/projects/{project_id}", response_model=ProjectOut)
async def get_project(project: ProjectAccess) -> ProjectOut:
    return ProjectOut.model_validate(project)


@router.patch("/projects/{project_id}", response_model=ProjectOut)
async def update_project_profile(
    update: ProjectUpdate,
    project: ProjectAccess,
    session: SessionDep,
) -> ProjectOut:
    try:
        updated = await update_project(
            session=session,
            project=project,
            name=update.name,
            timezone=update.timezone,
            project_code=update.project_code,
            description=update.description,
            industry=update.industry,
            client_name=update.client_name,
            contractor_name=update.contractor_name,
            currency_code=update.currency_code,
        )
        await session.commit()
    except ValueError as e:
        raise ApiError(422, "VALIDATION_ERROR", str(e)) from e

    return ProjectOut.model_validate(updated)


@router.post("/projects/{project_id}/archive", response_model=ProjectOut)
async def archive_existing_project(
    project: ProjectAccess,
    session: SessionDep,
) -> ProjectOut:
    archived = await archive_project(session=session, project=project)
    await session.commit()
    return ProjectOut.model_validate(archived)


@router.delete("/projects/{project_id}")
async def delete_existing_project(
    project: ProjectAccess,
    session: SessionDep,
    settings: SettingsDep,
) -> dict[str, object]:
    """Delete a project with cascade cleanup (PI-051).

    Marks project.deleted_at, soft-deletes child uploaded files, and purges
    underlying file and report binaries from private storage.
    """
    now = datetime.now(UTC)
    project.deleted_at = now

    storage = get_storage_adapter(settings)

    # Cascade soft-delete files and delete storage objects
    files = (
        (
            await session.execute(
                select(UploadedFile).where(
                    UploadedFile.project_id == project.id,
                    UploadedFile.deleted_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    for f in files:
        f.deleted_at = now
        try:
            await storage.delete_object(f.object_key)
        except Exception:  # noqa: S110
            pass

    # Clean up any stored reports for this project
    reports = (
        (
            await session.execute(
                select(Report).where(
                    Report.project_id == project.id,
                    Report.object_key.is_not(None),
                )
            )
        )
        .scalars()
        .all()
    )
    for r in reports:
        if r.object_key:
            try:
                await storage.delete_object(r.object_key)
            except Exception:  # noqa: S110
                pass

    await session.commit()
    return {"status": "deleted", "project_id": project.id}


@router.post(
    "/projects/{project_id}/uploads",
    response_model=UploadSessionOut,
    status_code=201,
)
async def create_upload_session(
    data: UploadSessionCreate,
    project: ProjectAccess,
    user: CurrentUser,
    settings: SettingsDep,
) -> UploadSessionOut:
    try:
        clean_filename = sanitize_upload_filename(data.filename)
    except ValueError as e:
        raise ApiError(422, "VALIDATION_ERROR", str(e)) from e

    if data.file_size_bytes and data.file_size_bytes > settings.upload_max_size_bytes:
        raise ApiError(
            422,
            "VALIDATION_ERROR",
            f"File size exceeds maximum allowed limit ({settings.upload_max_size_bytes} bytes).",
        )

    file_id = uuid.uuid4()
    upload_url = (
        f"/api/v1/uploads/{file_id}/content?project_id={project.id}&filename={clean_filename}"
    )
    expires_at = datetime.now(UTC) + timedelta(minutes=30)

    return UploadSessionOut(
        file_id=file_id,
        project_id=project.id,
        upload_method="direct",
        upload_url=upload_url,
        expires_at=expires_at,
        max_size_bytes=settings.upload_max_size_bytes,
    )


@router.put("/uploads/{file_id}/content", response_model=UploadCompleteOut)
async def upload_file_content(
    file_id: uuid.UUID,
    project_id: uuid.UUID,
    filename: str,
    request: Request,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
) -> UploadCompleteOut:
    project = await get_project_for_user(project_id, user, session)
    body = await request.body()

    try:
        clean_name = sanitize_upload_filename(filename)
        source_format, size, checksum = validate_file_payload(
            body, clean_name, settings.upload_max_size_bytes
        )
    except ValueError as e:
        raise ApiError(422, "VALIDATION_ERROR", str(e)) from e

    # Enforce plan quota and upload file size limit (PI-050)
    ws = await session.get(Workspace, project.workspace_id)
    plan = get_plan_definition(ws.plan_code if ws else None)
    if size > plan.quotas.max_upload_size_bytes:
        raise ApiError(
            422,
            "VALIDATION_ERROR",
            f"File size ({size} bytes) exceeds {plan.name} plan limit "
            f"({plan.quotas.max_upload_size_bytes} bytes).",
        )
    try:
        await enforce_plan_limit(session, project.workspace_id, "file_upload", 1.0)
    except PlanLimitExceededError as err:
        raise ApiError(403, "PLAN_LIMIT_EXCEEDED", err.message) from err

    object_key = (
        f"workspaces/{project.workspace_id}/projects/{project.id}/uploads/{file_id}/{clean_name}"
    )

    storage = get_storage_adapter(settings)
    await storage.put_object(object_key, body)

    uploaded_file = UploadedFile(
        id=file_id,
        workspace_id=project.workspace_id,
        project_id=project.id,
        uploaded_by=user.id,
        original_filename=clean_name,
        object_key=object_key,
        content_type=request.headers.get("content-type"),
        source_format=source_format,
        file_size_bytes=size,
        sha256_checksum=checksum,
        storage_status="private",
    )
    session.add(uploaded_file)

    # Record file_upload usage event (PI-050)
    await record_usage_event(
        session=session,
        workspace_id=project.workspace_id,
        event_type="file_upload",
        quantity=1.0,
        unit="upload",
        user_id=user.id,
        project_id=project.id,
        metadata={
            "filename": clean_name,
            "file_size_bytes": size,
            "source_format": source_format,
        },
    )

    await session.commit()

    return UploadCompleteOut.model_validate(uploaded_file)


@router.post("/uploads/{file_id}/complete", response_model=UploadCompleteOut)
async def complete_file_upload(
    file: UploadedFileAccess,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
) -> UploadCompleteOut:
    storage = get_storage_adapter(settings)
    if not await storage.exists(file.object_key):
        raise ApiError(400, "BAD_REQUEST", "Uploaded content not found in storage.")

    # Create queued import job (PI-013)
    job = await create_import_job(session=session, uploaded_file=file, requested_by=user.id)
    queue = get_queue_adapter(settings)
    await queue.enqueue_import_job(job.id)
    await session.commit()

    out = UploadCompleteOut.model_validate(file)
    out.import_job_id = job.id
    return out


@router.get("/uploads/{file_id}", response_model=UploadCompleteOut)
async def get_upload_metadata(file: UploadedFileAccess) -> UploadCompleteOut:
    return UploadCompleteOut.model_validate(file)


@router.delete("/uploads/{file_id}")
async def delete_uploaded_file(
    file: UploadedFileAccess,
    session: SessionDep,
    settings: SettingsDep,
) -> dict[str, object]:
    file.deleted_at = datetime.now(UTC)
    storage = get_storage_adapter(settings)
    await storage.delete_object(file.object_key)
    await session.commit()
    return {"status": "deleted", "file_id": file.id}


@router.get("/imports/{import_job_id}", response_model=ImportJobOut)
async def get_import_job_status(job: ImportJobAccess) -> ImportJobOut:
    return ImportJobOut.model_validate(job)


@router.get("/imports/{import_job_id}/preview")
async def get_import_job_preview(job: ImportJobAccess) -> dict[str, Any]:
    return {
        "id": job.id,
        "status": job.status,
        "progress_pct": float(job.progress_pct),
        "detected_metadata": job.detected_metadata,
        "preview_summary": job.preview_summary,
        "warnings": job.warnings,
        "errors": job.errors,
    }


@router.post("/imports/{import_job_id}/retry", response_model=ImportJobOut)
async def retry_failed_import_job(
    job: ImportJobAccess,
    session: SessionDep,
    settings: SettingsDep,
) -> ImportJobOut:
    re_enqueued = retry_import_job(job)
    if re_enqueued:
        queue = get_queue_adapter(settings)
        await queue.enqueue_import_job(job.id)
    await session.commit()
    return ImportJobOut.model_validate(job)


@router.post("/imports/{import_job_id}/confirm", response_model=ImportJobOut)
async def confirm_import_job_endpoint(
    job: ImportJobAccess,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
) -> ImportJobOut:
    """Explicitly confirm an import job and materialize immutable project version (PI-014, PI-023).

    Rejects confirmation if the job has blocking errors or is not ready.
    Atomically creates next version number, persists schedule records, and updates
    project.latest_version_id.
    """
    confirmed, reason = confirm_import_job(job)
    if not confirmed:
        raise ApiError(400, "CANNOT_CONFIRM_IMPORT", reason or "Job cannot be confirmed.")

    # Enforce plan quota for imports (PI-050)
    try:
        await enforce_plan_limit(session, job.workspace_id, "file_import", 1.0)
    except PlanLimitExceededError as err:
        raise ApiError(403, "PLAN_LIMIT_EXCEEDED", err.message) from err

    uploaded_file = await session.get(UploadedFile, job.uploaded_file_id)
    if not uploaded_file:
        raise ApiError(404, "NOT_FOUND", "Associated uploaded file record not found.")

    storage = get_storage_adapter(settings)
    try:
        raw_data = await storage.get_object(uploaded_file.object_key)
    except FileNotFoundError:
        raise ApiError(404, "NOT_FOUND", "Uploaded storage object not found.") from None

    # Produce canonical schedule bundle
    if uploaded_file.source_format == "xer":
        bundle = parse_xer_bytes(raw_data)
        schedule = normalize_schedule_bundle(bundle)
    elif uploaded_file.source_format in ("csv", "xlsx"):
        raw_mapping = job.detected_metadata.get("mapping")
        if not raw_mapping:
            # Fallback mapping if not pre-configured
            raw_mapping = {"activity_code": "Code", "activity_name": "Name"}
        config = ColumnMappingConfig.model_validate(raw_mapping)
        rows = read_tabular_rows(
            data=raw_data,
            format_hint=uploaded_file.source_format,
            sheet_name=config.sheet_name,
        )
        schedule = validate_and_normalize_tabular(
            rows=rows,
            mapping=config,
            source_format=uploaded_file.source_format,
        )
    else:
        raise ApiError(
            400,
            "UNSUPPORTED_FORMAT",
            f"Cannot materialize schedule version for format '{uploaded_file.source_format}'.",
        )

    # Materialize version atomically
    version = await create_version_from_confirmed_job(
        session=session,
        job=job,
        schedule=schedule,
        user_id=user.id,
    )

    # Record file_import usage event (PI-050)
    await record_usage_event(
        session=session,
        workspace_id=job.workspace_id,
        event_type="file_import",
        quantity=1.0,
        unit="import",
        user_id=user.id,
        project_id=job.project_id,
        metadata={
            "project_version_id": str(version.id),
            "activity_count": len(schedule.activities),
            "source_format": uploaded_file.source_format,
        },
    )

    await session.commit()
    out = ImportJobOut.model_validate(job)
    out.project_version_id = version.id
    return out


@router.get("/projects/{project_id}/versions", response_model=list[ProjectVersionOut])
async def list_versions_for_project(
    project: ProjectAccess,
    session: SessionDep,
) -> list[ProjectVersionOut]:
    """List version history showing data date, source file, parser version (PI-023)."""
    versions = await list_project_versions(session, project.id)
    return [ProjectVersionOut.model_validate(v) for v in versions]


@router.post(
    "/projects/{project_id}/versions/compare",
    response_model=VersionComparisonReport,
)
async def compare_project_versions_post(
    project: ProjectAccess,
    session: SessionDep,
    payload: CompareVersionsRequest,
) -> VersionComparisonReport:
    """Compare two confirmed schedule versions via POST (PI-034)."""
    try:
        return await compare_versions(
            session=session,
            project_id=project.id,
            from_version_id=payload.from_version_id,
            to_version_id=payload.to_version_id,
            fields=payload.fields,
            category_filter=payload.category_filter,
            limit=payload.limit,
            offset=payload.offset,
        )
    except ValueError as exc:
        raise ApiError(404, "NOT_FOUND", str(exc)) from None


@router.get(
    "/projects/{project_id}/versions/compare/export",
)
async def export_project_version_comparison(
    project: ProjectAccess,
    session: SessionDep,
    from_version_id: uuid.UUID,
    to_version_id: uuid.UUID,
    category: DiffCategory | None = None,
) -> Response:
    """Export schedule version comparison report as RFC 4180 CSV (PI-034)."""
    try:
        report = await compare_versions(
            session=session,
            project_id=project.id,
            from_version_id=from_version_id,
            to_version_id=to_version_id,
            category_filter=category,
            limit=100000,
            offset=0,
        )
        csv_content = export_comparison_csv(report)
        filename = f"version_comparison_{str(from_version_id)[:8]}_{str(to_version_id)[:8]}.csv"
        return Response(
            content=csv_content,
            media_type="text/csv",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY",
                "Cache-Control": "private, no-store, max-age=0",
                "Pragma": "no-cache",
            },
        )
    except ValueError as exc:
        raise ApiError(404, "NOT_FOUND", str(exc)) from None


@router.get(
    "/projects/{project_id}/versions/compare",
    response_model=VersionComparisonReport,
)
async def compare_project_versions_get(
    project: ProjectAccess,
    session: SessionDep,
    from_version_id: uuid.UUID,
    to_version_id: uuid.UUID,
    category: DiffCategory | None = None,
    limit: int = 100,
    offset: int = 0,
) -> VersionComparisonReport:
    """Compare two confirmed schedule versions via GET (PI-034)."""
    try:
        return await compare_versions(
            session=session,
            project_id=project.id,
            from_version_id=from_version_id,
            to_version_id=to_version_id,
            category_filter=category,
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        raise ApiError(404, "NOT_FOUND", str(exc)) from None


@router.get(
    "/projects/{project_id}/versions/{version_id}",
    response_model=ProjectVersionDetailOut,
)
async def get_version_detail(
    project: ProjectAccess,
    version_id: uuid.UUID,
    session: SessionDep,
) -> ProjectVersionDetailOut:
    """Retrieve metadata and quality summary for a specific project version (PI-023)."""
    detail = await get_project_version_detail(session, project.id, version_id)
    if not detail:
        raise ApiError(404, "NOT_FOUND", "Project version not found.")
    return ProjectVersionDetailOut.model_validate(detail)


@router.get("/projects/{project_id}/overview", response_model=ProjectOverviewMetrics)
async def get_project_overview(
    project: ProjectAccess,
    session: SessionDep,
    version_id: uuid.UUID | None = None,
) -> ProjectOverviewMetrics:
    """Retrieve deterministic schedule overview KPI metrics (PI-030).

    Defaults to latest ready version if version_id is not specified.
    """
    try:
        return await compute_project_overview_metrics(
            session=session,
            project_id=project.id,
            version_id=version_id,
        )
    except ValueError as exc:
        msg = str(exc)
        if "no ready versions" in msg.lower():
            raise ApiError(404, "NO_VERSION_AVAILABLE", "Project has no ready versions.") from None
        if "not found" in msg.lower():
            raise ApiError(404, "NOT_FOUND", msg) from None
        raise ApiError(400, "BAD_REQUEST", msg) from None


@router.get("/projects/{project_id}/activities", response_model=ActivityListResponse)
async def list_project_activities(
    project: ProjectAccess,
    session: SessionDep,
    version_id: uuid.UUID | None = None,
    q: str | None = None,
    status: str | None = None,
    wbs_id: uuid.UUID | None = None,
    float_max: float | None = None,
    limit: int = 50,
    offset: int = 0,
) -> ActivityListResponse:
    """Server-side paginated activity list with search and filters (PI-031)."""
    try:
        return await list_activities(
            session=session,
            project_id=project.id,
            version_id=version_id,
            q=q,
            status=status,
            wbs_id=wbs_id,
            float_max=float_max,
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        msg = str(exc)
        if "no ready versions" in msg.lower():
            raise ApiError(404, "NO_VERSION_AVAILABLE", "Project has no ready versions.") from None
        if "not found" in msg.lower():
            raise ApiError(404, "NOT_FOUND", msg) from None
        raise ApiError(400, "BAD_REQUEST", msg) from None


@router.get("/projects/{project_id}/activities/{activity_id}", response_model=ActivityDetail)
async def get_project_activity_detail(
    project: ProjectAccess,
    activity_id: uuid.UUID,
    session: SessionDep,
    version_id: uuid.UUID | None = None,
) -> ActivityDetail:
    """Retrieve full activity detail with raw provenance and baselines (PI-031)."""
    try:
        detail = await get_activity_detail(
            session=session,
            project_id=project.id,
            activity_id=activity_id,
            version_id=version_id,
        )
        if not detail:
            raise ApiError(404, "NOT_FOUND", "Activity not found in this project version.")
        return detail
    except ValueError as exc:
        msg = str(exc)
        if "not found" in msg.lower():
            raise ApiError(404, "NOT_FOUND", msg) from None
        raise ApiError(400, "BAD_REQUEST", msg) from None


@router.get(
    "/projects/{project_id}/activities/{activity_id}/relationships",
    response_model=ActivityRelationshipsResponse,
)
async def get_project_activity_relationships(
    project: ProjectAccess,
    activity_id: uuid.UUID,
    session: SessionDep,
    version_id: uuid.UUID | None = None,
) -> ActivityRelationshipsResponse:
    """Retrieve predecessor and successor links resolved within same version (PI-031)."""
    try:
        rels = await get_activity_relationships(
            session=session,
            project_id=project.id,
            activity_id=activity_id,
            version_id=version_id,
        )
        if not rels:
            raise ApiError(404, "NOT_FOUND", "Activity not found in this project version.")
        return rels
    except ValueError as exc:
        msg = str(exc)
        if "not found" in msg.lower():
            raise ApiError(404, "NOT_FOUND", msg) from None
        raise ApiError(400, "BAD_REQUEST", msg) from None


@router.get("/projects/{project_id}/wbs", response_model=list[WBSNodeItem])
async def get_project_wbs_tree(
    project: ProjectAccess,
    session: SessionDep,
    version_id: uuid.UUID | None = None,
) -> list[WBSNodeItem]:
    """Retrieve WBS nodes with direct activity counts (PI-031)."""
    try:
        return await get_wbs_tree(
            session=session,
            project_id=project.id,
            version_id=version_id,
        )
    except ValueError as exc:
        msg = str(exc)
        if "not found" in msg.lower():
            raise ApiError(404, "NOT_FOUND", msg) from None
        raise ApiError(400, "BAD_REQUEST", msg) from None


@router.get(
    "/projects/{project_id}/schedule/float-distribution",
    response_model=FloatDistributionResponse,
)
async def get_project_float_distribution(
    project: ProjectAccess,
    session: SessionDep,
    version_id: uuid.UUID | None = None,
    critical_threshold_hours: float = 0.0,
    near_critical_threshold_hours: float = 80.0,
    hours_per_day: float = 8.0,
) -> FloatDistributionResponse:
    """Retrieve deterministic total float histogram and band distribution (PI-032)."""
    try:
        return await compute_float_distribution(
            session=session,
            project_id=project.id,
            version_id=version_id,
            critical_threshold_hours=critical_threshold_hours,
            near_critical_threshold_hours=near_critical_threshold_hours,
            hours_per_day=hours_per_day,
        )
    except ValueError as exc:
        msg = str(exc)
        if "no ready versions" in msg.lower():
            raise ApiError(404, "NO_VERSION_AVAILABLE", "Project has no ready versions.") from None
        if "not found" in msg.lower():
            raise ApiError(404, "NOT_FOUND", msg) from None
        raise ApiError(400, "BAD_REQUEST", msg) from None


@router.get(
    "/projects/{project_id}/schedule/critical-exposure",
    response_model=CriticalExposureResponse,
)
async def get_project_critical_exposure(
    project: ProjectAccess,
    session: SessionDep,
    version_id: uuid.UUID | None = None,
    band: str | None = None,
    critical_threshold_hours: float = 0.0,
    near_critical_threshold_hours: float = 80.0,
    hours_per_day: float = 8.0,
    limit: int = 50,
    offset: int = 0,
) -> CriticalExposureResponse:
    """Retrieve and paginate activities within critical/near-critical exposure bands (PI-032)."""
    try:
        return await get_critical_exposure_activities(
            session=session,
            project_id=project.id,
            version_id=version_id,
            band=band,
            critical_threshold_hours=critical_threshold_hours,
            near_critical_threshold_hours=near_critical_threshold_hours,
            hours_per_day=hours_per_day,
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        msg = str(exc)
        if "no ready versions" in msg.lower():
            raise ApiError(404, "NO_VERSION_AVAILABLE", "Project has no ready versions.") from None
        if "not found" in msg.lower():
            raise ApiError(404, "NOT_FOUND", msg) from None
        raise ApiError(400, "BAD_REQUEST", msg) from None


@router.post(
    "/projects/{project_id}/schedule/quality-checks",
    response_model=QualityCheckReport,
)
async def trigger_schedule_quality_checks(
    project: ProjectAccess,
    session: SessionDep,
    user: CurrentUser,
    payload: RunQualityChecksRequest | None = None,
) -> QualityCheckReport:
    """Run deterministic schedule quality audit against a confirmed project version (PI-033)."""
    target_version_id = payload.version_id if payload else None
    selected_checks = payload.selected_checks if payload else None
    persist = payload.persist if payload else True

    # Enforce plan quota for analysis (PI-050)
    try:
        await enforce_plan_limit(session, project.workspace_id, "analysis", 1.0)
    except PlanLimitExceededError as err:
        raise ApiError(403, "PLAN_LIMIT_EXCEEDED", err.message) from err

    try:
        report = await run_schedule_quality_checks(
            session=session,
            project_id=project.id,
            version_id=target_version_id,
            selected_checks=selected_checks,
            persist=persist,
            requested_by=user.id,
        )

        # Record analysis usage event (PI-050)
        await record_usage_event(
            session=session,
            workspace_id=project.workspace_id,
            event_type="analysis",
            quantity=1.0,
            unit="analysis",
            user_id=user.id,
            project_id=project.id,
            metadata={
                "run_id": str(report.run_id),
                "findings_count": len(report.findings),
            },
        )
        await session.commit()
        return report
    except ValueError as exc:
        msg = str(exc)
        if "no ready versions" in msg.lower():
            raise ApiError(404, "NO_VERSION_AVAILABLE", "Project has no ready versions.") from None
        if "not found" in msg.lower():
            raise ApiError(404, "NOT_FOUND", msg) from None
        raise ApiError(400, "BAD_REQUEST", msg) from None


@router.get(
    "/projects/{project_id}/schedule/quality-checks",
    response_model=QualityCheckReport,
)
async def get_schedule_quality_checks(
    project: ProjectAccess,
    session: SessionDep,
    version_id: uuid.UUID | None = None,
    category: str | None = None,
) -> QualityCheckReport:
    """Retrieve schedule quality audit report, optionally filtered by category (PI-033)."""
    try:
        report = await run_schedule_quality_checks(
            session=session,
            project_id=project.id,
            version_id=version_id,
            persist=False,
        )
        if category:
            filtered_findings = [f for f in report.findings if f.category == category]
            report = QualityCheckReport(
                project_id=report.project_id,
                version_id=report.version_id,
                run_id=report.run_id,
                data_date=report.data_date,
                summary=report.summary,
                findings=filtered_findings,
            )
        return report
    except ValueError as exc:
        msg = str(exc)
        if "no ready versions" in msg.lower():
            raise ApiError(404, "NO_VERSION_AVAILABLE", "Project has no ready versions.") from None
        if "not found" in msg.lower():
            raise ApiError(404, "NOT_FOUND", msg) from None
        raise ApiError(400, "BAD_REQUEST", msg) from None


@router.get(
    "/projects/{project_id}/schedule/forecast",
    response_model=MilestoneForecastResponse,
)
async def get_project_milestone_forecast(
    project: ProjectAccess,
    session: SessionDep,
    version_id: uuid.UUID | None = None,
    method: ForecastMethod = "imported_schedule_dates",
    milestone_id: str | None = None,
    hours_per_day: float = 8.0,
) -> MilestoneForecastResponse:
    """Retrieve deterministic milestone forecast with transparent methods (PI-044)."""
    try:
        return await compute_milestone_forecast(
            session=session,
            project_id=project.id,
            version_id=version_id,
            method=method,
            milestone_id=milestone_id,
            hours_per_day=hours_per_day,
        )
    except ValueError as exc:
        msg = str(exc)
        if "no ready versions" in msg.lower():
            raise ApiError(404, "NO_VERSION_AVAILABLE", "Project has no ready versions.") from None
        if "not found" in msg.lower():
            raise ApiError(404, "NOT_FOUND", msg) from None
        raise ApiError(400, "BAD_REQUEST", msg) from None


@router.post(
    "/projects/{project_id}/schedule/scenarios/delay",
    response_model=DelayScenarioResponse,
)
async def run_delay_scenario(
    project: ProjectAccess,
    session: SessionDep,
    user: CurrentUser,
    payload: DelayScenarioRequest,
) -> DelayScenarioResponse:
    """Simulate what-if activity delay with zero source row mutation (PI-045)."""
    # Enforce plan quota for scenarios (PI-050)
    try:
        await enforce_plan_limit(session, project.workspace_id, "scenario", 1.0)
    except PlanLimitExceededError as err:
        raise ApiError(403, "PLAN_LIMIT_EXCEEDED", err.message) from err

    try:
        scen = await simulate_activity_delay(
            session=session,
            project_id=project.id,
            activity_source_id=payload.activity_source_id,
            delay_value=payload.delay_value,
            delay_unit=payload.delay_unit,
            version_id=payload.version_id,
            scenario_name=payload.scenario_name,
            hours_per_day=payload.hours_per_day,
            persist=payload.persist,
            requested_by=user.id,
        )

        # Record scenario usage event (PI-050)
        await record_usage_event(
            session=session,
            workspace_id=project.workspace_id,
            event_type="scenario",
            quantity=1.0,
            unit="scenario",
            user_id=user.id,
            project_id=project.id,
            metadata={
                "activity_source_id": payload.activity_source_id,
                "delay_value": payload.delay_value,
                "delay_unit": payload.delay_unit,
            },
        )
        await session.commit()
        return scen
    except ValueError as exc:
        msg = str(exc)
        if "no ready versions" in msg.lower():
            raise ApiError(404, "NO_VERSION_AVAILABLE", "Project has no ready versions.") from None
        if "not found" in msg.lower():
            raise ApiError(404, "NOT_FOUND", msg) from None
        raise ApiError(400, "BAD_REQUEST", msg) from None


@router.post(
    "/projects/{project_id}/ai/conversations",
    response_model=ConversationResponse,
    status_code=201,
)
async def create_project_ai_conversation(
    project: ProjectAccess,
    session: SessionDep,
    user: CurrentUser,
    payload: CreateConversationRequest | None = None,
) -> ConversationResponse:
    """Create a new AI conversation scoped to a project (PI-041)."""
    title = payload.title if payload else None
    version_id = payload.version_id if payload else None
    return await create_conversation(
        session=session,
        workspace_id=project.workspace_id,
        project_id=project.id,
        user_id=user.id,
        title=title,
        version_id=version_id,
    )


@router.get(
    "/projects/{project_id}/ai/conversations",
    response_model=list[ConversationResponse],
)
async def list_project_ai_conversations(
    project: ProjectAccess,
    session: SessionDep,
    limit: int = 50,
    offset: int = 0,
) -> list[ConversationResponse]:
    """List AI conversations for a project (PI-041)."""
    return await list_conversations(
        session=session,
        project_id=project.id,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/projects/{project_id}/ai/conversations/{conversation_id}",
    response_model=ConversationResponse,
)
async def get_project_ai_conversation(
    project: ProjectAccess,
    conversation_id: uuid.UUID,
    session: SessionDep,
) -> ConversationResponse:
    """Retrieve full conversation details and message history (PI-041)."""
    try:
        return await get_conversation(
            session=session,
            project_id=project.id,
            conversation_id=conversation_id,
        )
    except ValueError as exc:
        raise ApiError(404, "NOT_FOUND", str(exc)) from None


@router.post(
    "/projects/{project_id}/ai/conversations/{conversation_id}/messages",
    response_model=AgentTurnResponse,
)
async def send_project_ai_message(
    project: ProjectAccess,
    conversation_id: uuid.UUID,
    payload: SendMessageRequest,
    session: SessionDep,
    user: CurrentUser,
    settings: SettingsDep,
) -> AgentTurnResponse:
    """Send user message, execute multi-turn tool calling, and return response (PI-041)."""
    # Enforce plan quota for AI queries (PI-050)
    try:
        await enforce_plan_limit(session, project.workspace_id, "ai_query", 1.0)
    except PlanLimitExceededError as err:
        raise ApiError(403, "PLAN_LIMIT_EXCEEDED", err.message) from err

    llm_client = get_ai_adapter(settings)
    storage = get_storage_adapter(settings)
    try:
        turn = await run_agent_turn(
            session=session,
            llm_client=llm_client,
            workspace_id=project.workspace_id,
            project_id=project.id,
            user_id=user.id,
            conversation_id=conversation_id,
            user_message_text=payload.message,
            target_version_id=payload.version_id,
            storage_put_fn=storage.put_object,
        )

        # Record ai_query usage event (PI-050)
        await record_usage_event(
            session=session,
            workspace_id=project.workspace_id,
            event_type="ai_query",
            quantity=1.0,
            unit="query",
            user_id=user.id,
            project_id=project.id,
            metadata={
                "conversation_id": str(conversation_id),
                "tokens_used": turn.tokens_used,
                "latency_ms": turn.latency_ms,
            },
        )
        await session.commit()
        return turn
    except ValueError as exc:
        raise ApiError(404, "NOT_FOUND", str(exc)) from None


@router.get("/workspaces/{workspace_id}/mappings", response_model=list[MappingProfileOut])
async def list_workspace_mapping_profiles(
    workspace: WorkspaceAccess,
    session: SessionDep,
) -> list[MappingProfileOut]:
    """List reusable tabular mapping profiles for a workspace (PI-022)."""
    profiles = await list_mapping_profiles(session, workspace.id)
    return [MappingProfileOut.model_validate(p) for p in profiles]


@router.post(
    "/workspaces/{workspace_id}/mappings",
    response_model=MappingProfileOut,
    status_code=201,
)
async def create_workspace_mapping_profile(
    workspace: WorkspaceAccess,
    data: MappingProfileCreateIn,
    user: CurrentUser,
    session: SessionDep,
) -> MappingProfileOut:
    """Create a reusable tabular mapping profile (PI-022)."""
    profile = await save_mapping_profile(
        session=session,
        workspace_id=workspace.id,
        name=data.name,
        mapping_config=data.mapping_config,
        dataset_type=data.dataset_type,
        created_by=user.id,
    )
    await session.commit()
    return MappingProfileOut.model_validate(profile)


@router.get("/imports/{import_job_id}/inspect", response_model=TabularInspectionOut)
async def inspect_import_file(
    job: ImportJobAccess,
    session: SessionDep,
    settings: SettingsDep,
    sheet: str | None = Query(None, description="Target sheet name for multi-sheet workbooks"),
) -> TabularInspectionOut:
    """Inspect tabular file to detect sheets, headers, sample rows, and total row count (PI-022)."""
    uploaded_file = await session.get(UploadedFile, job.uploaded_file_id)
    if not uploaded_file:
        raise ApiError(404, "NOT_FOUND", "Associated uploaded file record not found.")

    storage = get_storage_adapter(settings)
    try:
        data = await storage.get_object(uploaded_file.object_key)
    except FileNotFoundError:
        raise ApiError(404, "NOT_FOUND", "Uploaded storage object not found.") from None

    inspection = inspect_tabular_bytes(
        data=data,
        format_hint=uploaded_file.source_format,
        sheet_name=sheet,
    )

    return TabularInspectionOut(
        format=inspection.format,
        sheet_names=inspection.sheet_names,
        active_sheet=inspection.active_sheet,
        headers=inspection.headers,
        sample_rows=inspection.sample_rows,
        total_rows=inspection.total_rows,
    )


@router.post("/imports/{import_job_id}/mapping", response_model=ImportJobOut)
async def apply_import_mapping(
    job: ImportJobAccess,
    data: ApplyMappingIn,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
) -> ImportJobOut:
    """Apply mapping configuration to tabular file, validate rows, and prepare preview (PI-022)."""
    uploaded_file = await session.get(UploadedFile, job.uploaded_file_id)
    if not uploaded_file:
        raise ApiError(404, "NOT_FOUND", "Associated uploaded file record not found.")

    # 1. Resolve mapping configuration
    config: ColumnMappingConfig
    if data.mapping_profile_id:
        profile = await get_mapping_profile(session, job.workspace_id, data.mapping_profile_id)
        if not profile:
            raise ApiError(404, "NOT_FOUND", "Selected mapping profile not found.")
        job.mapping_id = profile.id
        config = ColumnMappingConfig.model_validate(profile.mapping_config)
    elif data.mapping:
        config = data.mapping
        if data.save_profile_name:
            saved_profile = await save_mapping_profile(
                session=session,
                workspace_id=job.workspace_id,
                name=data.save_profile_name,
                mapping_config=config.model_dump(),
                created_by=user.id,
            )
            job.mapping_id = saved_profile.id
    else:
        raise ApiError(
            400,
            "BAD_REQUEST",
            "Either mapping configuration or mapping_profile_id must be provided.",
        )

    # 2. Read rows from storage
    storage = get_storage_adapter(settings)
    try:
        raw_data = await storage.get_object(uploaded_file.object_key)
    except FileNotFoundError:
        raise ApiError(404, "NOT_FOUND", "Uploaded storage object not found.") from None

    rows = read_tabular_rows(
        data=raw_data,
        format_hint=uploaded_file.source_format,
        sheet_name=config.sheet_name,
    )

    # 3. Validate and normalize into canonical schedule
    try:
        schedule = validate_and_normalize_tabular(
            rows=rows,
            mapping=config,
            source_format=uploaded_file.source_format,
        )
    except MappingValidationError as exc:
        raise ApiError(400, "MAPPING_VALIDATION_ERROR", exc.message) from exc

    # 4. Update import job state
    job.detected_metadata = {
        "source_format": uploaded_file.source_format,
        "sheet_name": config.sheet_name,
        "mapping": config.model_dump(),
        "total_rows_read": len(rows),
    }
    job.preview_summary = {
        "activities": len(schedule.activities),
        "wbs_nodes": len(schedule.wbs_nodes),
        "relationships": len(schedule.relationships),
        "calendars": len(schedule.calendars),
    }
    job.warnings = [w.model_dump() for w in schedule.warnings]
    job.errors = []
    job.status = "preview_ready"
    job.progress_pct = 100.0
    job.finished_at = datetime.now(UTC)

    await session.commit()
    return ImportJobOut.model_validate(job)


# ============================================================================
# Reports & Exports (PI-046)
# ============================================================================


@router.post("/projects/{project_id}/reports", response_model=ReportResponse)
async def create_project_report(
    project: ProjectAccess,
    session: SessionDep,
    user: CurrentUser,
    settings: SettingsDep,
    payload: ReportCreateRequest,
) -> ReportResponse:
    """Generate a deterministic schedule report artifact (PI-046)."""
    # Enforce plan quota for reports (PI-050)
    try:
        await enforce_plan_limit(session, project.workspace_id, "report_export", 1.0)
    except PlanLimitExceededError as err:
        raise ApiError(403, "PLAN_LIMIT_EXCEEDED", err.message) from err

    storage = get_storage_adapter(settings)
    try:
        report = await generate_schedule_report(
            session=session,
            storage_put_fn=storage.put_object,
            project_id=project.id,
            version_id=payload.version_id,
            user_id=user.id,
            user_email=user.email,
            report_type=payload.report_type,
            output_format=payload.format,
            options=payload.options,
        )
        await session.commit()
        resp = ReportResponse.model_validate(report)
        if report.status == "ready":
            resp.download_url = f"/api/v1/reports/{report.id}/download"
        return resp
    except ValueError as e:
        await session.rollback()
        raise ApiError(status_code=400, code="BAD_REQUEST", message=str(e)) from e


@router.post("/projects/{project_id}/exports/activities", response_model=ReportResponse)
async def create_activity_export(
    project: ProjectAccess,
    session: SessionDep,
    user: CurrentUser,
    settings: SettingsDep,
    payload: ActivityExportRequest,
) -> ReportResponse:
    """Create CSV or XLSX export for schedule activities (PI-047)."""
    # Enforce plan quota for exports (PI-050)
    try:
        await enforce_plan_limit(session, project.workspace_id, "report_export", 1.0)
    except PlanLimitExceededError as err:
        raise ApiError(403, "PLAN_LIMIT_EXCEEDED", err.message) from err

    storage = get_storage_adapter(settings)
    try:
        report = await generate_activity_export(
            session=session,
            storage_put_fn=storage.put_object,
            project_id=project.id,
            version_id=payload.version_id,
            user_id=user.id,
            output_format=payload.format,
            status_filter=payload.status,
            wbs_code_filter=payload.wbs_code,
            search_query=payload.search,
            critical_only=payload.critical_only,
        )
        await session.commit()
        resp = ReportResponse.model_validate(report)
        if report.status == "ready":
            resp.download_url = f"/api/v1/reports/{report.id}/download"
        return resp
    except ValueError as e:
        await session.rollback()
        raise ApiError(status_code=400, code="BAD_REQUEST", message=str(e)) from e


@router.get("/reports/{report_id}", response_model=ReportResponse)
async def get_report_metadata(
    report: ReportAccess,
) -> ReportResponse:
    """Retrieve report status and metadata (PI-046)."""
    resp = ReportResponse.model_validate(report)
    if report.status == "ready":
        resp.download_url = f"/api/v1/reports/{report.id}/download"
    return resp


@router.get("/reports/{report_id}/download", response_model=ReportDownloadUrlResponse)
async def get_report_download_url(
    report: ReportAccess,
    user: CurrentUser,
    settings: SettingsDep,
) -> ReportDownloadUrlResponse:
    """Generate short-lived signed download URL (PI-046)."""
    if report.status != "ready" or not report.object_key:
        raise ApiError(
            status_code=400,
            code="REPORT_NOT_READY",
            message="Report is not ready for download.",
        )
    secret = (
        settings.auth_jwt_secret.get_secret_value()
        if settings.auth_jwt_secret
        else "epc-fallback-secret-development-key-32b"
    )
    token = create_report_download_token(
        report_id=report.id,
        project_id=report.project_id,
        workspace_id=report.workspace_id,
        user_id=user.id,
        auth_subject=user.auth_subject,
        secret_key=secret,
        expires_in_seconds=900,
        issuer=settings.auth_jwt_issuer,
        audience=settings.auth_jwt_audience,
    )
    expires_at = datetime.now(UTC) + timedelta(seconds=900)
    download_url = f"/api/v1/reports/{report.id}/content?token={token}"
    return ReportDownloadUrlResponse(download_url=download_url, expires_at=expires_at)


@router.get("/reports/{report_id}/content")
async def get_report_content(
    report: ReportAccess,
    settings: SettingsDep,
    token: str | None = Query(None),
) -> Response:
    """Stream private report binary content via short-lived token or Bearer auth (PI-046)."""
    if token:
        secret = (
            settings.auth_jwt_secret.get_secret_value()
            if settings.auth_jwt_secret
            else "epc-fallback-secret-development-key-32b"
        )
        try:
            payload = verify_report_download_token(
                token,
                secret,
                issuer=settings.auth_jwt_issuer,
                audience=settings.auth_jwt_audience,
            )
            if payload.get("report_id") != str(report.id):
                raise ApiError(
                    status_code=403,
                    code="FORBIDDEN",
                    message="Token does not match report ID.",
                )
        except ValueError as err:
            raise ApiError(status_code=403, code="FORBIDDEN", message=str(err)) from err

    if report.status != "ready" or not report.object_key:
        raise ApiError(
            status_code=404,
            code="NOT_FOUND",
            message="Report not found or not ready.",
        )

    storage = get_storage_adapter(settings)
    try:
        content = await storage.get_object(report.object_key)
    except FileNotFoundError:
        raise ApiError(
            status_code=404, code="NOT_FOUND", message="Report object not found in storage."
        ) from None

    if report.output_format == "csv":
        media_type = "text/csv; charset=utf-8"
        filename = f"activity-export-{report.id}.csv"
    elif report.output_format == "xlsx":
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        filename = f"activity-export-{report.id}.xlsx"
    else:
        media_type = "application/pdf"
        filename = f"schedule-report-{report.id}.pdf"

    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "Cache-Control": "private, no-store, max-age=0",
            "Pragma": "no-cache",
        },
    )
