"""Deterministic in-memory AI adapter for testing and local development (PI-040).

Rules (02_SYSTEM_ARCHITECTURE.md, 05_AI_AGENT_SPEC.md):
- Supports repeatable, hermetic tests without hitting external LLM endpoints.
- Allows queuing canned text responses, tool calls, and simulated errors.
- Records all message conversations in call_history for assertions.
"""

import json
import uuid
from typing import Any

from app.adapters.ai.contracts import (
    AICompletionResult,
    AIUsageMetadata,
    ChatMessage,
    ToolCallFunction,
    ToolCallItem,
    ToolDefinition,
)
from app.adapters.ai.telemetry import log_ai_completion_metadata


class MockAIProviderAdapter:
    """Mock implementation of AIProviderAdapter protocol."""

    def __init__(self, model: str = "mock-model") -> None:
        self.model = model
        self.provider = "mock"
        self.call_history: list[list[ChatMessage]] = []
        self._queue: list[AICompletionResult | Exception] = []

    def queue_response(
        self,
        content: str,
        prompt_tokens: int = 10,
        completion_tokens: int = 10,
    ) -> None:
        """Queue a canned textual completion response."""
        result = AICompletionResult(
            message=ChatMessage(role="assistant", content=content),
            tool_calls=[],
            usage=AIUsageMetadata(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
            ),
            model=self.model,
            provider=self.provider,
            latency_ms=10,
        )
        self._queue.append(result)

    def queue_tool_call(
        self,
        name: str,
        arguments: dict[str, Any] | str,
        call_id: str | None = None,
        assistant_content: str | None = None,
        prompt_tokens: int = 20,
        completion_tokens: int = 15,
    ) -> None:
        """Queue a canned tool call invocation response."""
        args_str = arguments if isinstance(arguments, str) else json.dumps(arguments)
        cid = call_id or f"call_{uuid.uuid4().hex[:8]}"
        tool_call = ToolCallItem(
            id=cid,
            type="function",
            function=ToolCallFunction(name=name, arguments=args_str),
        )
        result = AICompletionResult(
            message=ChatMessage(
                role="assistant",
                content=assistant_content,
                tool_calls=[tool_call],
            ),
            tool_calls=[tool_call],
            usage=AIUsageMetadata(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
            ),
            model=self.model,
            provider=self.provider,
            latency_ms=15,
        )
        self._queue.append(result)

    def queue_error(self, error: Exception) -> None:
        """Queue a simulated provider exception (e.g. rate limit, timeout)."""
        self._queue.append(error)

    def clear(self) -> None:
        """Clear call history and queued items."""
        self.call_history.clear()
        self._queue.clear()

    async def complete(
        self,
        messages: list[ChatMessage],
        tools: list[ToolDefinition] | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> AICompletionResult:
        """Execute mock completion, recording history and popping queued responses."""
        self.call_history.append(list(messages))

        if self._queue:
            item = self._queue.pop(0)
            if isinstance(item, Exception):
                raise item
            log_ai_completion_metadata(item, status="completed")
            return item

        # Default fallback response if queue is empty
        res = AICompletionResult(
            message=ChatMessage(
                role="assistant",
                content=f"Mock AI response for {len(messages)} messages.",
            ),
            tool_calls=[],
            usage=AIUsageMetadata(
                prompt_tokens=25,
                completion_tokens=10,
                total_tokens=35,
            ),
            model=self.model,
            provider=self.provider,
            latency_ms=5,
        )
        log_ai_completion_metadata(res, status="completed")
        return res
