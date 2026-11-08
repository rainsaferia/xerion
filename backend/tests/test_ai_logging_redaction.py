"""Tests for AI completion metadata logging and payload redaction (PI-040).

Acceptance criteria:
- Request/response metadata logged: provider, model, tokens, latency, status, tool names.
- Raw sensitive project payloads and prompt texts are strictly redacted from logs.
"""

import logging

import pytest
from app.adapters.ai.contracts import (
    AICompletionResult,
    AIUsageMetadata,
    ChatMessage,
    ToolCallFunction,
    ToolCallItem,
)
from app.adapters.ai.telemetry import log_ai_completion_metadata


def test_log_ai_completion_metadata_redacts_sensitive_payloads(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test that telemetry logger outputs metadata but redacts raw sensitive text."""
    confidential_prompt = "TOP SECRET LNG EXPANSION SCHEDULE VENDOR CONFIDENTIAL"
    confidential_output = "CONFIDENTIAL COST AND DELAY DETAILS"

    result = AICompletionResult(
        message=ChatMessage(role="assistant", content=confidential_output),
        tool_calls=[
            ToolCallItem(
                id="call_01",
                type="function",
                function=ToolCallFunction(
                    name="get_project_overview",
                    arguments='{"project_code": "SECRET-LNG"}',
                ),
            )
        ],
        usage=AIUsageMetadata(prompt_tokens=120, completion_tokens=30, total_tokens=150),
        model="gpt-4o",
        provider="openai",
        latency_ms=340,
    )

    with caplog.at_level(logging.INFO, logger="app.adapters.ai.telemetry"):
        log_ai_completion_metadata(
            result=result,
            status="completed",
        )

    log_output = caplog.text

    # Metadata must be present
    assert "openai" in log_output
    assert "gpt-4o" in log_output
    assert "150" in log_output  # total tokens
    assert "340" in log_output  # latency ms
    assert "get_project_overview" in log_output
    assert "completed" in log_output

    # Sensitive payloads must NOT be present
    assert confidential_prompt not in log_output
    assert confidential_output not in log_output
    assert "SECRET-LNG" not in log_output
