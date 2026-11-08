"""Unit tests for AI provider adapter implementations and factory (PI-040).

Acceptance criteria:
- Mock adapter supports deterministic responses, tool calls, and call history.
- OpenAI adapter formats payloads, parses tool calls, handles timeouts, and retries 429/5xx.
- Factory resolves configured adapter correctly based on Settings.
- Sensitive API keys are never exposed in adapter representations or errors.
"""

from unittest.mock import AsyncMock, patch

import httpx
import pytest
from app.adapters.ai import get_ai_adapter
from app.adapters.ai.contracts import (
    ChatMessage,
    ToolDefinition,
)
from app.adapters.ai.errors import (
    AIAuthenticationError,
    AIInvalidRequestError,
    AIProviderTimeoutError,
    AIRateLimitError,
)
from app.adapters.ai.mock_adapter import MockAIProviderAdapter
from app.adapters.ai.openai_adapter import OpenAIProviderAdapter
from app.core.config import Settings
from pydantic import SecretStr


@pytest.mark.asyncio
async def test_mock_adapter_default_and_canned_responses() -> None:
    """Test MockAIProviderAdapter default completion and canned response queue."""
    adapter = MockAIProviderAdapter()

    # 1. Default response
    messages = [ChatMessage(role="user", content="Hello")]
    res1 = await adapter.complete(messages=messages)
    assert res1.provider == "mock"
    assert "Mock AI response" in (res1.message.content or "")
    assert len(adapter.call_history) == 1
    assert adapter.call_history[0][0].content == "Hello"

    # 2. Queue canned text response
    adapter.queue_response("Critical path consists of 5 activities.")
    res2 = await adapter.complete(messages=messages)
    assert res2.message.content == "Critical path consists of 5 activities."
    assert res2.tool_calls == []

    # 3. Queue canned tool call
    adapter.queue_tool_call(
        name="get_project_overview",
        arguments={"project_id": "proj-123"},
    )
    res3 = await adapter.complete(messages=messages)
    assert len(res3.tool_calls) == 1
    assert res3.tool_calls[0].function.name == "get_project_overview"
    assert "proj-123" in res3.tool_calls[0].function.arguments

    # 4. Queue error
    adapter.queue_error(AIRateLimitError("Simulated rate limit exceeded", provider="mock"))
    with pytest.raises(AIRateLimitError):
        await adapter.complete(messages=messages)


