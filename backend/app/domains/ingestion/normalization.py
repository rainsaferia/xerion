"""Canonical normalization service (PI-021).

Rules (02_SYSTEM_ARCHITECTURE.md, 03_DATA_MODEL.md, 08_DEVELOPMENT_BACKLOG.md PI-021):
- Parsed objects map to canonical Pydantic models.
- Source IDs and source field references are retained.
- Unknown statuses/types do not crash import; they create warnings.
- Invalid date ranges and orphan links are reported.
"""

from datetime import date, datetime
from typing import Any

from app.domains.schedule.schemas import (
    ActivityStatus,
    CanonicalActivity,
    CanonicalBaseline,
    CanonicalCalendar,
    CanonicalProjectSchedule,
    CanonicalRelationship,
    CanonicalWBS,
    NormalizationWarning,
    RelationshipType,
)


def _to_date(val: Any) -> date | None:
    if val is None:
        return None
    if isinstance(val, date) and not isinstance(val, datetime):
        return val
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, str) and val.strip():
        s = val.strip()
        # Handle "YYYY-MM-DD" or "YYYY-MM-DD HH:MM"
        for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S"):
            try:
                return datetime.strptime(s, fmt).date()
            except ValueError:
                continue
    return None


def _get_val(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _normalize_activity_status(raw_status: str | None) -> tuple[ActivityStatus, str | None]:
    if not raw_status or not raw_status.strip():
        return "unknown", raw_status

    clean = raw_status.strip()
    status_map: dict[str, ActivityStatus] = {
        "not_started": "not_started",
        "tk_notstart": "not_started",
        "not started": "not_started",
        "in_progress": "in_progress",
        "tk_active": "in_progress",
        "in progress": "in_progress",
        "active": "in_progress",
        "complete": "complete",
        "completed": "complete",
        "tk_complete": "complete",
        "suspended": "suspended",
        "unknown": "unknown",
    }
    canonical = status_map.get(clean.lower())
    if canonical:
        return canonical, clean
    return "unknown", clean


def _normalize_relationship_type(raw_type: str | None) -> tuple[RelationshipType, str | None]:
    if not raw_type or not raw_type.strip():
        return "unknown", raw_type

    clean = raw_type.strip()
    rel_map: dict[str, RelationshipType] = {
        "fs": "FS",
        "pr_fs": "FS",
        "ss": "SS",
        "pr_ss": "SS",
        "ff": "FF",
        "pr_ff": "FF",
        "sf": "SF",
        "pr_sf": "SF",
        "unknown": "unknown",
    }
    canonical = rel_map.get(clean.lower())
    if canonical:
        return canonical, clean
    return "unknown", clean


def normalize_schedule_bundle(bundle: Any) -> CanonicalProjectSchedule:
    """Normalize a parsed bundle (or dictionary representation) into a CanonicalProjectSchedule.

    Validates:
    - Retains source IDs and source field mappings.
    - Emits warnings for unknown activity status and relationship types without failing.
    - Emits warnings for invalid date ranges (e.g. planned_start > planned_finish).
    - Emits warnings for orphan relationship links and self-loops.
    - Emits warnings for orphan WBS and calendar references.
    """
    warnings: list[NormalizationWarning] = []

    # 1. Calendars
    raw_calendars = _get_val(bundle, "calendars", [])
    calendars: list[CanonicalCalendar] = []
    calendar_ids: set[str] = set()

    for raw_cal in raw_calendars:
        cid = str(_get_val(raw_cal, "source_id") or "")
        if not cid:
            continue
        calendar_ids.add(cid)
        cname = str(
            _get_val(raw_cal, "name") or _get_val(raw_cal, "calendar_name") or f"Calendar {cid}"
        )
        ctype = _get_val(raw_cal, "calendar_type")
        tz = _get_val(raw_cal, "timezone")
        src_fields = dict(_get_val(raw_cal, "source_fields") or {})

        calendars.append(
            CanonicalCalendar(
                source_id=cid,
                calendar_name=cname,
                calendar_type=str(ctype) if ctype else None,
                timezone=str(tz) if tz else None,
                fidelity_status="metadata_only",
                source_fields=src_fields,
            )
        )

    # 2. WBS Nodes
    raw_wbs = _get_val(bundle, "wbs_nodes", [])
    wbs_nodes: list[CanonicalWBS] = []
    wbs_ids: set[str] = set()

    for raw_node in raw_wbs:
        wid = str(_get_val(raw_node, "source_id") or "")
        if not wid:
            continue
        wbs_ids.add(wid)
        parent_id = _get_val(raw_node, "parent_source_id")
        code = _get_val(raw_node, "code") or _get_val(raw_node, "wbs_code")
        name = _get_val(raw_node, "name") or _get_val(raw_node, "wbs_name") or f"WBS {wid}"
        sort_ord = _get_val(raw_node, "sort_order")
        src_fields = dict(_get_val(raw_node, "source_fields") or {})

        wbs_nodes.append(
            CanonicalWBS(
                source_id=wid,
                parent_source_id=str(parent_id) if parent_id else None,
                wbs_code=str(code) if code else None,
                wbs_name=str(name),
                sort_order=int(sort_ord) if sort_ord is not None else None,
                source_fields=src_fields,
            )
        )

    # 3. Activities
    raw_activities = _get_val(bundle, "activities", [])
    activities: list[CanonicalActivity] = []
    activity_ids: set[str] = set()

    for raw_act in raw_activities:
        aid = str(_get_val(raw_act, "source_id") or "")
        if not aid:
            continue
        activity_ids.add(aid)
        code = _get_val(raw_act, "code") or _get_val(raw_act, "activity_code") or f"ACT-{aid}"
        name = _get_val(raw_act, "name") or _get_val(raw_act, "activity_name") or str(code)
        wbs_id = _get_val(raw_act, "wbs_source_id")
        cal_id = _get_val(raw_act, "calendar_source_id")

        raw_status = _get_val(raw_act, "status") or _get_val(raw_act, "source_status")
        canonical_status, source_status = _normalize_activity_status(
            str(raw_status) if raw_status is not None else None
        )
        if canonical_status == "unknown" and raw_status:
            warnings.append(
                NormalizationWarning(
                    code="UNKNOWN_ACTIVITY_STATUS",
                    message=(
                        f"Activity '{code}' has unrecognized status '{raw_status}'. "
                        "Coerced to 'unknown'."
                    ),
                    entity_type="activity",
                    entity_source_id=aid,
                    details={"raw_status": str(raw_status)},
                )
            )

        planned_start = _to_date(_get_val(raw_act, "planned_start"))
        planned_finish = _to_date(_get_val(raw_act, "planned_finish"))
        actual_start = _to_date(_get_val(raw_act, "actual_start"))
        actual_finish = _to_date(_get_val(raw_act, "actual_finish"))

        # Schedule dates
        start_date = actual_start or planned_start
        finish_date = actual_finish or planned_finish

        # Date range validations (PI-021 acceptance criteria)
        if planned_start and planned_finish and planned_start > planned_finish:
            warnings.append(
                NormalizationWarning(
                    code="INVALID_DATE_RANGE",
                    message=(
                        f"Activity '{code}' planned_start ({planned_start}) "
                        f"is after planned_finish ({planned_finish})."
                    ),
                    entity_type="activity",
                    entity_source_id=aid,
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
                        f"Activity '{code}' actual_start ({actual_start}) "
                        f"is after actual_finish ({actual_finish})."
                    ),
                    entity_type="activity",
                    entity_source_id=aid,
                    details={
                        "actual_start": str(actual_start),
                        "actual_finish": str(actual_finish),
                    },
                )
            )

        # Integrity check: WBS reference
        if wbs_id and str(wbs_id) not in wbs_ids:
            warnings.append(
                NormalizationWarning(
                    code="ORPHAN_WBS_REFERENCE",
                    message=f"Activity '{code}' references non-existent WBS node '{wbs_id}'.",
                    entity_type="activity",
                    entity_source_id=aid,
                    details={"wbs_source_id": str(wbs_id)},
                )
            )

        # Integrity check: Calendar reference
        if cal_id and str(cal_id) not in calendar_ids:
            warnings.append(
                NormalizationWarning(
                    code="ORPHAN_CALENDAR_REFERENCE",
                    message=f"Activity '{code}' references non-existent Calendar '{cal_id}'.",
                    entity_type="activity",
                    entity_source_id=aid,
                    details={"calendar_source_id": str(cal_id)},
                )
            )

        # Numbers and floats
        remain_durn = _get_val(raw_act, "remaining_duration_hours")
        orig_durn = _get_val(raw_act, "original_duration_hours")
        act_durn = _get_val(raw_act, "actual_duration_hours")
        tot_float = _get_val(raw_act, "total_float_hours")
        free_float = _get_val(raw_act, "free_float_hours")

        phys_pct = _get_val(raw_act, "physical_pct_complete")
        dur_pct = _get_val(raw_act, "duration_pct_complete")
        unit_pct = _get_val(raw_act, "units_pct_complete")
        pct_type = _get_val(raw_act, "percent_complete_type")
        src_fields = dict(_get_val(raw_act, "source_fields") or {})

        activities.append(
            CanonicalActivity(
                source_id=aid,
                activity_code=str(code),
                activity_name=str(name),
                wbs_source_id=str(wbs_id) if wbs_id else None,
                calendar_source_id=str(cal_id) if cal_id else None,
                status=canonical_status,
                source_status=source_status,
                planned_start=planned_start,
                planned_finish=planned_finish,
                start_date=start_date,
                finish_date=finish_date,
                actual_start=actual_start,
                actual_finish=actual_finish,
                remaining_duration_hours=float(remain_durn) if remain_durn is not None else None,
                original_duration_hours=float(orig_durn) if orig_durn is not None else None,
                actual_duration_hours=float(act_durn) if act_durn is not None else None,
                total_float_hours=float(tot_float) if tot_float is not None else None,
                free_float_hours=float(free_float) if free_float is not None else None,
                physical_pct_complete=float(phys_pct) if phys_pct is not None else None,
                duration_pct_complete=float(dur_pct) if dur_pct is not None else None,
                units_pct_complete=float(unit_pct) if unit_pct is not None else None,
                percent_complete_type=str(pct_type) if pct_type else None,
                source_fields=src_fields,
            )
        )

    # 4. Relationships
    raw_relationships = _get_val(bundle, "relationships", [])
    relationships: list[CanonicalRelationship] = []

    for raw_rel in raw_relationships:
        pred_id = str(_get_val(raw_rel, "predecessor_source_id") or "")
        succ_id = str(_get_val(raw_rel, "successor_source_id") or "")
        rel_id = _get_val(raw_rel, "source_id")

        if not pred_id or not succ_id:
            continue

        raw_rel_type = _get_val(raw_rel, "relationship_type") or _get_val(
            raw_rel, "source_relationship_type"
        )
        canonical_rel_type, source_rel_type = _normalize_relationship_type(
            str(raw_rel_type) if raw_rel_type is not None else None
        )

        if canonical_rel_type == "unknown" and raw_rel_type:
            warnings.append(
                NormalizationWarning(
                    code="UNKNOWN_RELATIONSHIP_TYPE",
                    message=(
                        f"Relationship has unrecognized type '{raw_rel_type}'. "
                        "Coerced to 'unknown'."
                    ),
                    entity_type="relationship",
                    entity_source_id=str(rel_id) if rel_id else None,
                    details={"raw_relationship_type": str(raw_rel_type)},
                )
            )

        # Integrity check: Orphan link detection (PI-021 acceptance criteria)
        if pred_id not in activity_ids:
            warnings.append(
                NormalizationWarning(
                    code="ORPHAN_PREDECESSOR_LINK",
                    message=f"Relationship references missing predecessor activity '{pred_id}'.",
                    entity_type="relationship",
                    entity_source_id=str(rel_id) if rel_id else None,
                    details={"predecessor_source_id": pred_id},
                )
            )

        if succ_id not in activity_ids:
            warnings.append(
                NormalizationWarning(
                    code="ORPHAN_SUCCESSOR_LINK",
                    message=f"Relationship references missing successor activity '{succ_id}'.",
                    entity_type="relationship",
                    entity_source_id=str(rel_id) if rel_id else None,
                    details={"successor_source_id": succ_id},
                )
            )

        # Integrity check: Self loop
        if pred_id == succ_id:
            warnings.append(
                NormalizationWarning(
                    code="SELF_LOOP_RELATIONSHIP",
                    message=f"Relationship connects activity '{pred_id}' to itself.",
                    entity_type="relationship",
                    entity_source_id=str(rel_id) if rel_id else None,
                    details={"activity_source_id": pred_id},
                )
            )

        lag = _get_val(raw_rel, "lag_hours", 0.0)
        is_ext = bool(_get_val(raw_rel, "is_external", False))
        src_fields = dict(_get_val(raw_rel, "source_fields") or {})

        relationships.append(
            CanonicalRelationship(
                source_id=str(rel_id) if rel_id else None,
                predecessor_source_id=pred_id,
                successor_source_id=succ_id,
                relationship_type=canonical_rel_type,
                source_relationship_type=source_rel_type,
                lag_hours=float(lag) if lag is not None else 0.0,
                is_external=is_ext,
                source_fields=src_fields,
            )
        )

    # 5. Baselines
    raw_baselines = _get_val(bundle, "baselines", [])
    baselines: list[CanonicalBaseline] = []

    for raw_bl in raw_baselines:
        act_id = str(_get_val(raw_bl, "activity_source_id") or "")
        if not act_id:
            continue
        bl_id = _get_val(raw_bl, "baseline_source_id")
        bl_start = _to_date(_get_val(raw_bl, "planned_start") or _get_val(raw_bl, "baseline_start"))
        bl_finish = _to_date(
            _get_val(raw_bl, "planned_finish") or _get_val(raw_bl, "baseline_finish")
        )
        bl_durn = _get_val(raw_bl, "duration_hours") or _get_val(raw_bl, "baseline_duration_hours")
        bl_pct = _get_val(raw_bl, "baseline_pct_complete")
        bl_label = _get_val(raw_bl, "baseline_label")
        src_fields = dict(_get_val(raw_bl, "source_fields") or {})

        baselines.append(
            CanonicalBaseline(
                source_activity_id=act_id,
                baseline_source_id=str(bl_id) if bl_id else None,
                baseline_start=bl_start,
                baseline_finish=bl_finish,
                baseline_duration_hours=float(bl_durn) if bl_durn is not None else None,
                baseline_pct_complete=float(bl_pct) if bl_pct is not None else None,
                baseline_label=str(bl_label) if bl_label else None,
                source_fields=src_fields,
            )
        )

    # Combine parser warnings if passed
    for warn in _get_val(bundle, "warnings", []):
        w_code = _get_val(warn, "code", "PARSER_WARNING")
        w_msg = _get_val(warn, "message", "")
        w_tbl = _get_val(warn, "table")
        w_row = _get_val(warn, "row_identifier")
        ent_type = (
            "activity" if w_tbl == "TASK" else "relationship" if w_tbl == "TASKPRED" else "project"
        )
        warnings.append(
            NormalizationWarning(
                code=str(w_code),
                message=str(w_msg),
                entity_type=ent_type,
                entity_source_id=str(w_row) if w_row else None,
                details={"table": str(w_tbl)} if w_tbl else {},
            )
        )

    return CanonicalProjectSchedule(
        source_format=str(_get_val(bundle, "source_format", "unknown")),
        source_format_version=_get_val(bundle, "source_format_version"),
        source_project_key=_get_val(bundle, "source_project_key"),
        project_name=_get_val(bundle, "project_name"),
        data_date=_to_date(_get_val(bundle, "data_date")),
        calendars=calendars,
        wbs_nodes=wbs_nodes,
        activities=activities,
        relationships=relationships,
        baselines=baselines,
        source_metadata=dict(_get_val(bundle, "source_metadata") or {}),
        warnings=warnings,
    )
