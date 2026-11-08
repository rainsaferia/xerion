"""Tabular file inspector and streaming reader for CSV and XLSX (PI-022)."""

import csv
import io
from dataclasses import dataclass, field
from typing import Any

import openpyxl


@dataclass(slots=True)
class TabularInspection:
    """Inspection summary for tabular uploads."""

    format: str
    sheet_names: list[str]
    active_sheet: str
    headers: list[str]
    sample_rows: list[dict[str, Any]] = field(default_factory=list)
    total_rows: int = 0


def _decode_text(data: bytes) -> str:
    """Decode raw text bytes handling UTF-8, Windows-1252, and Latin-1."""
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        try:
            return data.decode("windows-1252")
        except UnicodeDecodeError:
            return data.decode("latin-1", errors="replace")


def _sniff_delimiter(sample_text: str) -> str:
    """Detect delimiter among standard candidates (comma, semicolon, tab, pipe)."""
    try:
        dialect = csv.Sniffer().sniff(sample_text, delimiters=",;\t|")
        return dialect.delimiter
    except Exception:
        first_line = sample_text.splitlines()[0] if sample_text.splitlines() else ""
        for delim in (",", ";", "\t", "|"):
            if delim in first_line:
                return delim
        return ","


def inspect_tabular_bytes(
    data: bytes, format_hint: str = "csv", sheet_name: str | None = None
) -> TabularInspection:
    """Inspect CSV or XLSX bytes to detect sheets, headers, sample rows, and row counts."""
    fmt = format_hint.lower()
    if fmt == "xlsx":
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        sheet_names = wb.sheetnames
        target_sheet = sheet_name if sheet_name and sheet_name in sheet_names else sheet_names[0]
        ws = wb[target_sheet]

        headers: list[str] = []
        sample_rows: list[dict[str, Any]] = []
        total_rows = 0

        for row_idx, row in enumerate(ws.iter_rows(values_only=True), start=1):
            if row_idx == 1:
                headers = [
                    str(cell).strip() if cell is not None else f"Column_{i + 1}"
                    for i, cell in enumerate(row)
                ]
                continue

            # Skip trailing completely blank rows
            if not any(cell is not None and str(cell).strip() != "" for cell in row):
                continue

            total_rows += 1
            row_dict: dict[str, Any] = {}
            for h_idx, header in enumerate(headers):
                val = row[h_idx] if h_idx < len(row) else None
                row_dict[header] = val

            if len(sample_rows) < 5:
                sample_rows.append(row_dict)

        wb.close()
        return TabularInspection(
            format="xlsx",
            sheet_names=sheet_names,
            active_sheet=target_sheet,
            headers=headers,
            sample_rows=sample_rows,
            total_rows=total_rows,
        )

    # Default to CSV
    text = _decode_text(data)
    delimiter = _sniff_delimiter(text[:4096])
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)

    headers = []
    sample_rows = []
    total_rows = 0

    for row_idx, row in enumerate(reader, start=1):
        if row_idx == 1:
            headers = [
                col.strip() if col.strip() else f"Column_{i + 1}" for i, col in enumerate(row)
            ]
            continue

        if not any(col.strip() for col in row):
            continue

        total_rows += 1
        row_dict = {}
        for h_idx, header in enumerate(headers):
            val = row[h_idx].strip() if h_idx < len(row) else ""
            row_dict[header] = val

        if len(sample_rows) < 5:
            sample_rows.append(row_dict)

    return TabularInspection(
        format="csv",
        sheet_names=["Sheet1"],
        active_sheet="Sheet1",
        headers=headers,
        sample_rows=sample_rows,
        total_rows=total_rows,
    )


def read_tabular_rows(
    data: bytes, format_hint: str = "csv", sheet_name: str | None = None
) -> list[dict[str, Any]]:
    """Stream all data rows from CSV or XLSX as a list of dictionaries."""
    fmt = format_hint.lower()
    if fmt == "xlsx":
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        sheet_names = wb.sheetnames
        target_sheet = sheet_name if sheet_name and sheet_name in sheet_names else sheet_names[0]
        ws = wb[target_sheet]

        headers: list[str] = []
        rows: list[dict[str, Any]] = []

        for row_idx, row in enumerate(ws.iter_rows(values_only=True), start=1):
            if row_idx == 1:
                headers = [
                    str(cell).strip() if cell is not None else f"Column_{i + 1}"
                    for i, cell in enumerate(row)
                ]
                continue

            if not any(cell is not None and str(cell).strip() != "" for cell in row):
                continue

            row_dict: dict[str, Any] = {}
            for h_idx, header in enumerate(headers):
                val = row[h_idx] if h_idx < len(row) else None
                row_dict[header] = val
            rows.append(row_dict)

        wb.close()
        return rows

    # CSV
    text = _decode_text(data)
    delimiter = _sniff_delimiter(text[:4096])
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)

    headers = []
    rows = []

    for row_idx, row in enumerate(reader, start=1):
        if row_idx == 1:
            headers = [
                col.strip() if col.strip() else f"Column_{i + 1}" for i, col in enumerate(row)
            ]
            continue

        if not any(col.strip() for col in row):
            continue

        row_dict = {}
        for h_idx, header in enumerate(headers):
            val = row[h_idx].strip() if h_idx < len(row) else ""
            row_dict[header] = val
        rows.append(row_dict)

    return rows
