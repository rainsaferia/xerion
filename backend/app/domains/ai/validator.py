"""Deterministic AI Response Validator (PI-042).

Rules (02_SYSTEM_ARCHITECTURE.md, 05_AI_AGENT_SPEC.md):
- Validates assistant claims against deterministic tool evidence.
- Flags unevidenced numerical or schedule claims with an explicit audit caveat.
- Identifies missing input or insufficient data conditions.
- Enforces disclaimers against unsupported probabilistic confidence claims.
- Hexagonal domain isolation: zero web framework (fastapi) or vendor adapter dependencies.
"""

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domains.ai.evidence import EvidenceReference


class ValidatedResponse(BaseModel):
    """Result of validating an assistant turn response against evidence (PI-042)."""

    model_config = ConfigDict(frozen=True)

    content: str
    validation_status: Literal["verified", "caveated", "insufficient_data"] = "verified"
    evidence_citations: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


CITATION_REGEX = re.compile(r"\[EV:[^\]]+\]")
DATE_REGEX = re.compile(r"\b20\d{2}[-/]\d{1,2}[-/]\d{1,2}\b")
PROBABILISTIC_TERMS = ("monte carlo", "probability", "confidence interval", "probabilistic")


def validate_assistant_response(
    response_text: str,
    tools_executed: list[dict[str, Any]],
    accumulated_evidence: list[EvidenceReference],
) -> ValidatedResponse:
    """Validate assistant text against executed tools and accumulated evidence references."""
    citations = CITATION_REGEX.findall(response_text)
    warnings: list[str] = []
    final_content = response_text
    status: Literal["verified", "caveated", "insufficient_data"] = "verified"

    # 1. Check for insufficient data / missing input
    has_not_found = any(
        isinstance(t.get("output_summary"), dict)
        and t.get("output_summary", {}).get("status") == "not_found"
        for t in tools_executed
    )
    has_failed_tools = any(t.get("status") == "failed" for t in tools_executed)

    if (
        has_not_found
        or has_failed_tools
        or "could not be found" in response_text.lower()
        or "insufficient data" in response_text.lower()
        or "not available" in response_text.lower()
    ):
        status = "insufficient_data"
        warnings.append(
            "INSUFFICIENT_DATA: Requested items were not found or lack required inputs."
        )

    # 2. Check for probabilistic confidence claims
    lower_text = response_text.lower()
    if any(term in lower_text for term in PROBABILISTIC_TERMS):
        disclaimer = (
            "\n\n> [Deterministic Schedule Note] Forward projections are deterministic CPM "
            "schedule calculations derived from Primavera P6 logic, not probabilistic or "
            "statistical Monte Carlo forecasts."
        )
        if "[Deterministic Schedule Note]" not in final_content:
            final_content += disclaimer
        warnings.append(
            "Probabilistic claim detected; appended deterministic projection disclaimer."
        )

    # 3. Check for unevidenced numerical claims
    # If no tools were executed or no evidence exists, but response claims dates or float/metrics
    has_numbers = bool(
        re.search(r"\b\d+(\.\d+)?\s*(days?|hours?|activities|critical)\b", lower_text)
    )
    has_dates = bool(DATE_REGEX.search(response_text))

    if (
        (not tools_executed or not accumulated_evidence)
        and (has_numbers or has_dates)
        and status != "insufficient_data"
    ):
        status = "caveated"
        caveat = (
            "\n\n> [Audit Caveat] Certain schedule numbers or dates in this response could "
            "not be verified against deterministic domain tool evidence."
        )
        if "[Audit Caveat]" not in final_content:
            final_content += caveat
        warnings.append("Unevidenced schedule claims detected without supporting tool evidence.")

    return ValidatedResponse(
        content=final_content,
        validation_status=status,
        evidence_citations=citations,
        warnings=warnings,
    )
