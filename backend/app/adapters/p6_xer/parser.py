"""Primavera P6 XER file parser adapter (PI-020).

Parses Oracle Primavera P6 XER exports into canonical ParsedProjectBundle models.
Designed according to 02_SYSTEM_ARCHITECTURE.md Section 5 and 03_DATA_MODEL.md.
"""

from datetime import datetime

from app.adapters.p6_xer.models import (
    ParsedActivity,
    ParsedCalendar,
    ParsedProjectBundle,
    ParsedRelationship,
    ParsedWBS,
    ParseWarning,
)


class XERParserError(Exception):
    """Exception raised when an XER file cannot be parsed due to structural defects."""

    def __init__(self, code: str, message: str, actionable: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.actionable = actionable


def _parse_datetime(val: str | None) -> datetime | None:
    """Parse common Primavera P6 datetime formats."""
    if not val or not val.strip():
        return None
    val_clean = val.strip()
    # P6 common format: "YYYY-MM-DD HH:MM" or "YYYY-MM-DD HH:MM:SS" or "YYYY-MM-DD"
    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%Y-%m-%dT%H:%M:%S",
        "%d-%b-%y %H:%M",
        "%d-%b-%y",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(val_clean, fmt)
        except ValueError:
            continue
    return None


def _parse_float(val: str | None) -> float | None:
    if val is None or not val.strip():
        return None
    try:
        return float(val.strip())
    except ValueError:
        return None


def _decode_bytes(content: bytes) -> str:
    """Decode bytes handling UTF-8, Windows-1252, and Latin-1 encodings."""
    # Strip UTF-8 BOM if present
    if content.startswith(b"\xef\xbb\xbf"):
        content = content[3:]

    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        try:
            return content.decode("windows-1252")
        except UnicodeDecodeError:
            return content.decode("latin-1", errors="replace")


class XERParser:
    """Tokenizer and parser for Primavera P6 XER exports."""

    # Standard P6 task status mapping
    TASK_STATUS_MAP = {
        "TK_NotStart": "not_started",
        "TK_Active": "in_progress",
        "TK_Complete": "completed",
    }

    # Standard P6 relationship type mapping
    PRED_TYPE_MAP = {
        "PR_FS": "FS",
        "PR_SS": "SS",
        "PR_FF": "FF",
        "PR_SF": "SF",
    }

    def __init__(self) -> None:
        self.warnings: list[ParseWarning] = []

    def parse(self, content: bytes) -> ParsedProjectBundle:
        """Parse raw XER file bytes into a ParsedProjectBundle."""
        text = _decode_bytes(content)
        lines = text.splitlines()

        if not lines:
            raise XERParserError(
                code="EMPTY_XER_FILE",
                message="XER file is empty.",
                actionable="Provide a non-empty P6 XER schedule export.",
            )

        header_line = lines[0].strip()
        if not (header_line.startswith("ERMHDR") or "ERMHDR" in header_line):
            raise XERParserError(
                code="INVALID_XER_HEADER",
                message="XER file is missing valid ERMHDR header on line 1.",
                actionable=(
                    "Export the project again from Oracle Primavera P6 using standard XER export."
                ),
            )

        # Parse ERMHDR
        header_parts = header_line.split("\t")
        format_version = header_parts[1].strip() if len(header_parts) > 1 else None

        # State machine for tables
        tables: dict[str, list[dict[str, str]]] = {}
        current_table: str | None = None
        current_fields: list[str] = []

        for line_num, line in enumerate(lines[1:], start=2):
            if not line or not line.strip():
                continue

            parts = line.split("\t")
            marker = parts[0].strip()

            if marker == "%T":
                current_table = parts[1].strip() if len(parts) > 1 else "UNKNOWN"
                tables[current_table] = []
                current_fields = []
            elif marker == "%F":
                current_fields = [f.strip() for f in parts[1:]]
            elif marker == "%R":
                if not current_table or not current_fields:
                    self.warnings.append(
                        ParseWarning(
                            code="ORPHAN_ROW",
                            message=(
                                f"Row at line {line_num} found without preceding %T or %F header."
                            ),
                            table=current_table,
                            row_identifier=str(line_num),
                        )
                    )
                    continue

                values = [v.strip() for v in parts[1:]]
                # Zip fields and values, padding if row is shorter or longer
                row_dict: dict[str, str] = {}
                for idx, field_name in enumerate(current_fields):
                    val = values[idx] if idx < len(values) else ""
                    row_dict[field_name] = val

                # Extra unexpected columns beyond %F header
                if len(values) > len(current_fields):
                    for extra_idx in range(len(current_fields), len(values)):
                        row_dict[f"_extra_col_{extra_idx}"] = values[extra_idx]

                tables[current_table].append(row_dict)
            elif marker == "%E":
                # End of export marker
                break

        bundle = ParsedProjectBundle(
            source_format="xer",
            source_format_version=format_version,
            warnings=self.warnings,
        )

        known_tables = {"PROJECT", "CALENDAR", "PROJWBS", "TASK", "TASKPRED"}

        # 1. Parse PROJECT
        if "PROJECT" in tables and tables["PROJECT"]:
            proj_row = tables["PROJECT"][0]
            bundle.source_project_key = proj_row.get("proj_id")
            bundle.project_name = proj_row.get("proj_name") or proj_row.get("proj_short_name")
            data_date_str = proj_row.get("last_recalc_date") or proj_row.get("plan_start_date")
            bundle.data_date = _parse_datetime(data_date_str)
            bundle.source_metadata = {
                k: v for k, v in proj_row.items() if k not in ("proj_id", "proj_name")
            }

        # 2. Parse CALENDAR
        if "CALENDAR" in tables:
            for row in tables["CALENDAR"]:
                cid = row.get("clndr_id")
                if not cid:
                    continue
                cname = row.get("clndr_name", f"Calendar {cid}")
                is_def = row.get("default_flag", "").upper() == "Y"
                ctype = row.get("clndr_type")
                source_fields = {
                    k: v for k, v in row.items() if k not in ("clndr_id", "clndr_name")
                }
                bundle.calendars.append(
                    ParsedCalendar(
                        source_id=cid,
                        name=cname,
                        is_default=is_def,
                        calendar_type=ctype,
                        source_fields=source_fields,
                    )
                )

        # 3. Parse PROJWBS
        if "PROJWBS" in tables:
            for row in tables["PROJWBS"]:
                wid = row.get("wbs_id")
                if not wid:
                    continue
                parent_id = row.get("parent_wbs_id")
                code = row.get("wbs_short_name")
                name = row.get("wbs_name")
                source_fields = {
                    k: v
                    for k, v in row.items()
                    if k not in ("wbs_id", "parent_wbs_id", "wbs_short_name", "wbs_name")
                }
                bundle.wbs_nodes.append(
                    ParsedWBS(
                        source_id=wid,
                        parent_source_id=parent_id if parent_id else None,
                        code=code,
                        name=name,
                        source_fields=source_fields,
                    )
                )

        # 4. Parse TASK
        if "TASK" in tables:
            for row in tables["TASK"]:
                tid = row.get("task_id")
                if not tid:
                    continue
                code = row.get("task_code", f"ACT-{tid}")
                name = row.get("task_name", code)
                wbs_id = row.get("wbs_id")
                clndr_id = row.get("clndr_id")

                raw_status = row.get("status_code", "TK_NotStart")
                status = self.TASK_STATUS_MAP.get(raw_status)
                if not status:
                    status = raw_status
                    self.warnings.append(
                        ParseWarning(
                            code="UNKNOWN_ACTIVITY_STATUS",
                            message=(
                                f"Activity {code} has unknown status '{raw_status}'. "
                                "Retained as raw."
                            ),
                            table="TASK",
                            row_identifier=tid,
                        )
                    )

                planned_start = _parse_datetime(row.get("target_start_date"))
                planned_finish = _parse_datetime(row.get("target_end_date"))
                actual_start = _parse_datetime(row.get("act_start_date"))
                actual_finish = _parse_datetime(row.get("act_end_date"))

                target_durn = _parse_float(row.get("target_durn"))
                remain_durn = _parse_float(row.get("remain_durn"))
                act_durn = _parse_float(row.get("act_durn"))
                tot_float = _parse_float(row.get("total_float_hr_cnt"))
                free_float = _parse_float(row.get("free_float_hr_cnt"))
                phys_pct = _parse_float(row.get("phys_complete_pct"))

                known_task_cols = {
                    "task_id",
                    "task_code",
                    "task_name",
                    "wbs_id",
                    "clndr_id",
                    "status_code",
                    "target_start_date",
                    "target_end_date",
                    "act_start_date",
                    "act_end_date",
                    "target_durn",
                    "remain_durn",
                    "act_durn",
                    "total_float_hr_cnt",
                    "free_float_hr_cnt",
                    "phys_complete_pct",
                }
                source_fields = {k: v for k, v in row.items() if k not in known_task_cols}

                bundle.activities.append(
                    ParsedActivity(
                        source_id=tid,
                        code=code,
                        name=name,
                        status=status,
                        wbs_source_id=wbs_id,
                        calendar_source_id=clndr_id,
                        planned_start=planned_start,
                        planned_finish=planned_finish,
                        actual_start=actual_start,
                        actual_finish=actual_finish,
                        remaining_duration_hours=remain_durn,
                        original_duration_hours=target_durn,
                        actual_duration_hours=act_durn,
                        total_float_hours=tot_float,
                        free_float_hours=free_float,
                        physical_pct_complete=phys_pct,
                        source_fields=source_fields,
                    )
                )

        # 5. Parse TASKPRED
        if "TASKPRED" in tables:
            for row in tables["TASKPRED"]:
                pred_id = row.get("task_pred_id")
                pred_task_id = row.get("pred_task_id")
                succ_task_id = row.get("task_id")

                if not pred_task_id or not succ_task_id:
                    continue

                raw_rel_type = row.get("pred_type", "PR_FS")
                rel_type = self.PRED_TYPE_MAP.get(raw_rel_type)
                if not rel_type:
                    rel_type = raw_rel_type
                    self.warnings.append(
                        ParseWarning(
                            code="UNKNOWN_RELATIONSHIP_TYPE",
                            message=(
                                f"Relationship has unknown type '{raw_rel_type}'. Retained as raw."
                            ),
                            table="TASKPRED",
                            row_identifier=pred_id,
                        )
                    )

                lag = _parse_float(row.get("lag_hr_cnt")) or 0.0
                known_pred_cols = {
                    "task_pred_id",
                    "pred_task_id",
                    "task_id",
                    "pred_type",
                    "lag_hr_cnt",
                }
                source_fields = {k: v for k, v in row.items() if k not in known_pred_cols}

                bundle.relationships.append(
                    ParsedRelationship(
                        source_id=pred_id,
                        predecessor_source_id=pred_task_id,
                        successor_source_id=succ_task_id,
                        relationship_type=rel_type,
                        lag_hours=lag,
                        source_fields=source_fields,
                    )
                )

        # 6. Preserve Unknown/Diagnostic Tables
        for tbl_name, tbl_rows in tables.items():
            if tbl_name not in known_tables:
                bundle.unknown_tables[tbl_name] = tbl_rows

        # 7. Post-parse reference integrity warnings
        activity_ids = {a.source_id for a in bundle.activities}
        calendar_ids = {c.source_id for c in bundle.calendars}
        wbs_ids = {w.source_id for w in bundle.wbs_nodes}

        for act in bundle.activities:
            if act.wbs_source_id and act.wbs_source_id not in wbs_ids:
                self.warnings.append(
                    ParseWarning(
                        code="ORPHAN_WBS_REFERENCE",
                        message=(
                            f"Activity {act.code} references non-existent WBS node "
                            f"'{act.wbs_source_id}'."
                        ),
                        table="TASK",
                        row_identifier=act.source_id,
                    )
                )
            if act.calendar_source_id and act.calendar_source_id not in calendar_ids:
                self.warnings.append(
                    ParseWarning(
                        code="ORPHAN_CALENDAR_REFERENCE",
                        message=(
                            f"Activity {act.code} references non-existent Calendar "
                            f"'{act.calendar_source_id}'."
                        ),
                        table="TASK",
                        row_identifier=act.source_id,
                    )
                )

        for rel in bundle.relationships:
            if rel.predecessor_source_id not in activity_ids:
                self.warnings.append(
                    ParseWarning(
                        code="ORPHAN_PREDECESSOR",
                        message=(
                            "Relationship references missing predecessor activity "
                            f"'{rel.predecessor_source_id}'."
                        ),
                        table="TASKPRED",
                        row_identifier=rel.source_id,
                    )
                )
            if rel.successor_source_id not in activity_ids:
                self.warnings.append(
                    ParseWarning(
                        code="ORPHAN_SUCCESSOR",
                        message=(
                            "Relationship references missing successor activity "
                            f"'{rel.successor_source_id}'."
                        ),
                        table="TASKPRED",
                        row_identifier=rel.source_id,
                    )
                )

        return bundle


def parse_xer_bytes(content: bytes) -> ParsedProjectBundle:
    """Convenience helper to parse XER bytes with XERParser."""
    return XERParser().parse(content)
