"""Telemetry and sanitized metadata logging for AI completions (PI-040).

Rules (02_SYSTEM_ARCHITECTURE.md, 05_AI_AGENT_SPEC.md):
- Logs request/response metadata: provider, model, tokens, latency, status, tool names.
- Strictly redacts raw prompt text, user messages, and tool argument payloads.
"""

import logging
from typing import Any

from app.adapters.ai.contracts import AICompletionResult

logger = logging.getLogger("app.adapters.ai.telemetry")


def log_ai_completion_metadata(
    result: AICompletionResult,
    status: str = "completed",
    error_message: str | None = None,
) -> dict[str, Any]:
    """Emit sanitized telemetry log without exposing sensitive project payloads."""
    tool_names = [tc.function.name for tc in result.tool_calls]

    meta = {
        "event": "ai_completion",
        "provider": result.provider,
        "model": result.model,
        "latency_ms": result.latency_ms,
        "prompt_tokens": result.usage.prompt_tokens,
        "completion_tokens": result.usage.completion_tokens,
        "total_tokens": result.usage.total_tokens,
        "tool_call_count": len(result.tool_calls),
        "tool_names": tool_names,
        "status": status,
    }
    if error_message:
        meta["error"] = error_message

    logger.info(
        "AI completion: provider=%s model=%s status=%s latency=%dms tokens=%d tools=%s",
        meta["provider"],
        meta["model"],
        meta["status"],
        meta["latency_ms"],
        meta["total_tokens"],
        tool_names,
        extra=meta,
    )
    return meta
