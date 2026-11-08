"""Upload safety and file signature verification (PI-012).

Rules (01_PRD.md FR-004, 02_SYSTEM_ARCHITECTURE.md Section 10, 08_DEVELOPMENT_BACKLOG.md PI-012):
- Only supported extensions accepted: .xer, .xlsx, .csv.
- Actual file signature (magic bytes) verified after upload.
- Malicious/executable content masquerading as schedule files rejected.
- Size limit checked.
- SHA-256 checksum calculated.
"""

import hashlib
import re
from pathlib import Path

SUPPORTED_FORMATS: dict[str, str] = {
    ".xer": "xer",
    ".xlsx": "xlsx",
    ".csv": "csv",
}

RESERVED_DEVICE_NAMES: set[str] = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def sanitize_upload_filename(filename: str) -> str:
    """Sanitize uploaded filename preventing path traversal, device names, and control chars.

    Rules:
    - Strips directory components (/ and \\).
    - Removes control characters and null bytes.
    - Rejects hidden files (starting with dot).
    - Rejects Windows reserved device names (CON, PRN, AUX, NUL, COM1-9, LPT1-9).
    - Enforces length bounds (1..255 chars).
    - Validates extension against supported schedule formats (.xer, .xlsx, .csv).
    """
    if not filename or not isinstance(filename, str):
        raise ValueError("Filename must be a non-empty string.")

    # Remove null bytes and control characters
    raw = "".join(c for c in filename if ord(c) >= 32 and ord(c) != 127)

    # Split on both / and \ to strip any path components
    parts = re.split(r"[\\/]", raw)
    clean_name = parts[-1].strip()

    if not clean_name or clean_name in {".", ".."}:
        raise ValueError("Invalid or empty filename after path sanitization.")

    if clean_name.startswith("."):
        raise ValueError("Hidden filenames starting with '.' are forbidden.")

    if len(clean_name) > 255:
        raise ValueError("Filename exceeds maximum length of 255 characters.")

    # Check reserved device names (before extension)
    stem = Path(clean_name).stem.upper()
    if stem in RESERVED_DEVICE_NAMES:
        raise ValueError(f"Filename '{clean_name}' contains a reserved system device name.")

    # Validate that extension is recognized and supported
    detect_and_validate_extension(clean_name)

    return clean_name


# Zip signature for .xlsx files
ZIP_MAGIC = b"PK\x03\x04"
# Primavera P6 XER header
XER_MAGIC = b"ERMHDR"
XER_BOM_MAGIC = b"\xef\xbb\xbfERMHDR"


def detect_and_validate_extension(filename: str) -> str:
    """Validate file extension and return canonical source_format ('xer', 'xlsx', 'csv')."""
    clean_name = filename.strip()
    suffix = Path(clean_name).suffix.lower()
    if suffix not in SUPPORTED_FORMATS:
        raise ValueError(
            f"Unsupported file extension '{suffix}'. Supported formats: .xer, .xlsx, .csv."
        )
    return SUPPORTED_FORMATS[suffix]


def compute_sha256(data: bytes) -> str:
    """Compute 64-character lowercase hexadecimal SHA-256 checksum."""
    return hashlib.sha256(data).hexdigest()


def verify_file_signature(data: bytes, source_format: str) -> None:
    """Inspect actual magic bytes to prevent masquerading binaries or corrupt uploads."""
    if len(data) == 0:
        raise ValueError("Uploaded file is empty (0 bytes).")

    if source_format == "xer":
        # Primavera P6 XER must begin with ERMHDR
        if not (data.startswith(XER_MAGIC) or data.startswith(XER_BOM_MAGIC)):
            raise ValueError(
                "Invalid XER file signature. File does not start with Primavera ERMHDR header."
            )

    elif source_format == "xlsx":
        # Office Open XML (.xlsx) is a ZIP package starting with PK\x03\x04
        if not data.startswith(ZIP_MAGIC):
            raise ValueError(
                "Invalid XLSX file signature. File is not a valid Office Open XML ZIP package."
            )

    elif source_format == "csv":
        # CSV must be text; binary files with null bytes (\x00) are forbidden
        # Check first 8KB for null bytes
        sample = data[:8192]
        if b"\x00" in sample:
            raise ValueError(
                "Invalid CSV file. Binary content or null bytes detected in text file."
            )
        try:
            # Must be decodable as UTF-8 or latin-1 text
            sample.decode("utf-8")
        except UnicodeDecodeError:
            try:
                sample.decode("latin-1")
            except Exception:
                raise ValueError("Invalid CSV file. Content is not valid text.") from None

    else:
        raise ValueError(f"Unknown source format '{source_format}'.")


def validate_file_payload(
    data: bytes,
    filename: str,
    max_size_bytes: int,
) -> tuple[str, int, str]:
    """Validate filename safety, extension, size limit, and signature.

    Returns (source_format, size, sha256).
    """
    clean_name = sanitize_upload_filename(filename)
    source_format = detect_and_validate_extension(clean_name)

    file_size = len(data)
    if file_size > max_size_bytes:
        raise ValueError(
            f"File size ({file_size} bytes) exceeds maximum limit ({max_size_bytes} bytes)."
        )

    verify_file_signature(data, source_format)
    checksum = compute_sha256(data)

    return source_format, file_size, checksum
