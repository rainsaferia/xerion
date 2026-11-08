"""Unit tests for Response Validator (PI-042).

Rules (02_SYSTEM_ARCHITECTURE.md, 05_AI_AGENT_SPEC.md):
- Validates assistant claims against deterministic tool evidence.
- Adds caveat warnings when claims lack supporting evidence.
- Detects missing input / insufficient data conditions.
- Flags misleading probabilistic confidence claims.
"""

import uuid
from typing import Any

from app.domains.ai.evidence import EvidenceReference
from app.domains.ai.validator import ValidatedResponse, validate_assistant_response


def test_validate_verified_response_with_citations() -> None:
    """A response backed by evidence citations is verified."""
    version_id = uuid.uuid4()
    evidence = [
        EvidenceReference(
            project_version_id=version_id,
            entity_type="activity",
            source_identifier="A1010",
            field_name="total_float_hours",
            normalized_value=0.0,
            unit="hours",
            citation_label="[EV: A1010 total_float_hours=0.0h]",
        ),
    ]
    tools_executed: list[dict[str, Any]] = [
        {"tool_name": "get_critical_activities", "status": "completed"}
    ]
    response_text = (
        "Activity A1010 has 0.0 hours float and is currently on the critical path. "
        "[EV: A1010 total_float_hours=0.0h]"
    )

    validated: ValidatedResponse = validate_assistant_response(
        response_text=response_text,
        tools_executed=tools_executed,
        accumulated_evidence=evidence,
    )

    assert validated.validation_status == "verified"
    assert len(validated.evidence_citations) == 1
    assert "[EV: A1010 total_float_hours=0.0h]" in validated.evidence_citations
    assert len(validated.warnings) == 0
    assert validated.content == response_text


def test_validate_insufficient_data_condition() -> None:
    """When a tool failed due to missing inputs or reports not found, status is insufficient."""
    tools_executed: list[dict[str, Any]] = [
        {
            "tool_name": "get_activity_detail",
            "status": "completed",
            "output_summary": {"status": "not_found"},
        }
    ]
    response_text = "Activity A9999 could not be found in the active schedule version."

    validated: ValidatedResponse = validate_assistant_response(
        response_text=response_text,
        tools_executed=tools_executed,
        accumulated_evidence=[],
    )

    assert validated.validation_status == "insufficient_data"
    assert any("INSUFFICIENT_DATA" in w or "not found" in w.lower() for w in validated.warnings)


def test_validate_caveat_for_unevidenced_numerical_claims() -> None:
    """If model asserts specific schedule numbers without tools or evidence, caveat is attached."""
    tools_executed: list[dict[str, Any]] = []  # No tools executed
    response_text = (
        "The project has 52 critical activities and will finish on 2027-10-15 with 140 days delay."
    )

    validated: ValidatedResponse = validate_assistant_response(
        response_text=response_text,
        tools_executed=tools_executed,
        accumulated_evidence=[],
    )

    assert validated.validation_status == "caveated"
    assert len(validated.warnings) >= 1
    assert any("unevidenced" in w.lower() or "unverified" in w.lower() for w in validated.warnings)
    assert "[Audit Caveat]" in validated.content


def test_validate_probabilistic_claim_disclaimer() -> None:
    """If model claims probabilistic confidence without validation, disclaimer is appended."""
    version_id = uuid.uuid4()
    evidence = [
        EvidenceReference(
            project_version_id=version_id,
            entity_type="project_kpi",
            field_name="total_activities",
            normalized_value=100,
            citation_label="[EV: total_activities=100]",
        )
    ]
    tools_executed = [{"tool_name": "get_project_overview", "status": "completed"}]
    response_text = (
        "Based on Monte Carlo simulation, there is an 85% probability "
        "that the project finishes on time."
    )

    validated = validate_assistant_response(
        response_text=response_text,
        tools_executed=tools_executed,
        accumulated_evidence=evidence,
    )

    assert any("probabilistic" in w.lower() for w in validated.warnings)
    assert "deterministic" in validated.content.lower()
