"""Project metadata validation rules.

Rules (01_PRD.md FR-003, 06_API_SPEC.md Section 3, 08_DEVELOPMENT_BACKLOG.md PI-011):
- Required timezone must be a valid IANA timezone.
- Currency code must be 3-letter ISO-4217 uppercase.
- Project name must be non-empty string <= 255 chars.
"""

import re
import zoneinfo

_CURRENCY_PATTERN = re.compile(r"^[A-Z]{3}$")


def validate_timezone(tz: str) -> str:
    """Validate that the timezone string is a recognized IANA time zone identifier."""
    cleaned = tz.strip()
    if not cleaned:
        raise ValueError("Timezone cannot be empty.")
    if cleaned not in zoneinfo.available_timezones():
        # Attempt fallback check with ZoneInfo directly in case of case-normalized alias
        try:
            zoneinfo.ZoneInfo(cleaned)
        except Exception:
            raise ValueError(
                f"Invalid IANA timezone: '{cleaned}'. "
                "Must be a recognized IANA time zone identifier (e.g., 'Asia/Jakarta', 'UTC')."
            ) from None
    return cleaned


def validate_currency_code(code: str | None) -> str | None:
    """Validate that the currency code is a 3-letter ISO-4217 uppercase code."""
    if code is None:
        return None
    cleaned = code.strip().upper()
    if not cleaned:
        return None
    if not _CURRENCY_PATTERN.match(cleaned):
        raise ValueError(
            f"Invalid currency code: '{code}'. Must be a 3-letter ISO 4217 code (e.g. 'USD')."
        )
    return cleaned


def validate_project_name(name: str) -> str:
    """Validate project name."""
    cleaned = name.strip()
    if not cleaned:
        raise ValueError("Project name cannot be empty.")
    if len(cleaned) > 255:
        raise ValueError("Project name cannot exceed 255 characters.")
    return cleaned
