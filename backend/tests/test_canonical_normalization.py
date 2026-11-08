"""PI-021: Canonical normalization unit and integration tests.

Acceptance criteria:
- Parsed objects map to canonical Pydantic models.
- Source IDs and source field references are retained.
- Unknown statuses/types do not crash import; they create warnings.
- Invalid date ranges and orphan links are reported.
"""

from datetime import date
from pathlib import Path

from app.adapters.p6_xer import parse_xer_bytes
from app.domains.ingestion.normalization import normalize_schedule_bundle
from app.domains.schedule.schemas import (
    CanonicalActivity,
    CanonicalCalendar,
    CanonicalProjectSchedule,
    CanonicalRelationship,
    CanonicalWBS,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "xer"


def test_normalization_maps_parsed_xer_to_canonical_models() -> None:
    """PI-021: Parsed objects map to canonical Pydantic models."""
    fixture_path = FIXTURES_DIR / "p6_release_82_facility.xer"
    content = fixture_path.read_bytes()
    bundle = parse_xer_bytes(content)

    schedule = normalize_schedule_bundle(bundle)

    assert isinstance(schedule, CanonicalProjectSchedule)
    assert schedule.source_format == "xer"
    assert schedule.source_format_version == "8.2"
    assert schedule.source_project_key == "1001"
    assert schedule.project_name == "Gas Processing Facility EPC"
    assert schedule.data_date == date(2026, 11, 1)

    # 1. Calendars
    assert len(schedule.calendars) == 2
    for cal in schedule.calendars:
        assert isinstance(cal, CanonicalCalendar)
        assert cal.source_id in ("501", "502")

    # 2. WBS
    assert len(schedule.wbs_nodes) == 4
    for wbs in schedule.wbs_nodes:
        assert isinstance(wbs, CanonicalWBS)
        assert wbs.wbs_code is not None

    # 3. Activities
    assert len(schedule.activities) == 5
    for act in schedule.activities:
        assert isinstance(act, CanonicalActivity)
        assert act.status in ("not_started", "in_progress", "complete")

    # 4. Relationships
    assert len(schedule.relationships) == 5
    for rel in schedule.relationships:
        assert isinstance(rel, CanonicalRelationship)
        assert rel.relationship_type in ("FS", "SS", "FF", "SF")


def test_retention_of_source_ids_and_fields() -> None:
    """PI-021: Source IDs and source field references are retained."""
    raw_data = {
        "source_format": "xer",
        "wbs_nodes": [
            {
                "source_id": "WBS_10",
                "wbs_code": "1.0",
                "wbs_name": "Engineering",
                "source_fields": {"raw_wbs_owner": "ENG_LEAD", "oracle_internal_id": 9912},
            }
        ],
        "activities": [
            {
                "source_id": "ACT_901",
                "activity_code": "E-100",
                "activity_name": "P&ID Development",
                "wbs_source_id": "WBS_10",
                "status": "in_progress",
                "source_fields": {
                    "contractor_vendor": "EPC_PARTNER_A",
                    "sap_po_number": "PO-882194",
                    "custom_budget_code": "CAPEX-01",
                },
            }
        ],
    }

    schedule = normalize_schedule_bundle(raw_data)

    act = schedule.activities[0]
    assert act.source_id == "ACT_901"
    assert act.wbs_source_id == "WBS_10"
    assert act.source_fields["contractor_vendor"] == "EPC_PARTNER_A"
    assert act.source_fields["sap_po_number"] == "PO-882194"

    wbs = schedule.wbs_nodes[0]
    assert wbs.source_id == "WBS_10"
    assert wbs.source_fields["raw_wbs_owner"] == "ENG_LEAD"


def test_unknown_status_and_relationship_types_create_warnings_without_crashing() -> None:
    """PI-021: Unknown statuses/types do not crash import; they create warnings."""
    raw_data = {
        "source_format": "xer",
        "activities": [
            {
                "source_id": "A1",
                "activity_code": "TASK-1",
                "activity_name": "Task with unknown status",
                "status": "TK_SUPER_CUSTOM_ON_HOLD",
            },
            {
                "source_id": "A2",
                "activity_code": "TASK-2",
                "activity_name": "Task 2",
                "status": "not_started",
            },
        ],
        "relationships": [
            {
                "source_id": "R1",
                "predecessor_source_id": "A1",
                "successor_source_id": "A2",
                "relationship_type": "PR_UNKNOWN_ELASTIC_LINK",
            }
        ],
    }

    schedule = normalize_schedule_bundle(raw_data)

    # Activity status mapped to 'unknown', source_status preserved
    act1 = schedule.activities[0]
    assert act1.status == "unknown"
    assert act1.source_status == "TK_SUPER_CUSTOM_ON_HOLD"

    # Relationship type mapped to 'unknown', source_type preserved
    rel = schedule.relationships[0]
    assert rel.relationship_type == "unknown"
    assert rel.source_relationship_type == "PR_UNKNOWN_ELASTIC_LINK"

    # Warnings emitted
    warn_codes = {w.code for w in schedule.warnings}
    assert "UNKNOWN_ACTIVITY_STATUS" in warn_codes
    assert "UNKNOWN_RELATIONSHIP_TYPE" in warn_codes


def test_invalid_date_ranges_are_reported() -> None:
    """PI-021: Invalid date ranges are reported as warnings."""
    raw_data = {
        "source_format": "xer",
        "activities": [
            {
                "source_id": "A1",
                "activity_code": "BAD-DATES",
                "activity_name": "Activity with reversed planned dates",
                "planned_start": "2026-05-15",
                "planned_finish": "2026-05-01",  # Finish before start!
                "actual_start": "2026-06-10",
                "actual_finish": "2026-06-01",  # Actual finish before actual start!
            }
        ],
    }

    schedule = normalize_schedule_bundle(raw_data)

    warn_codes = {w.code for w in schedule.warnings}
    assert "INVALID_DATE_RANGE" in warn_codes
    assert "INVALID_ACTUAL_DATE_RANGE" in warn_codes

    date_warn = next(w for w in schedule.warnings if w.code == "INVALID_DATE_RANGE")
    assert "planned_start" in date_warn.message
    assert "after planned_finish" in date_warn.message


def test_orphan_links_and_self_loops_are_reported() -> None:
    """PI-021: Orphan links and self-loops are reported as warnings."""
    raw_data = {
        "source_format": "xer",
        "activities": [
            {
                "source_id": "A100",
                "activity_code": "VALID-TASK",
                "activity_name": "Valid Activity",
            }
        ],
        "relationships": [
            # 1. Missing predecessor
            {
                "source_id": "R1",
                "predecessor_source_id": "MISSING_PRED_999",
                "successor_source_id": "A100",
                "relationship_type": "FS",
            },
            # 2. Missing successor
            {
                "source_id": "R2",
                "predecessor_source_id": "A100",
                "successor_source_id": "MISSING_SUCC_888",
                "relationship_type": "FS",
            },
            # 3. Self-loop
            {
                "source_id": "R3",
                "predecessor_source_id": "A100",
                "successor_source_id": "A100",
                "relationship_type": "FS",
            },
        ],
    }

    schedule = normalize_schedule_bundle(raw_data)

    warn_codes = {w.code for w in schedule.warnings}
    assert "ORPHAN_PREDECESSOR_LINK" in warn_codes
    assert "ORPHAN_SUCCESSOR_LINK" in warn_codes
    assert "SELF_LOOP_RELATIONSHIP" in warn_codes

    orphan_pred = next(w for w in schedule.warnings if w.code == "ORPHAN_PREDECESSOR_LINK")
    assert orphan_pred.details["predecessor_source_id"] == "MISSING_PRED_999"

    self_loop = next(w for w in schedule.warnings if w.code == "SELF_LOOP_RELATIONSHIP")
    assert "connects activity 'A100' to itself" in self_loop.message


def test_orphan_wbs_and_calendar_references_are_reported() -> None:
    """Orphan WBS and Calendar references on activities generate warnings."""
    raw_data = {
        "source_format": "xer",
        "wbs_nodes": [{"source_id": "WBS_EXISTING", "wbs_name": "Root"}],
        "calendars": [{"source_id": "CAL_EXISTING", "calendar_name": "Default"}],
        "activities": [
            {
                "source_id": "ACT_1",
                "activity_code": "A1",
                "activity_name": "Task 1",
                "wbs_source_id": "WBS_NON_EXISTENT",
                "calendar_source_id": "CAL_NON_EXISTENT",
            }
        ],
    }

    schedule = normalize_schedule_bundle(raw_data)

    warn_codes = {w.code for w in schedule.warnings}
    assert "ORPHAN_WBS_REFERENCE" in warn_codes
    assert "ORPHAN_CALENDAR_REFERENCE" in warn_codes
