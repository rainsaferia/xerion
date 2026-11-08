"""PI-020: Primavera P6 XER parser proof of concept tests.

Acceptance criteria:
- Parser handles each supported fixture reproducibly.
- Counts and selected key values are compared against a trusted P6 export/reference.
- Malformed/unsupported files fail clearly.
- Parser tests include encoding, line endings, large file, missing optional
  table, and unexpected field cases.
"""

import time
from datetime import datetime
from pathlib import Path

import pytest
from app.adapters.p6_xer import (
    ParsedProjectBundle,
    XERParserError,
    parse_xer_bytes,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "xer"


def test_parse_release_82_facility_fixture() -> None:
    """Compare counts and key values against trusted P6 8.2 export fixture."""
    fixture_path = FIXTURES_DIR / "p6_release_82_facility.xer"
    content = fixture_path.read_bytes()

    bundle = parse_xer_bytes(content)

    assert isinstance(bundle, ParsedProjectBundle)
    assert bundle.source_format == "xer"
    assert bundle.source_format_version == "8.2"
    assert bundle.source_project_key == "1001"
    assert bundle.project_name == "Gas Processing Facility EPC"
    assert bundle.data_date == datetime(2026, 11, 1, 8, 0)

    # 1. Calendars (2 records)
    assert len(bundle.calendars) == 2
    cal_names = {c.name for c in bundle.calendars}
    assert "Standard 5 Day Workweek" in cal_names
    assert "Continuous 7 Day Operation" in cal_names
    default_cal = next(c for c in bundle.calendars if c.is_default)
    assert default_cal.source_id == "501"

    # 2. WBS Nodes (4 records)
    assert len(bundle.wbs_nodes) == 4
    wbs_codes = {w.code for w in bundle.wbs_nodes}
    assert {"GPF", "GPF.ENG", "GPF.PROC", "GPF.CONST"}.issubset(wbs_codes)

    # 3. Activities (5 records)
    assert len(bundle.activities) == 5
    act_map = {a.code: a for a in bundle.activities}

    # Completed activity
    pfd = act_map["ENG-100"]
    assert pfd.name == "Process Flow Diagrams (PFD)"
    assert pfd.status == "completed"
    assert pfd.planned_start == datetime(2026, 1, 15, 8, 0)
    assert pfd.actual_finish == datetime(2026, 2, 14, 17, 0)
    assert pfd.remaining_duration_hours == 0.0
    assert pfd.physical_pct_complete == 100.0

    # Active activity
    pid = act_map["ENG-200"]
    assert pid.status == "in_progress"
    assert pid.actual_start == datetime(2026, 2, 16, 8, 0)
    assert pid.remaining_duration_hours == 220.0
    assert pid.physical_pct_complete == 50.0

    # Float checks
    civil = act_map["CONST-100"]
    assert civil.status == "not_started"
    assert civil.total_float_hours == 80.0
    assert civil.free_float_hours == 80.0

    # 4. Relationships (5 records)
    assert len(bundle.relationships) == 5
    ss_rel = next(r for r in bundle.relationships if r.relationship_type == "SS")
    assert ss_rel.lag_hours == 40.0
    assert ss_rel.predecessor_source_id == "2002"
    assert ss_rel.successor_source_id == "2003"

    # 5. Unknown table preservation for diagnostics
    assert "UDFTYPE" in bundle.unknown_tables
    assert len(bundle.unknown_tables["UDFTYPE"]) == 1
    assert bundle.unknown_tables["UDFTYPE"][0]["udf_type_name"] == "EPC Area Code"


def test_parse_release_20_pipeline_fixture_with_crlf() -> None:
    """Verify parsing P6 Release 20.x export with CRLF line endings and negative float."""
    fixture_path = FIXTURES_DIR / "p6_release_20_pipeline.xer"
    content = fixture_path.read_bytes()

    bundle = parse_xer_bytes(content)

    assert bundle.source_format_version == "20.12"
    assert bundle.project_name == "Offshore Subsea Pipeline Package"
    assert bundle.data_date == datetime(2026, 10, 31, 18, 0)
    assert len(bundle.activities) == 3
    assert len(bundle.relationships) == 2

    # Negative float verification
    critical_act = next(a for a in bundle.activities if a.code == "LAY-01")
    assert critical_act.total_float_hours == -16.0
    assert critical_act.free_float_hours == -16.0


def test_malformed_empty_file_fails_clearly() -> None:
    """Empty content raises XERParserError with actionable code."""
    with pytest.raises(XERParserError) as exc_info:
        parse_xer_bytes(b"")
    assert exc_info.value.code == "EMPTY_XER_FILE"
    assert "empty" in exc_info.value.message.lower()


def test_malformed_header_fails_clearly() -> None:
    """Non-ERMHDR file raises XERParserError with actionable guidance."""
    corrupted = b"NOT_A_P6_FILE\t1.0\tDATA\n%T\tPROJECT\n"
    with pytest.raises(XERParserError) as exc_info:
        parse_xer_bytes(corrupted)
    assert exc_info.value.code == "INVALID_XER_HEADER"
    assert "ERMHDR" in exc_info.value.message
    assert "Export the project again" in exc_info.value.actionable


def test_multi_encoding_resilience_latin1() -> None:
    """Windows-1252 / Latin-1 encoded characters decode without corruption or crash."""
    fixture_path = FIXTURES_DIR / "latin1_special_chars.xer"
    content = fixture_path.read_bytes()

    bundle = parse_xer_bytes(content)

    assert "Ingénierie" in (bundle.project_name or "")
    act_names = {a.name for a in bundle.activities}
    assert "Étude de faisabilité préliminaire" in act_names
    assert "Montage des pièces préfabriquées" in act_names


def test_missing_optional_tables_parses_gracefully() -> None:
    """XER without CALENDAR or TASKPRED parses remaining tables without crashing."""
    fixture_path = FIXTURES_DIR / "missing_optional_tables.xer"
    content = fixture_path.read_bytes()

    bundle = parse_xer_bytes(content)

    assert bundle.project_name == "Minimal Project Without Optional Tables"
    assert len(bundle.activities) == 2
    assert len(bundle.calendars) == 0
    assert len(bundle.relationships) == 0


def test_unexpected_columns_preserved_in_source_fields() -> None:
    """Unrecognized/custom columns in %F are preserved in source_fields."""
    fixture_path = FIXTURES_DIR / "unexpected_columns.xer"
    content = fixture_path.read_bytes()

    bundle = parse_xer_bytes(content)

    # Project source_metadata holds custom column
    assert bundle.source_metadata.get("custom_client_ref") == "CLIENT-REF-999"

    # Task source_fields holds custom contractor column
    task = bundle.activities[0]
    assert task.source_fields.get("contractor_tag") == "CONTRACTOR-ALPHA"
    assert task.source_fields.get("future_calculated_cost") == "154000.50"


def test_unknown_status_and_relationship_types_generate_warnings() -> None:
    """Unknown statuses or link types do not crash import; they create warnings."""
    xer_content = (
        b"ERMHDR\t8.2\t2026-11-05\n"
        b"%T\tPROJECT\n%F\tproj_id\tproj_short_name\n%R\t1\tTEST-WARN\n"
        b"%T\tTASK\n%F\ttask_id\tproj_id\ttask_code\ttask_name\tstatus_code\n"
        b"%R\t101\t1\tA1\tTask One\tTK_CustomUnknownStatus\n"
        b"%T\tTASKPRED\n%F\ttask_pred_id\ttask_id\tpred_task_id\tpred_type\n"
        b"%R\t501\t101\t101\tPR_CustomRelationshipType\n"
    )

    bundle = parse_xer_bytes(xer_content)

    warning_codes = {w.code for w in bundle.warnings}
    assert "UNKNOWN_ACTIVITY_STATUS" in warning_codes
    assert "UNKNOWN_RELATIONSHIP_TYPE" in warning_codes

    # Raw value is preserved
    assert bundle.activities[0].status == "TK_CustomUnknownStatus"
    assert bundle.relationships[0].relationship_type == "PR_CustomRelationshipType"


def test_orphan_references_generate_diagnostics_warnings() -> None:
    """Tasks referencing non-existent WBS/calendars and orphan relationships create warnings."""
    xer_content = (
        b"ERMHDR\t8.2\t2026-11-05\n"
        b"%T\tPROJECT\n%F\tproj_id\tproj_short_name\n%R\t1\tTEST-ORPHAN\n"
        b"%T\tTASK\n%F\ttask_id\tproj_id\twbs_id\tclndr_id\ttask_code\ttask_name\n"
        b"%R\t101\t1\tNON_EXISTENT_WBS\tNON_EXISTENT_CAL\tA1\tTask One\n"
        b"%T\tTASKPRED\n%F\ttask_pred_id\ttask_id\tpred_task_id\tpred_type\n"
        b"%R\t501\t101\t99999_MISSING_PRED\tPR_FS\n"
    )

    bundle = parse_xer_bytes(xer_content)

    warning_codes = {w.code for w in bundle.warnings}
    assert "ORPHAN_WBS_REFERENCE" in warning_codes
    assert "ORPHAN_CALENDAR_REFERENCE" in warning_codes
    assert "ORPHAN_PREDECESSOR" in warning_codes


def test_large_schedule_performance() -> None:
    """Synthetic schedule with 2,000 tasks and 3,000 links parses under 500ms."""
    lines = [
        "ERMHDR\t8.2\t2026-11-05\tBENCHMARK\tPERF_DB",
        "%T\tPROJECT",
        "%F\tproj_id\tproj_short_name\tproj_name\tlast_recalc_date",
        "%R\t999\tPERF-TEST\tLarge Benchmark Schedule\t2026-11-01 08:00",
        "%T\tPROJWBS",
        "%F\twbs_id\tproj_id\twbs_short_name\twbs_name",
        "%R\t901\t999\tROOT\tBenchmark Root",
        "%T\tTASK",
        "%F\ttask_id\tproj_id\twbs_id\ttask_code\ttask_name\tstatus_code\ttarget_durn\ttotal_float_hr_cnt",
    ]

    for i in range(1, 2001):
        lines.append(f"%R\t{i}\t999\t901\tACT-{i:04d}\tActivity {i}\tTK_NotStart\t80\t16")

    lines.append("%T\tTASKPRED")
    lines.append("%F\ttask_pred_id\ttask_id\tpred_task_id\tpred_type\tlag_hr_cnt")

    for i in range(1, 2000):
        lines.append(f"%R\t{10000 + i}\t{i + 1}\t{i}\tPR_FS\t0")
    for i in range(1, 1001):
        lines.append(f"%R\t{20000 + i}\t{i + 1000}\t{i}\tPR_SS\t8")

    lines.append("%E")
    content = "\n".join(lines).encode("utf-8")

    t0 = time.perf_counter()
    bundle = parse_xer_bytes(content)
    duration = time.perf_counter() - t0

    assert len(bundle.activities) == 2000
    assert len(bundle.relationships) == 2999
    assert duration < 0.50, f"Parsing 2,000 tasks took {duration:.3f}s (must be < 0.50s)"
