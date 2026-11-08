"""AI Provider Adapters module (PI-040).

Rules (02_SYSTEM_ARCHITECTURE.md, 05_AI_AGENT_SPEC.md):
- Exposes standardized AIProviderAdapter protocol and implementations.
- Provides factory get_ai_adapter() configuring the active provider from Settings.
"""

from functools import lru_cache

from pydantic import SecretStr

from app.adapters.ai.base import AIProviderAdapter
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
from app.adapters.ai.mock_adapter import MockAIProviderAdapter
from app.adapters.ai.openai_adapter import OpenAIProviderAdapter
from app.core.config import Settings, get_settings


@lru_cache
def _get_mock_adapter(model: str) -> MockAIProviderAdapter:
    return MockAIProviderAdapter(model=model)


@lru_cache
def _get_openai_adapter(
    model: str,
    api_key: str | None,
    base_url: str | None,
    timeout_seconds: float,
    max_retries: int,
) -> OpenAIProviderAdapter:
    s = Settings(
        ai_provider="openai",
        ai_model=model,
        ai_api_key=SecretStr(api_key) if api_key else None,
        ai_base_url=base_url,
        ai_timeout_seconds=timeout_seconds,
        ai_max_retries=max_retries,
    )
    return OpenAIProviderAdapter(settings=s)


def get_ai_adapter(settings: Settings | None = None) -> AIProviderAdapter:
    """Resolve and return configured AI provider adapter instance."""
    s = settings or get_settings()
    provider = s.ai_provider.lower().strip()

    if provider == "mock":
        return _get_mock_adapter(s.ai_model)
    elif provider == "openai":
        api_key_str = s.ai_api_key.get_secret_value() if s.ai_api_key else None
        return _get_openai_adapter(
            s.ai_model,
            api_key_str,
            s.ai_base_url,
            s.ai_timeout_seconds,
            s.ai_max_retries,
        )
    else:
        raise ValueError(f"Unsupported AI provider: '{s.ai_provider}'. Supported: 'mock', 'openai'")


__all__ = [
    "AIAuthenticationError",
    "AICompletionResult",
    "AIInvalidRequestError",
    "AIProviderAdapter",
    "AIProviderError",
    "AIProviderTimeoutError",
    "AIRateLimitError",
    "AIUsageMetadata",
    "ChatMessage",
    "MockAIProviderAdapter",
    "OpenAIProviderAdapter",
    "ToolCallFunction",
    "ToolCallItem",
    "ToolDefinition",
    "_get_mock_adapter",
    "_get_openai_adapter",
    "get_ai_adapter",
]
