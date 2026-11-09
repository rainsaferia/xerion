"""Project version creation and materialization domain service (PI-023).

Rules (02_SYSTEM_ARCHITECTURE.md, 03_DATA_MODEL.md, 08_DEVELOPMENT_BACKLOG.md PI-023):
- Confirmed import creates next sequential version number.
- Prior version records remain unchanged (isolated by project_version_id).
- projects.latest_version_id updates only after version is ready.
- Version list shows data date, source file, and parser version.
"""

import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.schedule.schemas import CanonicalProjectSchedule
from app.models.project import ImportJob, Project, ProjectVersion, UploadedFile
from app.models.schedule import (
    Activity,
    ActivityRelationship,
    BaselineActivityValue,
    Calendar,
    WBSNode,
)


async def create_version_from_confirmed_job(
    session: AsyncSession,
    job: ImportJob,
    schedule: CanonicalProjectSchedule,
    user_id: uuid.UUID | None = None,
) -> ProjectVersion:
    """Create an immutable ProjectVersion and persist canonical schedule records.

    Acceptance criteria (PI-023):
    - Confirmed import creates next version number.
    - Prior version records remain unchanged.
    - projects.latest_version_id updates only after version is ready.
    """
    # 1. Idempotency: return existing version if already created
    existing = (
        await session.execute(select(ProjectVersion).where(ProjectVersion.import_job_id == job.id))
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    # 2. Get project
    project = await session.get(Project, job.project_id)
    if not project:
        raise ValueError(f"Project '{job.project_id}' not found.")

    # 3. Calculate next sequential version number
    max_version = (
        await session.execute(
            select(func.max(ProjectVersion.version_number)).where(
                ProjectVersion.project_id == job.project_id
            )
        )
    ).scalar() or 0
    next_version = max_version + 1

    # 4. Create ProjectVersion in staging status
    version = ProjectVersion(
        id=uuid.uuid4(),
        workspace_id=job.workspace_id,
        project_id=job.project_id,
        import_job_id=job.id,
        version_number=next_version,
        version_label=f"V{next_version}",
        source_project_id=schedule.source_project_key or project.project_code,
        source_project_code=project.project_code,
        source_project_name=schedule.project_name or project.name,
        source_format=schedule.source_format,
        source_format_version=schedule.source_format_version,
        parser_version=job.parser_version or "0.2.0",
        data_date=schedule.data_date,
        source_metadata=schedule.source_metadata,
        quality_summary={
            "activities_count": len(schedule.activities),
            "wbs_nodes_count": len(schedule.wbs_nodes),
            "relationships_count": len(schedule.relationships),
            "calendars_count": len(schedule.calendars),
            "warnings_count": len(schedule.warnings),
        },
        status="staging",
        confirmed_by=user_id,
        confirmed_at=datetime.now(UTC),
    )
    session.add(version)
    await session.flush()

    # 5. Persist WBS Nodes
    wbs_map: dict[str, uuid.UUID] = {}
    for w in schedule.wbs_nodes:
        wbs_id = uuid.uuid4()
        wbs_map[w.source_id] = wbs_id
        session.add(
            WBSNode(
                id=wbs_id,
                workspace_id=version.workspace_id,
                project_id=version.project_id,
                project_version_id=version.id,
                source_wbs_id=w.source_id,
                wbs_code=w.wbs_code,
                wbs_name=w.wbs_name,
                sort_order=w.sort_order,
                source_fields=w.source_fields,
            )
        )
    await session.flush()

    # 6. Persist Calendars
    cal_map: dict[str, uuid.UUID] = {}
    for c in schedule.calendars:
        cal_id = uuid.uuid4()
        cal_map[c.source_id] = cal_id
        session.add(
            Calendar(
                id=cal_id,
                workspace_id=version.workspace_id,
                project_id=version.project_id,
                project_version_id=version.id,
                source_calendar_id=c.source_id,
                calendar_name=c.calendar_name,
                calendar_type=c.calendar_type,
                timezone=c.timezone,
                fidelity_status=c.fidelity_status,
                source_fields=c.source_fields,
            )
        )
    await session.flush()

    # 7. Persist Activities (chunked flush for large P6 schedules)
    act_map: dict[str, uuid.UUID] = {}
    start_dates: list[date] = []
    finish_dates: list[date] = []
    CHUNK_SIZE = 1000

    for idx, a in enumerate(schedule.activities):
        act_id = uuid.uuid4()
        act_map[a.source_id] = act_id
        if a.start_date:
            start_dates.append(a.start_date)
        if a.finish_date:
            finish_dates.append(a.finish_date)

        session.add(
            Activity(
                id=act_id,
                workspace_id=version.workspace_id,
                project_id=version.project_id,
                project_version_id=version.id,
                source_activity_id=a.source_id,
                activity_code=a.activity_code,
                activity_name=a.activity_name,
                wbs_node_id=wbs_map.get(a.wbs_source_id) if a.wbs_source_id else None,
                calendar_id=cal_map.get(a.calendar_source_id) if a.calendar_source_id else None,
                status=a.status,
                source_status=a.source_status,
                planned_start=a.planned_start,
                planned_finish=a.planned_finish,
                start_date=a.start_date,
                finish_date=a.finish_date,
                actual_start=a.actual_start,
                actual_finish=a.actual_finish,
                remaining_duration_hours=a.remaining_duration_hours,
                original_duration_hours=a.original_duration_hours,
                actual_duration_hours=a.actual_duration_hours,
                total_float_hours=a.total_float_hours,
                free_float_hours=a.free_float_hours,
                physical_pct_complete=a.physical_pct_complete,
                duration_pct_complete=a.duration_pct_complete,
                units_pct_complete=a.units_pct_complete,
                percent_complete_type=a.percent_complete_type,
                source_fields=a.source_fields,
            )
        )
        if (idx + 1) % CHUNK_SIZE == 0:
            await session.flush()
    await session.flush()

    # 8. Persist Relationships (chunked flush)
    rel_count = 0
    for r in schedule.relationships:
        pred_uuid = act_map.get(r.predecessor_source_id)
        succ_uuid = act_map.get(r.successor_source_id)
        # Avoid orphan or self-loop insertion violating constraints
        if pred_uuid and succ_uuid and pred_uuid != succ_uuid:
            session.add(
                ActivityRelationship(
                    id=uuid.uuid4(),
                    workspace_id=version.workspace_id,
                    project_id=version.project_id,
                    project_version_id=version.id,
                    source_relationship_id=r.source_id,
                    predecessor_activity_id=pred_uuid,
                    successor_activity_id=succ_uuid,
                    relationship_type=r.relationship_type,
                    lag_hours=r.lag_hours,
                    is_external=r.is_external,
                    source_fields=r.source_fields,
                )
            )
            rel_count += 1
            if rel_count % CHUNK_SIZE == 0:
                await session.flush()
    await session.flush()

    # 9. Persist Baselines
    for b in schedule.baselines:
        session.add(
            BaselineActivityValue(
                id=uuid.uuid4(),
                workspace_id=version.workspace_id,
                project_id=version.project_id,
                project_version_id=version.id,
                baseline_source_id=b.baseline_source_id,
                source_activity_id=b.source_activity_id,
                baseline_start=b.baseline_start,
                baseline_finish=b.baseline_finish,
                baseline_duration_hours=b.baseline_duration_hours,
                baseline_pct_complete=b.baseline_pct_complete,
                baseline_label=b.baseline_label,
                source_fields=b.source_fields,
            )
        )
    await session.flush()

    # 10. Finalize version: update dates, transition to 'ready'
    if start_dates:
        version.project_start_date = min(start_dates)
    if finish_dates:
        version.project_finish_date = max(finish_dates)
    version.status = "ready"

    # 11. Atomically update project latest_version_id ONLY when version is ready
    project.latest_version_id = version.id

    # 12. Mark job confirmed
    job.status = "confirmed"
    job.finished_at = datetime.now(UTC)
    await session.flush()

    return version


async def list_project_versions(
    session: AsyncSession,
    project_id: uuid.UUID,
) -> list[dict[str, Any]]:
    """List version history showing data date, source file, and parser version."""
    rows = (
        await session.execute(
            select(
                ProjectVersion,
                UploadedFile.original_filename,
                func.count(Activity.id).label("activity_count"),
            )
            .join(ImportJob, ImportJob.id == ProjectVersion.import_job_id)
            .join(UploadedFile, UploadedFile.id == ImportJob.uploaded_file_id)
            .outerjoin(Activity, Activity.project_version_id == ProjectVersion.id)
            .where(ProjectVersion.project_id == project_id)
            .group_by(ProjectVersion.id, UploadedFile.original_filename)
            .order_by(ProjectVersion.version_number.desc())
        )
    ).all()

    result = []
    for pv, filename, count in rows:
        result.append(
            {
                "id": pv.id,
                "project_id": pv.project_id,
                "version_number": pv.version_number,
                "version_label": pv.version_label,
                "data_date": pv.data_date,
                "project_start_date": pv.project_start_date,
                "project_finish_date": pv.project_finish_date,
                "source_filename": filename,
                "source_format": pv.source_format,
                "parser_version": pv.parser_version,
                "status": pv.status,
                "activity_count": count or 0,
                "created_at": pv.created_at,
            }
        )
    return result


async def get_project_version_detail(
    session: AsyncSession,
    project_id: uuid.UUID,
    version_id: uuid.UUID,
) -> dict[str, Any] | None:
    """Retrieve full version detail and quality summary."""
    row = (
        await session.execute(
            select(
                ProjectVersion,
                UploadedFile.original_filename,
                func.count(Activity.id).label("activity_count"),
            )
            .join(ImportJob, ImportJob.id == ProjectVersion.import_job_id)
            .join(UploadedFile, UploadedFile.id == ImportJob.uploaded_file_id)
            .outerjoin(Activity, Activity.project_version_id == ProjectVersion.id)
            .where(
                ProjectVersion.project_id == project_id,
                ProjectVersion.id == version_id,
            )
            .group_by(ProjectVersion.id, UploadedFile.original_filename)
        )
    ).first()

    if not row:
        return None

    pv, filename, count = row
    return {
        "id": pv.id,
        "project_id": pv.project_id,
        "version_number": pv.version_number,
        "version_label": pv.version_label,
        "data_date": pv.data_date,
        "project_start_date": pv.project_start_date,
        "project_finish_date": pv.project_finish_date,
        "source_filename": filename,
        "source_format": pv.source_format,
        "source_format_version": pv.source_format_version,
        "parser_version": pv.parser_version,
        "source_metadata": pv.source_metadata,
        "quality_summary": pv.quality_summary,
        "status": pv.status,
        "activity_count": count or 0,
        "created_at": pv.created_at,
    }
