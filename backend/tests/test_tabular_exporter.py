"""Tests for CSV and XLSX tabular activity export (PI-047)."""

import csv
import io
from datetime import date

import openpyxl
import pytest
from app.domains.reporting.schemas import ActivityExportRow
from app.domains.reporting.tabular_exporter import (
    export_activities_to_csv,
    export_activities_to_xlsx,
)


@pytest.fixture
def sample_activity_rows() -> list[ActivityExportRow]:
    return [
        ActivityExportRow(
            source_activity_id="ACT-100",
            activity_code="A1000",
            activity_name="Site Clearing & Grading",
            wbs_code="1.1",
            wbs_name="Civil Works",
            status="complete",
            activity_type="Task Dependent",
            planned_start=date(2026, 1, 10),
            planned_finish=date(2026, 1, 20),
            actual_start=date(2026, 1, 10),
            actual_finish=date(2026, 1, 19),
            original_duration_hours=80.0,
            remaining_duration_hours=0.0,
            actual_duration_hours=72.0,
            total_float_hours=16.0,
            free_float_hours=8.0,
            physical_pct_complete=100.0,
            calendar_name="Standard 5-Day",
        ),
        ActivityExportRow(
            source_activity_id="ACT-200",
            activity_code="A2000",
            activity_name="Turbine Foundation Pour",
            wbs_code="1.2",
            wbs_name="Power Island",
            status="in_progress",
            activity_type="Task Dependent",
            planned_start=date(2026, 1, 21),
            planned_finish=date(2026, 2, 15),
            actual_start=date(2026, 1, 22),
            actual_finish=None,
            original_duration_hours=200.0,
            remaining_duration_hours=120.0,
            actual_duration_hours=80.0,
            total_float_hours=-24.0,
            free_float_hours=0.0,
            physical_pct_complete=40.0,
            calendar_name="Standard 5-Day",
        ),
    ]


def test_export_activities_to_csv(sample_activity_rows: list[ActivityExportRow]) -> None:
    csv_bytes = export_activities_to_csv(sample_activity_rows)

    # Must start with UTF-8 BOM
    assert csv_bytes.startswith(b"\xef\xbb\xbf")

    # Read back as string with utf-8-sig
    content = csv_bytes.decode("utf-8-sig")
    reader = csv.reader(io.StringIO(content))
    rows = list(reader)

    assert len(rows) == 3  # Header + 2 data rows
    headers = rows[0]
    assert "Activity ID" in headers
    assert "Original Duration (Hours)" in headers
    assert "Total Float (Hours)" in headers
    assert "WBS Code" in headers

    row1 = rows[1]
    assert row1[0] == "ACT-100"
    assert row1[1] == "A1000"
    assert row1[2] == "Site Clearing & Grading"
    assert row1[5] == "complete"
    assert row1[7] == "2026-01-10"

    row2 = rows[2]
    assert row2[0] == "ACT-200"
    assert row2[10] == ""  # actual_finish is None
    assert row2[14] == "-24.0"  # total_float_hours


def test_export_activities_to_xlsx(sample_activity_rows: list[ActivityExportRow]) -> None:
    xlsx_bytes = export_activities_to_xlsx(
        sample_activity_rows, project_code="EPC-PRJ", version_label="v1"
    )

    # Valid ZIP / XLSX header
    assert xlsx_bytes.startswith(b"PK")

    # Load with openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(xlsx_bytes))
    assert "Activities" in wb.sheetnames
    ws = wb["Activities"]

    assert ws.max_row == 3
    assert ws.max_column == 18

    # Verify header
    assert ws.cell(row=1, column=1).value == "Activity ID"
    assert ws.cell(row=1, column=12).value == "Original Duration (Hours)"

    # Verify row 2 data
    assert ws.cell(row=2, column=1).value == "ACT-100"
    assert ws.cell(row=2, column=2).value == "A1000"
    val_date = ws.cell(row=2, column=8).value
    assert (hasattr(val_date, "date") and val_date.date() == date(2026, 1, 10)) or val_date == date(
        2026, 1, 10
    )

    # Verify row 3 negative float
    assert ws.cell(row=3, column=15).value == -24.0
