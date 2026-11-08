"""Import job background worker logic (PI-013).

Worker claims queued jobs, reads private file bytes from storage,
executes parsing and updates progress percentage and preview metadata.
"""

import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.p6_xer import XERParserError, parse_xer_bytes
from app.adapters.queue import QueueAdapter
from app.adapters.storage import StorageAdapter
from app.domains.ingestion.job_service import claim_import_job, process_import_job
from app.models.project import ImportJob, UploadedFile

logger = structlog.get_logger()


async def execute_import_job(
    session: AsyncSession,
    storage: StorageAdapter,
    job_id: uuid.UUID,
) -> ImportJob | None:
    """Claim a single import job, process its content, and update DB."""
    job = await claim_import_job(session, job_id)
    if job is None:
        logger.warning("worker.job_not_found", job_id=str(job_id))
        return None

    if job.status == "confirmed":
        logger.info("worker.job_already_confirmed", job_id=str(job_id))
        return job

    # Fetch uploaded file record
    uploaded_file = await session.get(UploadedFile, job.uploaded_file_id)
    if uploaded_file is None:
        job.status = "failed"
        job.errors = [
            {
                "code": "UPLOADED_FILE_NOT_FOUND",
                "message": f"Associated uploaded file {job.uploaded_file_id} not found.",
                "actionable": "Please upload the file again.",
            }
        ]
        await session.commit()
        return job

    try:
        data = await storage.get_object(uploaded_file.object_key)
    except FileNotFoundError:
        job.status = "failed"
        job.errors = [
            {
                "code": "STORAGE_OBJECT_NOT_FOUND",
                "message": f"Physical storage file '{uploaded_file.object_key}' was not found.",
                "actionable": "Please re-upload the file.",
            }
        ]
        await session.commit()
        return job

    # For XER files, use the isolated P6 XER adapter (PI-020)
    if uploaded_file.source_format == "xer":
        try:
            bundle = parse_xer_bytes(data)
            job.progress_pct = 100.0
            job.status = "preview_ready"
            project_code = (
                bundle.source_metadata.get("proj_short_name")
                or bundle.project_name
                or "UNKNOWN_PROJECT"
            )
            job.detected_metadata = {
                "source_format": "xer",
                "format_version": bundle.source_format_version,
                "project_key": bundle.source_project_key,
                "project_code": project_code,
                "project_name": bundle.project_name,
                "data_date": bundle.data_date.isoformat() if bundle.data_date else None,
            }
            job.preview_summary = {
                "activities": len(bundle.activities),
                "wbs_nodes": len(bundle.wbs_nodes),
                "relationships": len(bundle.relationships),
                "calendars": len(bundle.calendars),
            }
            job.parser_name = "pi_p6_xer_adapter"
            job.parser_version = "0.2.0"
            job.warnings = [{"code": w.code, "message": w.message} for w in bundle.warnings]
            job.errors = []
            job.finished_at = datetime.now(UTC)
            await session.commit()
            logger.info("worker.xer_parsed", job_id=str(job.id), activities=len(bundle.activities))
            return job
        except XERParserError as exc:
            job.status = "failed"
            job.finished_at = datetime.now(UTC)
            job.errors = [{"code": exc.code, "message": exc.message, "actionable": exc.actionable}]
            await session.commit()
            logger.warning("worker.xer_parse_error", job_id=str(job.id), error_code=exc.code)
            return job

    # Process other formats (CSV, XLSX) via domain ingestion service
    processed_job = await process_import_job(
        session=session,
        job=job,
        file_data=data,
        source_format=uploaded_file.source_format,
    )
    await session.commit()
    logger.info(
        "worker.job_finished",
        job_id=str(job.id),
        status=processed_job.status,
        progress=float(processed_job.progress_pct),
    )
    return processed_job


async def process_next_job(
    session: AsyncSession,
    storage: StorageAdapter,
    queue: QueueAdapter,
    timeout_seconds: float = 1.0,
) -> bool:
    """Dequeue next job and process it. Returns True if a job was processed."""
    job_id = await queue.dequeue_import_job(timeout_seconds=timeout_seconds)
    if job_id is None:
        return False
    await execute_import_job(session, storage, job_id)
    return True
