"""Mapping profile domain and validation engine for tabular schedule imports (PI-022).

Rules (08_DEVELOPMENT_BACKLOG.md PI-022):
- Detect sheets/headers/sample rows.
- User can map required columns for activity-level progress/schedule template.
- Save and reuse mapping profile.
- Validate dates, IDs, percentages, and duplicates.
- Preview normalized data before confirmation.
"""

import re
import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.schedule.schemas import (
    ActivityStatus,
    CanonicalActivity,
    CanonicalProjectSchedule,
    CanonicalWBS,
    NormalizationWarning,
)
from app.models.project import ImportMapping


class MappingValidationError(Exception):
    """Exception raised when mapping configuration is invalid or missing required keys."""

    def __init__(self, message: str, details: list[str] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or []


class ColumnMappingConfig(BaseModel):
    """Configuration mapping tabular file columns to canonical schedule fields."""

    model_config = ConfigDict(extra="ignore")

    activity_code: str = Field(description="Column name containing activity / task ID")
    activity_name: str = Field(description="Column name containing activity / task name")
    status: str | None = None
    planned_start: str | None = None
    planned_finish: str | None = None
    actual_start: str | None = None
    actual_finish: str | None = None
    remaining_duration_hours: str | None = None
    original_duration_hours: str | None = None
    total_float_hours: str | None = None
    percent_complete: str | None = None
    wbs_code: str | None = None
    sheet_name: str | None = None


def _parse_tabular_date(val: Any) -> tuple[date | None, bool]:
    """Parse a date value. Returns (date_val, is_invalid_format)."""
    if val is None:
        return None, False
    if isinstance(val, datetime):
        return val.date(), False
    if isinstance(val, date):
        return val, False

    s = str(val).strip()
    if not s:
        return None, False

    formats = (
        "%Y-%m-%d",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%m/%d/%Y",
        "%d/%m/%Y",
        "%d-%b-%Y",
        "%d-%b-%y",
        "%Y/%m/%d",
    )
    for fmt in formats:
        try:
            return datetime.strptime(s, fmt).date(), False
        except ValueError:
            continue
    return None, True


def _parse_percentage(val: Any) -> tuple[float | None, bool]:
    """Parse percentage value. Returns (float_pct, is_out_of_bounds)."""
    if val is None:
        return None, False
    if isinstance(val, (int, float)):
        num = float(val)
        if 0.0 <= num <= 100.0:
            return num, False
        return num, True

    s = str(val).strip()
    if not s:
        return None, False

    # Strip '%' or 'pct'
    clean = re.sub(r"[%\s]", "", s)
    try:
        num = float(clean)
        # If expressed as fraction 0.0 to 1.0, e.g. 0.75, normalize to 75.0
        # only if string explicitly had a decimal and no % sign, but in EPC schedules
        # percentages are usually 0-100.
        if 0.0 <= num <= 100.0:
            return num, False
        return num, True
    except ValueError:
        return None, False


def _parse_float(val: Any) -> float | None:
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _normalize_activity_status(raw_status: str | None) -> tuple[ActivityStatus, str | None]:
    if not raw_status or not raw_status.strip():
        return "unknown", raw_status

    clean = raw_status.strip().lower()
    mapping: dict[str, ActivityStatus] = {
        "not_started": "not_started",
        "not started": "not_started",
        "tk_notstart": "not_started",
        "unstarted": "not_started",
        "in_progress": "in_progress",
        "in progress": "in_progress",
        "active": "in_progress",
        "tk_active": "in_progress",
        "started": "in_progress",
        "complete": "complete",
        "completed": "complete",
        "tk_complete": "complete",
        "done": "complete",
        "finished": "complete",
        "suspended": "suspended",
        "on_hold": "suspended",
        "on hold": "suspended",
    }
    canonical = mapping.get(clean)
    if canonical:
        return canonical, raw_status.strip()
    return "unknown", raw_status.strip()


def validate_and_normalize_tabular(
    rows: list[dict[str, Any]],
    mapping: ColumnMappingConfig,
    source_format: str = "csv",
) -> CanonicalProjectSchedule:
    """Validate tabular rows against mapping configuration and normalize into canonical schedule.

    Acceptance criteria (PI-022):
    - Validates required columns (activity_code, activity_name).
    - Detects and reports duplicate activity IDs.
    - Validates dates (format and start <= finish).
    - Validates percentage complete [0, 100].
    - Preserves unmapped fields in source_fields.
    - Emits warnings without crashing on recoverable validation errors.
    """
    if not mapping.activity_code or not mapping.activity_code.strip():
        raise MappingValidationError("Mapping must specify an activity_code column.")
    if not mapping.activity_name or not mapping.activity_name.strip():
        raise MappingValidationError("Mapping must specify an activity_name column.")

    warnings: list[NormalizationWarning] = []
    activities: list[CanonicalActivity] = []
    seen_codes: set[str] = set()
    wbs_map: dict[str, CanonicalWBS] = {}

    mapped_keys = {
        mapping.activity_code,
        mapping.activity_name,
        mapping.status,
        mapping.planned_start,
        mapping.planned_finish,
        mapping.actual_start,
        mapping.actual_finish,
        mapping.remaining_duration_hours,
        mapping.original_duration_hours,
        mapping.total_float_hours,
        mapping.percent_complete,
        mapping.wbs_code,
    }
    mapped_keys.discard(None)

    for row_idx, row in enumerate(rows, start=1):
        raw_code = row.get(mapping.activity_code)
        raw_name = row.get(mapping.activity_name)

        if raw_code is None or not str(raw_code).strip():
            warnings.append(
                NormalizationWarning(
                    code="MISSING_ACTIVITY_CODE",
                    message=f"Row {row_idx} is missing activity code.",
                    entity_type="activity",
                    entity_source_id=str(row_idx),
                    details={"row_number": row_idx},
                )
            )
            continue

        act_code = str(raw_code).strip()
        act_name = (
            str(raw_name).strip() if raw_name is not None and str(raw_name).strip() else act_code
        )

        # Duplicate ID check (PI-022 acceptance criterion)
        if act_code in seen_codes:
            warnings.append(
                NormalizationWarning(
                    code="DUPLICATE_ACTIVITY_ID",
                    message=f"Duplicate activity code '{act_code}' detected at row {row_idx}.",
                    entity_type="activity",
                    entity_source_id=act_code,
                    details={"activity_code": act_code, "row_number": row_idx},
                )
            )
        seen_codes.add(act_code)

        # Dates validation (PI-022 acceptance criterion)
        planned_start: date | None = None
        if mapping.planned_start and mapping.planned_start in row:
            val = row[mapping.planned_start]
            p_start, is_inv = _parse_tabular_date(val)
            if is_inv:
                warnings.append(
                    NormalizationWarning(
                        code="INVALID_DATE_FORMAT",
                        message=(
                            f"Row {row_idx} activity '{act_code}' has invalid "
                            f"planned_start date '{val}'."
                        ),
                        entity_type="activity",
                        entity_source_id=act_code,
                        details={"field": "planned_start", "raw_value": str(val)},
                    )
                )
            planned_start = p_start

        planned_finish: date | None = None
        if mapping.planned_finish and mapping.planned_finish in row:
            val = row[mapping.planned_finish]
            p_fin, is_inv = _parse_tabular_date(val)
            if is_inv:
                warnings.append(
                    NormalizationWarning(
                        code="INVALID_DATE_FORMAT",
                        message=(
                            f"Row {row_idx} activity '{act_code}' has invalid "
                            f"planned_finish date '{val}'."
                        ),
                        entity_type="activity",
                        entity_source_id=act_code,
                        details={"field": "planned_finish", "raw_value": str(val)},
                    )
                )
            planned_finish = p_fin

        actual_start: date | None = None
        if mapping.actual_start and mapping.actual_start in row:
            val = row[mapping.actual_start]
            a_start, is_inv = _parse_tabular_date(val)
            if is_inv:
                warnings.append(
                    NormalizationWarning(
                        code="INVALID_DATE_FORMAT",
                        message=(
                            f"Row {row_idx} activity '{act_code}' has invalid "
                            f"actual_start date '{val}'."
                        ),
                        entity_type="activity",
                        entity_source_id=act_code,
                        details={"field": "actual_start", "raw_value": str(val)},
                    )
                )
            actual_start = a_start

        actual_finish: date | None = None
        if mapping.actual_finish and mapping.actual_finish in row:
            val = row[mapping.actual_finish]
            a_fin, is_inv = _parse_tabular_date(val)
            if is_inv:
                warnings.append(
                    NormalizationWarning(
                        code="INVALID_DATE_FORMAT",
                        message=(
                            f"Row {row_idx} activity '{act_code}' has invalid "
                            f"actual_finish date '{val}'."
                        ),
                        entity_type="activity",
                        entity_source_id=act_code,
                        details={"field": "actual_finish", "raw_value": str(val)},
                    )
                )
            actual_finish = a_fin

        if planned_start and planned_finish and planned_start > planned_finish:
            warnings.append(
                NormalizationWarning(
                    code="INVALID_DATE_RANGE",
                    message=(
                        f"Row {row_idx} activity '{act_code}' planned_start ({planned_start}) "
                        f"is after planned_finish ({planned_finish})."
                    ),
                    entity_type="activity",
                    entity_source_id=act_code,
                    details={
                        "planned_start": str(planned_start),
                        "planned_finish": str(planned_finish),
                    },
                )
            )

        if actual_start and actual_finish and actual_start > actual_finish:
            warnings.append(
                NormalizationWarning(
                    code="INVALID_ACTUAL_DATE_RANGE",
                    message=(
                        f"Row {row_idx} activity '{act_code}' actual_start ({actual_start}) "
                        f"is after actual_finish ({actual_finish})."
                    ),
                    entity_type="activity",
                    entity_source_id=act_code,
                    details={
                        "actual_start": str(actual_start),
                        "actual_finish": str(actual_finish),
                    },
                )
            )

        # Percentage validation (PI-022 acceptance criterion)
        phys_pct: float | None = None
        if mapping.percent_complete and mapping.percent_complete in row:
            val = row[mapping.percent_complete]
            parsed_pct, is_out = _parse_percentage(val)
            if is_out:
                warnings.append(
                    NormalizationWarning(
                        code="PERCENTAGE_OUT_OF_BOUNDS",
                        message=(
                            f"Row {row_idx} activity '{act_code}' percentage value '{val}' "
                            "is outside the valid range [0, 100]."
                        ),
                        entity_type="activity",
                        entity_source_id=act_code,
                        details={"raw_percentage": str(val)},
                    )
                )
            phys_pct = parsed_pct if not is_out else None

        # Status
        status_val = row.get(mapping.status) if mapping.status else None
        canonical_status, source_status = _normalize_activity_status(
            str(status_val) if status_val is not None else None
        )
        if canonical_status == "unknown" and status_val:
            warnings.append(
                NormalizationWarning(
                    code="UNKNOWN_ACTIVITY_STATUS",
                    message=(
                        f"Activity '{act_code}' has unrecognized status '{status_val}'. "
                        "Coerced to 'unknown'."
                    ),
                    entity_type="activity",
                    entity_source_id=act_code,
                    details={"raw_status": str(status_val)},
                )
            )

        # WBS
        wbs_code_val = (
            str(row[mapping.wbs_code]).strip()
            if mapping.wbs_code and row.get(mapping.wbs_code)
            else None
        )
        if wbs_code_val and wbs_code_val not in wbs_map:
            wbs_map[wbs_code_val] = CanonicalWBS(
                source_id=wbs_code_val,
                wbs_code=wbs_code_val,
                wbs_name=wbs_code_val,
            )

        # Numbers
        rem_dur = (
            _parse_float(row.get(mapping.remaining_duration_hours))
            if mapping.remaining_duration_hours
            else None
        )
        orig_dur = (
            _parse_float(row.get(mapping.original_duration_hours))
            if mapping.original_duration_hours
            else None
        )
        tot_float = (
            _parse_float(row.get(mapping.total_float_hours)) if mapping.total_float_hours else None
        )

        # Unmapped columns preserved in source_fields
        source_fields = {k: v for k, v in row.items() if k not in mapped_keys}

        activities.append(
            CanonicalActivity(
                source_id=act_code,
                activity_code=act_code,
                activity_name=act_name,
                wbs_source_id=wbs_code_val,
                status=canonical_status,
                source_status=source_status,
                planned_start=planned_start,
                planned_finish=planned_finish,
                start_date=actual_start or planned_start,
                finish_date=actual_finish or planned_finish,
                actual_start=actual_start,
                actual_finish=actual_finish,
                remaining_duration_hours=rem_dur,
                original_duration_hours=orig_dur,
                total_float_hours=tot_float,
                physical_pct_complete=phys_pct,
                source_fields=source_fields,
            )
        )

    return CanonicalProjectSchedule(
        source_format=source_format,
        wbs_nodes=list(wbs_map.values()),
        activities=activities,
        warnings=warnings,
    )


# --- Mapping Profile DB Persistence Helpers ---


async def save_mapping_profile(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    name: str,
    mapping_config: dict[str, Any],
    dataset_type: str = "activity_progress",
    created_by: uuid.UUID | None = None,
) -> ImportMapping:
    """Save or update a reusable tabular mapping profile in the workspace."""
    # Find existing profile by workspace and name
    existing = (
        (
            await session.execute(
                select(ImportMapping)
                .where(
                    ImportMapping.workspace_id == workspace_id,
                    ImportMapping.name == name,
                )
                .order_by(ImportMapping.mapping_version.desc())
            )
        )
        .scalars()
        .first()
    )

    next_version = (existing.mapping_version + 1) if existing else 1

    profile = ImportMapping(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        name=name,
        dataset_type=dataset_type,
        mapping_config=mapping_config,
        mapping_version=next_version,
        created_by=created_by,
    )
    session.add(profile)
    await session.flush()
    return profile


async def list_mapping_profiles(
    session: AsyncSession,
    workspace_id: uuid.UUID,
) -> list[ImportMapping]:
    """List all saved mapping profiles for a workspace."""
    rows = (
        (
            await session.execute(
                select(ImportMapping)
                .where(ImportMapping.workspace_id == workspace_id)
                .order_by(ImportMapping.name, ImportMapping.mapping_version.desc())
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


async def get_mapping_profile(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    profile_id: uuid.UUID,
) -> ImportMapping | None:
    """Retrieve a specific mapping profile by ID, scoped to workspace."""
    return (
        await session.execute(
            select(ImportMapping).where(
                ImportMapping.id == profile_id,
                ImportMapping.workspace_id == workspace_id,
            )
        )
    ).scalar_one_or_none()
