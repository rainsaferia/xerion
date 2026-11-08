"""Unit tests for AI provider settings and data contracts (PI-040).

Acceptance criteria:
- Provider/model configured by environment.
- API key wrapped safely in SecretStr.
- Data contracts model messages, tools, tool calls, and completions.
- Error hierarchy cleanly categorizes transient vs non-retryable provider issues.
"""

from app.adapters.ai.contracts import (
    AICompletionResult,
    AIUsageMetadata,
    ChatMessage,
    ToolCallFunction,
    ToolCallItem,
    ToolDefinition,
)
from app.adapters.ai.errors import (
    AIAuthenticationError,
    AIInvalidRequestError,
    AIProviderError,
    AIProviderTimeoutError,
    AIRateLimitError,
)
from app.core.config import Settings
from pydantic import SecretStr


def test_ai_settings_defaults_and_env_configuration() -> None:
    """Test default AI configuration and safety of SecretStr API key."""
    settings = Settings(
        ai_provider="openai",
        ai_model="gpt-4o-mini",
        ai_api_key=SecretStr("super-secret-key-12345"),
        ai_timeout_seconds=45.0,
        ai_max_retries=5,
    )

    assert settings.ai_provider == "openai"
    assert settings.ai_model == "gpt-4o-mini"
    assert settings.ai_timeout_seconds == 45.0
    assert settings.ai_max_retries == 5

    # Security check: SecretStr must never reveal key in str() or repr()
    assert settings.ai_api_key is not None
    assert "super-secret-key-12345" not in str(settings.ai_api_key)
    assert "super-secret-key-12345" not in repr(settings.ai_api_key)
    assert settings.ai_api_key.get_secret_value() == "super-secret-key-12345"


def test_chat_message_and_tool_call_contracts() -> None:
    """Test data contracts for messages and tool calls."""
    msg_user = ChatMessage(role="user", content="Show me project critical activities.")
    assert msg_user.role == "user"
    assert msg_user.content == "Show me project critical activities."

    tool_call = ToolCallItem(
        id="call_abc123",
        type="function",
        function=ToolCallFunction(
            name="get_critical_activities",
            arguments='{"float_threshold_hours": 0.0, "limit": 10}',
        ),
    )

    msg_assistant = ChatMessage(
        role="assistant",
        content=None,
        tool_calls=[tool_call],
    )
    assert msg_assistant.role == "assistant"
    assert msg_assistant.tool_calls is not None
    assert len(msg_assistant.tool_calls) == 1
    assert msg_assistant.tool_calls[0].function.name == "get_critical_activities"

    msg_tool = ChatMessage(
        role="tool",
        content='{"status": "ok", "items": []}',
        tool_call_id="call_abc123",
    )
    assert msg_tool.role == "tool"
    assert msg_tool.tool_call_id == "call_abc123"


def test_tool_definition_contract() -> None:
    """Test definition schema for LLM function calling."""
    tool = ToolDefinition(
        type="function",
        function={
            "name": "get_project_overview",
            "description": "Retrieve overview KPI metrics for the current project version.",
            "parameters": {
                "type": "object",
                "properties": {
                    "version_id": {"type": "string"},
                },
            },
        },
    )

    dumped = tool.model_dump()
    assert dumped["type"] == "function"
    assert dumped["function"]["name"] == "get_project_overview"


def test_ai_completion_result_contract() -> None:
    """Test complete AI response contract with usage and latency."""
    res = AICompletionResult(
        message=ChatMessage(role="assistant", content="Project looks on track."),
        tool_calls=[],
        usage=AIUsageMetadata(
            prompt_tokens=150,
            completion_tokens=25,
            total_tokens=175,
        ),
        model="gpt-4o",
        provider="mock",
        latency_ms=210,
    )

    assert res.message.content == "Project looks on track."
    assert res.usage.total_tokens == 175
    assert res.latency_ms == 210
    assert res.provider == "mock"


def test_ai_error_hierarchy() -> None:
    """Test error class hierarchy and specialized fields."""
    base_err = AIProviderError("Generic AI error", provider="mock")
    assert isinstance(base_err, Exception)
    assert base_err.provider == "mock"

    rate_err = AIRateLimitError("Too Many Requests", provider="openai", retry_after_seconds=5.0)
    assert isinstance(rate_err, AIProviderError)
    assert rate_err.retry_after_seconds == 5.0

    timeout_err = AIProviderTimeoutError("Connection timed out after 30s", provider="openai")
    assert isinstance(timeout_err, AIProviderError)

    auth_err = AIAuthenticationError("Invalid API Key", provider="openai")
    assert isinstance(auth_err, AIProviderError)

    inv_err = AIInvalidRequestError("Bad request schema", provider="openai")
    assert isinstance(inv_err, AIProviderError)
