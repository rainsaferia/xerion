"""Unit tests for Evidence Builder (PI-042).

Rules (02_SYSTEM_ARCHITECTURE.md, 05_AI_AGENT_SPEC.md):
- Evidence references conform to Section 7 of 05_AI_AGENT_SPEC.md.
- Extracts verifiable, structured citations from deterministic schedule tool outputs.
- Never invents evidence or relies on unvalidated model claims.
"""

import uuid
from typing import Any

from app.domains.ai.evidence import build_tool_evidence


def test_build_evidence_project_overview() -> None:
    """Test extracting evidence references from get_project_overview output."""
    version_id = uuid.uuid4()
    data: dict[str, Any] = {
        "project_id": str(uuid.uuid4()),
        "project_name": "FPSO Topside Module",
        "version_id": str(version_id),
        "version_number": 2,
        "version_label": "v2",
        "data_date": "2026-03-01",
        "total_activities": 142,
        "activity_status_counts": {
            "not_started": 100,
            "in_progress": 30,
            "complete": 12,
        },
    }

    refs = build_tool_evidence("get_project_overview", version_id, data)
    assert len(refs) >= 3

    # Check total activities reference
    act_ref = next(r for r in refs if r.field_name == "total_activities")
    assert act_ref.entity_type == "project_kpi"
    assert act_ref.project_version_id == version_id
    assert act_ref.normalized_value == 142
    assert act_ref.unit == "count"
    assert "total_activities=142" in act_ref.citation_label

    # Check data date reference
    dd_ref = next(r for r in refs if r.field_name == "data_date")
    assert dd_ref.normalized_value == "2026-03-01"
    assert "data_date=2026-03-01" in dd_ref.citation_label


def test_build_evidence_critical_activities() -> None:
    """Test extracting evidence references from get_critical_activities output."""
    version_id = uuid.uuid4()
    act_id = uuid.uuid4()
    data: dict[str, Any] = {
        "version_id": str(version_id),
        "band": "zero_float",
        "threshold_hours": 0.0,
        "total_exposed": 1,
        "items": [
            {
                "activity_id": str(act_id),
                "activity_code": "A1010",
                "activity_name": "Compressor Foundation Concrete Pour",
                "total_float_hours": 0.0,
                "status": "in_progress",
                "band": "zero_float",
            }
        ],
    }

    refs = build_tool_evidence("get_critical_activities", version_id, data)
    assert len(refs) == 1

    ref = refs[0]
    assert ref.entity_type == "activity"
    assert ref.entity_platform_id == str(act_id)
    assert ref.source_identifier == "A1010"
    assert ref.field_name == "total_float_hours"
    assert ref.normalized_value == 0.0
    assert ref.unit == "hours"
    assert ref.method == "critical_path_total_float"
    assert "[EV: A1010 total_float_hours=0.0h]" == ref.citation_label


def test_build_evidence_activity_detail() -> None:
    """Test extracting evidence references from get_activity_detail output."""
    version_id = uuid.uuid4()
    act_id = uuid.uuid4()
    data: dict[str, Any] = {
        "activity_id": str(act_id),
        "activity_code": "F200",
        "activity_name": "Turbine Alignment",
        "status": "not_started",
        "start_date": "2026-04-01",
        "finish_date": "2026-04-15",
        "total_float_hours": 16.0,
        "remaining_duration_hours": 80.0,
        "baselines": [
            {
                "source_activity_id": "SRC-F200",
                "baseline_start": "2026-03-25",
                "baseline_finish": "2026-04-10",
                "baseline_label": "Project Baseline v1",
            }
        ],
    }

    refs = build_tool_evidence("get_activity_detail", version_id, data)
    assert len(refs) >= 3

    float_ref = next(r for r in refs if r.field_name == "total_float_hours")
    assert float_ref.source_identifier == "F200"
    assert float_ref.normalized_value == 16.0

    bl_ref = next(r for r in refs if r.field_name == "baseline_finish")
    assert bl_ref.normalized_value == "2026-04-10"
    assert bl_ref.entity_type == "baseline"


def test_build_evidence_schedule_quality() -> None:
    """Test extracting evidence references from analyze_schedule_quality output."""
    version_id = uuid.uuid4()
    data: dict[str, Any] = {
        "summary": {
            "total_findings": 2,
            "data_quality_count": 1,
            "schedule_performance_count": 1,
        },
        "findings": [
            {
                "check_code": "CHK-01-OPEN-ENDS",
                "check_name": "Missing Successor Logic",
                "category": "schedule_performance",
                "severity": "high",
                "violation_count": 4,
                "message": "4 activities lack successor dependencies.",
            }
        ],
    }

    refs = build_tool_evidence("analyze_schedule_quality", version_id, data)
    assert len(refs) == 1

    ref = refs[0]
    assert ref.entity_type == "quality_finding"
    assert ref.source_identifier == "CHK-01-OPEN-ENDS"
    assert ref.field_name == "violation_count"
    assert ref.normalized_value == 4
    assert ref.unit == "count"
    assert "[EV: CHK-01-OPEN-ENDS violations=4]" in ref.citation_label


def test_build_evidence_version_comparison() -> None:
    """Test extracting evidence references from compare_project_versions output."""
    version_id = uuid.uuid4()
    data: dict[str, Any] = {
        "summary": {
            "from_version_total": 50,
            "to_version_total": 52,
            "matched": 50,
            "added": 2,
            "removed": 0,
            "changed": 1,
            "unchanged": 49,
            "ambiguous": 0,
        },
        "items": [
            {
                "activity_code": "A300",
                "change_type": "changed",
                "field_changes": [
                    {
                        "field_name": "total_float_hours",
                        "from_value": "40.0",
                        "to_value": "0.0",
                        "delta": -40.0,
                    }
                ],
            }
        ],
    }

    refs = build_tool_evidence("compare_project_versions", version_id, data)
    assert len(refs) >= 1

    ref = refs[0]
    assert ref.entity_type == "version_diff"
    assert ref.source_identifier == "A300"
    assert ref.field_name == "total_float_hours_delta"
    assert ref.normalized_value == -40.0
    assert "[EV: A300 total_float_hours delta=-40.0h]" in ref.citation_label


def test_build_evidence_unknown_tool_or_error() -> None:
    """Unknown tool or error payload returns empty list safely."""
    version_id = uuid.uuid4()
    assert build_tool_evidence("unknown_tool", version_id, {}) == []
    assert build_tool_evidence("get_project_overview", version_id, {"error": "Failed"}) == []
