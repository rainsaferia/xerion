"""Unit tests for tabular inspector and reader (PI-022)."""

import io

import openpyxl
from app.adapters.tabular import inspect_tabular_bytes, read_tabular_rows


def test_inspect_csv_comma_delimited() -> None:
    csv_bytes = (
        b"Activity ID,Activity Name,Status,Planned Start,Planned Finish\n"
        b"A101,Site Survey,Completed,2026-01-01,2026-01-10\n"
        b"A102,Site Clearance,Active,2026-01-11,2026-01-20\n"
    )

    inspection = inspect_tabular_bytes(csv_bytes, format_hint="csv")

    assert inspection.format == "csv"
    assert inspection.sheet_names == ["Sheet1"]
    assert inspection.headers == [
        "Activity ID",
        "Activity Name",
        "Status",
        "Planned Start",
        "Planned Finish",
    ]
    assert inspection.total_rows == 2
    assert len(inspection.sample_rows) == 2
    assert inspection.sample_rows[0]["Activity ID"] == "A101"
    assert inspection.sample_rows[1]["Activity Name"] == "Site Clearance"


def test_inspect_csv_semicolon_delimited() -> None:
    csv_bytes = b"Code;Name;Progress\nACT-1;Engineering;100%\nACT-2;Procurement;50%\n"

    inspection = inspect_tabular_bytes(csv_bytes, format_hint="csv")
    assert inspection.headers == ["Code", "Name", "Progress"]
    assert inspection.total_rows == 2
    assert inspection.sample_rows[0]["Code"] == "ACT-1"


def test_inspect_and_read_xlsx_multi_sheet() -> None:
    wb = openpyxl.Workbook()
    # Sheet 1: Activities
    ws1 = wb.active
    ws1.title = "Activities"
    ws1.append(["Task ID", "Task Name", "Duration Hours"])
    ws1.append(["T1", "Civil Foundation", 120])
    ws1.append(["T2", "Steel Structure", 240])

    # Sheet 2: Milestones
    ws2 = wb.create_sheet(title="Milestones")
    ws2.append(["Milestone Code", "Target Date"])
    ws2.append(["M1", "2026-06-30"])

    buf = io.BytesIO()
    wb.save(buf)
    xlsx_bytes = buf.getvalue()

    # Default inspection: inspects sheet 1
    insp1 = inspect_tabular_bytes(xlsx_bytes, format_hint="xlsx")
    assert insp1.format == "xlsx"
    assert insp1.sheet_names == ["Activities", "Milestones"]
    assert insp1.active_sheet == "Activities"
    assert insp1.headers == ["Task ID", "Task Name", "Duration Hours"]
    assert insp1.total_rows == 2
    assert insp1.sample_rows[0]["Task ID"] == "T1"

    # Specific inspection: inspects sheet 2
    insp2 = inspect_tabular_bytes(xlsx_bytes, format_hint="xlsx", sheet_name="Milestones")
    assert insp2.active_sheet == "Milestones"
    assert insp2.headers == ["Milestone Code", "Target Date"]
    assert insp2.total_rows == 1

    # Read rows
    rows = read_tabular_rows(xlsx_bytes, format_hint="xlsx", sheet_name="Activities")
    assert len(rows) == 2
    assert rows[0]["Task ID"] == "T1"
    assert rows[1]["Duration Hours"] == 240
