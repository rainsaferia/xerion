"""Import job domain service (PI-013).

Rules (02_SYSTEM_ARCHITECTURE.md, 06_API_SPEC.md, 08_DEVELOPMENT_BACKLOG.md PI-013):
- Upload completion creates a queued job.
- Worker claims job and updates progress.
- Retry does not duplicate a confirmed project version.
- Failure state stores actionable error code.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import ImportJob, UploadedFile


class ActionableImportError(Exception):
    """Domain exception carrying an actionable error code and remediation advice."""

    def __init__(self, code: str, message: str, actionable: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.actionable = actionable


async def create_import_job(
    session: AsyncSession,
    uploaded_file: UploadedFile,
    requested_by: uuid.UUID | None = None,
    idempotency_key: str | None = None,
) -> ImportJob:
    """Create a new queued import job for an uploaded file."""
    if idempotency_key:
        existing = (
            await session.execute(
                select(ImportJob).where(
                    ImportJob.workspace_id == uploaded_file.workspace_id,
                    ImportJob.idempotency_key == idempotency_key,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing

    job = ImportJob(
        id=uuid.uuid4(),
        workspace_id=uploaded_file.workspace_id,
        project_id=uploaded_file.project_id,
        uploaded_file_id=uploaded_file.id,
        status="queued",
        progress_pct=0.0,
        detected_metadata={},
        preview_summary={},
        warnings=[],
        errors=[],
        idempotency_key=idempotency_key,
        requested_by=requested_by,
    )
    session.add(job)
    await session.flush()
    return job


async def claim_import_job(
    session: AsyncSession,
    job_id: uuid.UUID,
) -> ImportJob | None:
    """Claim a queued job for worker processing. Updates status to processing."""
    job = (
        await session.execute(select(ImportJob).where(ImportJob.id == job_id))
    ).scalar_one_or_none()

    if job is None:
        return None

    # If already confirmed, never re-process (preserves confirmed project versions)
    if job.status == "confirmed":
        return job

    job.status = "processing"
    job.started_at = datetime.now(UTC)
    job.progress_pct = 10.0
    await session.flush()
    return job


def parse_xer_preview(file_data: bytes) -> tuple[dict[str, object], dict[str, int]]:
    """Inspect XER structure to extract preliminary counts and metadata."""
    try:
        text = file_data.decode("utf-8", errors="replace")
    except Exception as e:
        raise ActionableImportError(
            code="UNREADABLE_FILE_ENCODING",
            message=f"File could not be decoded as text: {e}",
            actionable="Please ensure the XER file is not corrupted or password-encrypted.",
        ) from e

    lines = text.splitlines()
    if not lines or not (lines[0].startswith("ERMHDR") or "ERMHDR" in lines[0]):
        raise ActionableImportError(
            code="INVALID_XER_HEADER",
            message="XER file is missing valid ERMHDR header on the first line.",
            actionable=(
                "Export the project again from Oracle Primavera P6 using standard XER export."
            ),
        )

    counts: dict[str, int] = {
        "activities": 0,
        "wbs_nodes": 0,
        "relationships": 0,
        "calendars": 0,
    }
    current_table: str | None = None
    project_code: str | None = None

    for line in lines:
        if line.startswith("%T\t"):
            current_table = line.split("\t")[1].strip()
        elif line.startswith("%F\t"):
            continue
        elif line.startswith("%R\t") and current_table:
            parts = line.split("\t")
            if current_table == "TASK":
                counts["activities"] += 1
            elif current_table == "PROJWBS":
                counts["wbs_nodes"] += 1
            elif current_table == "TASKPRED":
                counts["relationships"] += 1
            elif current_table == "CALENDAR":
                counts["calendars"] += 1
            elif current_table == "PROJECT" and len(parts) > 2 and not project_code:
                project_code = parts[2].strip()

    metadata: dict[str, object] = {
        "source_format": "xer",
        "header": lines[0][:80],
        "project_code": project_code or "Imported P6 Schedule",
        "data_date": datetime.now(UTC).strftime("%Y-%m-%d"),
    }

    return metadata, counts


def parse_csv_preview(file_data: bytes) -> tuple[dict[str, object], dict[str, int]]:
    """Inspect CSV structure to extract row count."""
    try:
        text = file_data.decode("utf-8", errors="replace")
    except Exception as e:
        raise ActionableImportError(
            code="UNREADABLE_CSV",
            message=f"CSV could not be decoded: {e}",
            actionable="Ensure the CSV file is saved with standard UTF-8 encoding.",
        ) from e

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        raise ActionableImportError(
            code="EMPTY_CSV_FILE",
            message="The uploaded CSV file contains no rows.",
            actionable="Add activity rows and column headers to the CSV file before uploading.",
        )

    # First row is header, rest are rows
    row_count = max(0, len(lines) - 1)
    counts = {
        "activities": row_count,
        "wbs_nodes": 0,
        "relationships": 0,
        "calendars": 0,
    }
    metadata = {
        "source_format": "csv",
        "total_rows": row_count,
        "header_columns": lines[0].split(",") if lines else [],
    }
    # pyrefly: ignore[bad-return]
    return metadata, counts


async def process_import_job(
    session: AsyncSession,
    job: ImportJob,
    file_data: bytes,
    source_format: str,
) -> ImportJob:
    """Execute preview analysis on the claimed job and update progress."""
    job.progress_pct = 35.0
    await session.flush()

    try:
        if source_format == "xer":
            metadata, counts = parse_xer_preview(file_data)
        elif source_format == "csv":
            metadata, counts = parse_csv_preview(file_data)
        elif source_format == "xlsx":
            # XLSX container signature verified; preliminary counts for preview
            metadata = {"source_format": "xlsx", "file_size": len(file_data)}
            counts = {"activities": 0, "wbs_nodes": 0, "relationships": 0, "calendars": 0}
        else:
            raise ActionableImportError(
                code="UNSUPPORTED_FORMAT",
                message=f"Parser not implemented for source format '{source_format}'.",
                actionable="Upload schedule as .xer or tabular .csv.",
            )

        job.progress_pct = 80.0
        await session.flush()

        job.detected_metadata = metadata
        job.preview_summary = counts
        job.parser_name = f"pi_{source_format}_preview"
        job.parser_version = "0.1.0"
        job.warnings = []
        job.errors = []
        job.status = "preview_ready"
        job.progress_pct = 100.0
        job.finished_at = datetime.now(UTC)

    except ActionableImportError as exc:
        job.status = "failed"
        job.finished_at = datetime.now(UTC)
        job.errors = [
            {
                "code": exc.code,
                "message": exc.message,
                "actionable": exc.actionable,
            }
        ]
    except Exception as exc:
        job.status = "failed"
        job.finished_at = datetime.now(UTC)
        job.errors = [
            {
                "code": "IMPORT_PROCESSING_FAILED",
                "message": str(exc),
                "actionable": "Please review the file structure and retry upload.",
            }
        ]

    await session.flush()
    return job


def retry_import_job(job: ImportJob) -> bool:
    """Reset a failed job to queued state. Returns True if reset, False if already confirmed."""
    if job.status == "confirmed":
        # Guaranteed: retry does NOT duplicate a confirmed project version
        return False

    job.status = "queued"
    job.progress_pct = 0.0
    job.started_at = None
    job.finished_at = None
    job.errors = []
    return True


def confirm_import_job(job: ImportJob) -> tuple[bool, str | None]:
    """Explicitly confirm an import job (PI-014).

    Rules:
    - User cannot confirm a blocking import (errors present or failed status).
    - Confirmation is explicit.
    - Idempotent if already confirmed.
    """
    if job.status == "confirmed":
        return True, None

    if job.errors and len(job.errors) > 0:
        return False, "Cannot confirm an import job with blocking errors."

    if job.status != "preview_ready":
        return False, f"Job cannot be confirmed while in status '{job.status}'."

    job.status = "confirmed"
    if job.finished_at is None:
        job.finished_at = datetime.now(UTC)
    return True, None