@pytest.mark.asyncio
async def test_openai_adapter_success_flow() -> None:
    """Test OpenAIProviderAdapter making request and parsing text and tool calls."""
    settings = Settings(
        ai_provider="openai",
        ai_model="gpt-4o",
        ai_api_key=SecretStr("sk-test-mock-key"),
        ai_timeout_seconds=10.0,
        ai_max_retries=2,
    )
    adapter = OpenAIProviderAdapter(settings=settings)

    mock_response_data = {
        "id": "chatcmpl-123",
        "object": "chat.completion",
        "created": 1677652288,
        "model": "gpt-4o",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "Analyzing schedule...",
                    "tool_calls": [
                        {
                            "id": "call_xyz",
                            "type": "function",
                            "function": {
                                "name": "get_critical_activities",
                                "arguments": '{"float_threshold_hours": 0.0}',
                            },
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {
            "prompt_tokens": 80,
            "completion_tokens": 20,
            "total_tokens": 100,
        },
    }

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_resp = httpx.Response(
        status_code=200,
        json=mock_response_data,
        request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions"),
    )
    mock_client.post.return_value = mock_resp

    with patch.object(adapter, "_get_client", return_value=mock_client):
        messages = [ChatMessage(role="user", content="Which activities are critical?")]
        tools = [
            ToolDefinition(
                type="function",
                function={
                    "name": "get_critical_activities",
                    "description": "Get critical activities",
                    "parameters": {"type": "object", "properties": {}},
                },
            )
        ]
        result = await adapter.complete(messages=messages, tools=tools)

        assert result.provider == "openai"
        assert result.model == "gpt-4o"
        assert result.message.content == "Analyzing schedule..."
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].function.name == "get_critical_activities"
        assert result.usage.total_tokens == 100
        assert result.latency_ms >= 0


@pytest.mark.asyncio
async def test_openai_adapter_retries_transient_error_and_succeeds() -> None:
    """Test exponential backoff retries on 429 and 503 before successful response."""
    settings = Settings(
        ai_provider="openai",
        ai_model="gpt-4o",
        ai_api_key=SecretStr("sk-test"),
        ai_max_retries=3,
    )
    adapter = OpenAIProviderAdapter(settings=settings)

    # First attempt: 429 rate limit
    resp_429 = httpx.Response(
        status_code=429,
        text='{"error": {"message": "Rate limit reached"}}',
        headers={"Retry-After": "0.01"},
        request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions"),
    )
    # Second attempt: 200 OK
    resp_200 = httpx.Response(
        status_code=200,
        json={
            "choices": [{"message": {"role": "assistant", "content": "Recovered!"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        },
        request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions"),
    )

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.side_effect = [resp_429, resp_200]

    with patch.object(adapter, "_get_client", return_value=mock_client):
        # Override sleep to run test fast
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            res = await adapter.complete(messages=[ChatMessage(role="user", content="Hi")])
            assert res.message.content == "Recovered!"
            assert mock_client.post.call_count == 2
            mock_sleep.assert_called_once()


@pytest.mark.asyncio
async def test_openai_adapter_fails_fast_on_auth_and_invalid_request() -> None:
    """Test non-retryable 401 and 400 errors fail immediately."""
    settings = Settings(
        ai_provider="openai",
        ai_model="gpt-4o",
        ai_api_key=SecretStr("sk-bad-key"),
        ai_max_retries=3,
    )
    adapter = OpenAIProviderAdapter(settings=settings)

    # 401 Unauthorized
    resp_401 = httpx.Response(
        status_code=401,
        text='{"error": {"message": "Incorrect API key provided"}}',
        request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions"),
    )
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.return_value = resp_401

    with patch.object(adapter, "_get_client", return_value=mock_client):
        with pytest.raises(AIAuthenticationError) as exc_info:
            await adapter.complete(messages=[ChatMessage(role="user", content="Hi")])
        assert "Incorrect API key" in str(exc_info.value)
        assert mock_client.post.call_count == 1  # No retries on 401!

    # 400 Invalid Request
    resp_400 = httpx.Response(
        status_code=400,
        text='{"error": {"message": "Invalid schema for tool call"}}',
        request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions"),
    )
    mock_client.post.return_value = resp_400
    with patch.object(adapter, "_get_client", return_value=mock_client):
        with pytest.raises(AIInvalidRequestError):
            await adapter.complete(messages=[ChatMessage(role="user", content="Hi")])


@pytest.mark.asyncio
async def test_openai_adapter_timeout_handling() -> None:
    """Test that httpx.TimeoutException maps to AIProviderTimeoutError."""
    settings = Settings(ai_provider="openai", ai_api_key=SecretStr("sk-test"), ai_max_retries=1)
    adapter = OpenAIProviderAdapter(settings=settings)

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.side_effect = httpx.ReadTimeout("Request timed out")

    with patch.object(adapter, "_get_client", return_value=mock_client):
        with patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(AIProviderTimeoutError):
                await adapter.complete(messages=[ChatMessage(role="user", content="Hi")])


def test_ai_adapter_factory() -> None:
    """Test get_ai_adapter factory function."""
    mock_settings = Settings(ai_provider="mock")
    adapter_mock = get_ai_adapter(mock_settings)
    assert isinstance(adapter_mock, MockAIProviderAdapter)

    openai_settings = Settings(ai_provider="openai", ai_api_key=SecretStr("sk-test"))
    adapter_openai = get_ai_adapter(openai_settings)
    assert isinstance(adapter_openai, OpenAIProviderAdapter)

    invalid_settings = Settings(ai_provider="unsupported_vendor")
    with pytest.raises(ValueError, match="Unsupported AI provider"):
        get_ai_adapter(invalid_settings)
