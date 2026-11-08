"""Tests for PDF schedule report generation engine (PI-046)."""

import uuid
from datetime import UTC, date, datetime

from app.domains.reporting.pdf_generator import build_schedule_analysis_pdf


def test_build_schedule_analysis_pdf_creates_valid_pdf_bytes() -> None:
    version_id = uuid.uuid4()
    pdf_bytes = build_schedule_analysis_pdf(
        project_name="FPSO Scarborough Topside Integration",
        project_code="FPSO-SCAR-01",
        project_version_id=version_id,
        data_date=date(2026, 8, 30),
        generated_at=datetime.now(UTC),
        generated_by_email="lead_planner@epc-workspace.org",
        metrics={
            "total_activities": 1420,
            "not_started_count": 320,
            "in_progress_count": 890,
            "completed_count": 210,
            "critical_count": 85,
            "planned_start": "2024-01-15",
            "planned_finish": "2027-04-30",
        },
        quality_summary={
            "passed_checks": 12,
            "warning_checks": 2,
            "error_checks": 0,
            "findings": [
                {
                    "category": "missing_logic",
                    "severity": "warning",
                    "rule_id": "ORPHAN_PREDECESSOR",
                    "description": "5 activities lack open predecessor logic",
                },
                {
                    "category": "negative_float",
                    "severity": "warning",
                    "rule_id": "NEGATIVE_TOTAL_FLOAT",
                    "description": "Critical path exhibits -3 days total float",
                },
            ],
        },
        milestone_forecasts=[
            {
                "activity_code": "MS-01",
                "activity_name": "Hull Delivery to Yard",
                "source_finish_date": "2025-06-15",
                "forecast_finish_date": "2025-06-15",
                "variance_days": 0,
                "float_indicator": "critical",
            },
            {
                "activity_code": "MS-02",
                "activity_name": "Module Integration Complete",
                "source_finish_date": "2026-11-20",
                "forecast_finish_date": "2026-12-05",
                "variance_days": 15,
                "float_indicator": "negative_float",
            },
        ],
        options={"include_activity_appendix": False},
    )

    assert isinstance(pdf_bytes, bytes)
    assert len(pdf_bytes) > 2000
    assert pdf_bytes.startswith(b"%PDF-")


def test_build_schedule_analysis_pdf_handles_minimal_or_missing_data() -> None:
    version_id = uuid.uuid4()
    pdf_bytes = build_schedule_analysis_pdf(
        project_name="Subsea Umbilical Tieback",
        project_code="SUB-UMB-09",
        project_version_id=version_id,
        data_date=None,
        generated_at=datetime.now(UTC),
        generated_by_email=None,
        metrics=None,
        quality_summary=None,
        milestone_forecasts=None,
        options={},
    )

    assert isinstance(pdf_bytes, bytes)
    assert len(pdf_bytes) > 1000
    assert pdf_bytes.startswith(b"%PDF-")
