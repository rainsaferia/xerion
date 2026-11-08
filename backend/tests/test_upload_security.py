"""PI-051: Upload abuse limits and download security headers tests."""

import uuid

import pytest
from app.domains.ingestion.safety import (
    sanitize_upload_filename,
    validate_file_payload,
)
from app.main import create_app
from httpx import ASGITransport, AsyncClient


def test_sanitize_filename_valid() -> None:
    assert sanitize_upload_filename("baseline_rev1.xer") == "baseline_rev1.xer"
    assert (
        sanitize_upload_filename("Schedule Update - Oct 2026.xlsx")
        == "Schedule Update - Oct 2026.xlsx"
    )
    assert sanitize_upload_filename("export.csv") == "export.csv"


@pytest.mark.parametrize(
    "filename,expected",
    [
        ("../../etc/passwd.xer", "passwd.xer"),
        ("..\\..\\windows\\system32\\cmd.xer", "cmd.xer"),
        ("/opt/data/uploads/upload.xlsx", "upload.xlsx"),
        ("c:\\projects\\subfolder\\schedule.xer", "schedule.xer"),
    ],
)
def test_sanitize_filename_path_traversal_stripped(filename: str, expected: str) -> None:
    assert sanitize_upload_filename(filename) == expected


@pytest.mark.parametrize(
    "bad_filename,error_match",
    [
        ("", "Filename must be a non-empty string"),
        ("   ", "Invalid or empty filename"),
        ("..", "Invalid or empty filename"),
        ("../../", "Invalid or empty filename"),
        (".hidden.xer", "Hidden filenames"),
        (".env.csv", "Hidden filenames"),
        ("con.xer", "reserved system device name"),
        ("PRN.xlsx", "reserved system device name"),
        ("aux.csv", "reserved system device name"),
        ("nul.xer", "reserved system device name"),
        ("com1.xer", "reserved system device name"),
        ("lpt3.csv", "reserved system device name"),
        ("payload.exe", "Unsupported file extension"),
        ("script.sh", "Unsupported file extension"),
        ("malicious.php", "Unsupported file extension"),
        ("a" * 256 + ".xer", "exceeds maximum length"),
    ],
)
def test_sanitize_filename_rejects_abusive_names(bad_filename: str, error_match: str) -> None:
    with pytest.raises(ValueError, match=error_match):
        sanitize_upload_filename(bad_filename)


def test_sanitize_filename_removes_null_bytes_and_control_chars() -> None:
    dirty = "safe\x00file\x07name.xer"
    cleaned = sanitize_upload_filename(dirty)
    assert cleaned == "safefilename.xer"
    assert "\x00" not in cleaned


def test_magic_bytes_detection_rejects_masquerading_files() -> None:
    # An executable or text masquerading as .xlsx
    fake_xlsx = b"#!/bin/bash\necho hello"
    with pytest.raises(ValueError, match="Invalid XLSX file signature"):
        validate_file_payload(fake_xlsx, "fake.xlsx", 1024 * 1024)

    # An invalid .xer
    fake_xer = b"NOT_ERMHDR_CONTENT"
    with pytest.raises(ValueError, match="Invalid XER file signature"):
        validate_file_payload(fake_xer, "fake.xer", 1024 * 1024)

    # Binary with null byte masquerading as .csv
    binary_csv = b"col1,col2\nval1,\x00\x01\x02"
    with pytest.raises(ValueError, match="Binary content or null bytes detected"):
        validate_file_payload(binary_csv, "binary.csv", 1024 * 1024)


async def test_upload_session_rejects_path_traversal_filename() -> None:
    app = create_app()
    # Path traversal that reduces to empty or reserved
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Without auth returns 401
        res = await client.post(
            f"/api/v1/projects/{uuid.uuid4()}/uploads",
            json={"filename": "../../.hidden.xer", "file_size_bytes": 100},
        )
        assert res.status_code == 401
