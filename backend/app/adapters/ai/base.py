"""Abstract protocol for AI provider adapters (PI-040).

Rules (02_SYSTEM_ARCHITECTURE.md, 05_AI_AGENT_SPEC.md):
- Decouples AI orchestrator from concrete model provider APIs.
- Supports messages, tools/function definitions, temperature, and tokens.
"""

from typing import Protocol, runtime_checkable

from app.adapters.ai.contracts import AICompletionResult, ChatMessage, ToolDefinition


@runtime_checkable
class AIProviderAdapter(Protocol):
    """Protocol for AI completion providers (OpenAI, Mock, Azure, etc.)."""

    async def complete(
        self,
        messages: list[ChatMessage],
        tools: list[ToolDefinition] | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> AICompletionResult:
        """Execute chat completion and return standardized result."""
        ...
