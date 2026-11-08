"""Deterministic CSV and XLSX exporter for EPC schedule activities (PI-047)."""

import csv
import io

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from app.domains.reporting.schemas import ActivityExportRow

COLUMNS = [
    ("Activity ID", "source_activity_id"),
    ("Activity Code", "activity_code"),
    ("Activity Name", "activity_name"),
    ("WBS Code", "wbs_code"),
    ("WBS Name", "wbs_name"),
    ("Status", "status"),
    ("Type", "activity_type"),
    ("Planned Start", "planned_start"),
    ("Planned Finish", "planned_finish"),
    ("Actual Start", "actual_start"),
    ("Actual Finish", "actual_finish"),
    ("Original Duration (Hours)", "original_duration_hours"),
    ("Remaining Duration (Hours)", "remaining_duration_hours"),
    ("Actual Duration (Hours)", "actual_duration_hours"),
    ("Total Float (Hours)", "total_float_hours"),
    ("Free Float (Hours)", "free_float_hours"),
    ("Physical % Complete", "physical_pct_complete"),
    ("Calendar", "calendar_name"),
]


def export_activities_to_csv(activities: list[ActivityExportRow]) -> bytes:
    """Generate CSV bytes encoded with UTF-8-BOM for Excel compatibility."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, quoting=csv.QUOTE_MINIMAL)

    # Header row
    writer.writerow([col[0] for col in COLUMNS])

    # Data rows
    for act in activities:
        row = []
        for _, attr in COLUMNS:
            val = getattr(act, attr)
            if val is None:
                row.append("")
            else:
                row.append(str(val))
        writer.writerow(row)

    return buffer.getvalue().encode("utf-8-sig")


def export_activities_to_xlsx(
    activities: list[ActivityExportRow],
    project_code: str = "PROJECT",
    version_label: str = "v1",
) -> bytes:
    """Generate professional, styled Excel XLSX workbook from activities."""
    wb = Workbook()
    ws = wb.active
    if ws is None:
        ws = wb.create_sheet(title="Activities")
    else:
        ws.title = "Activities"

    # Styling definitions
    header_fill = PatternFill(start_color="1E293B", end_color="1E293B", fill_type="solid")
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    data_font = Font(name="Calibri", size=10)
    thin_border_side = Side(border_style="thin", color="CBD5E1")
    data_border = Border(
        left=thin_border_side,
        right=thin_border_side,
        top=thin_border_side,
        bottom=thin_border_side,
    )

    # Header row (row 1)
    headers = [col[0] for col in COLUMNS]
    ws.append(headers)

    for col_idx in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=col_idx)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    # Data rows
    date_attrs = {"planned_start", "planned_finish", "actual_start", "actual_finish"}
    float_attrs = {
        "original_duration_hours",
        "remaining_duration_hours",
        "actual_duration_hours",
        "total_float_hours",
        "free_float_hours",
        "physical_pct_complete",
    }

    for row_idx, act in enumerate(activities, start=2):
        row_vals = []
        for _, attr in COLUMNS:
            val = getattr(act, attr)
            row_vals.append(val)
        ws.append(row_vals)

        for col_idx, (_, attr) in enumerate(COLUMNS, start=1):
            cell = ws.cell(row=row_idx, column=col_idx)
            cell.font = data_font
            cell.border = data_border

            if attr in date_attrs:
                cell.number_format = "yyyy-mm-dd"
                cell.alignment = Alignment(horizontal="center")
            elif attr in float_attrs:
                if attr == "physical_pct_complete":
                    cell.number_format = "0.0%"
                    if cell.value is not None:
                        # Normalize 0..100 to 0..1 for percentage format if > 1
                        if isinstance(cell.value, (int, float)) and cell.value > 1.0:
                            cell.value = cell.value / 100.0
                else:
                    cell.number_format = "#,##0.0"
                cell.alignment = Alignment(horizontal="right")
            elif attr in {"source_activity_id", "activity_code", "status", "activity_type"}:
                cell.alignment = Alignment(horizontal="center")
            else:
                cell.alignment = Alignment(horizontal="left")

    # Auto-adjust column widths
    ws.row_dimensions[1].height = 28
    for col in ws.columns:
        col_letter = get_column_letter(col[0].column)
        max_len = 0
        for cell in col:
            val_str = str(cell.value or "")
            if len(val_str) > max_len:
                max_len = len(val_str)
        ws.column_dimensions[col_letter].width = max(max_len + 4, 12)

    # Freeze panes on header row
    ws.freeze_panes = "A2"

    bio = io.BytesIO()
    wb.save(bio)
    return bio.getvalue()
