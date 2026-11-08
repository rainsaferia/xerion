"""Canonical data contracts for AI provider adapters (PI-040).

Rules (02_SYSTEM_ARCHITECTURE.md, 05_AI_AGENT_SPEC.md):
- Decouples downstream AI orchestrator from vendor-specific payloads.
- Strictly models roles, messages, tools, tool calls, token usage, and completions.
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Role = Literal[
    "system",
    "developer",
    "user",
    "assistant",
    "tool",
]


class ToolCallFunction(BaseModel):
    """Function call invocation name and serialized arguments."""

    model_config = ConfigDict(frozen=True)

    name: str
    arguments: str


class ToolCallItem(BaseModel):
    """Standardized tool call item matching OpenAI function calling spec."""

    model_config = ConfigDict(frozen=True)

    id: str
    type: Literal["function"] = "function"
    function: ToolCallFunction


class ChatMessage(BaseModel):
    """Canonical chat message exchanged with an AI provider."""

    model_config = ConfigDict(frozen=True)

    role: Role
    content: str | None = None
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[ToolCallItem] | None = None


class ToolDefinition(BaseModel):
    """Tool schema declaration exposed to the LLM."""

    model_config = ConfigDict(frozen=True)

    type: Literal["function"] = "function"
    function: dict[str, Any]


class AIUsageMetadata(BaseModel):
    """Token usage counters returned by the provider."""

    model_config = ConfigDict(frozen=True)

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class AICompletionResult(BaseModel):
    """Standardized result returned by AIProviderAdapter implementations."""

    model_config = ConfigDict(frozen=True)

    message: ChatMessage
    tool_calls: list[ToolCallItem] = Field(default_factory=list)
    usage: AIUsageMetadata = Field(default_factory=AIUsageMetadata)
    model: str
    provider: str
    latency_ms: int
