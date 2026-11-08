"""Exception types for AI provider adapters (PI-040).

Rules (02_SYSTEM_ARCHITECTURE.md, 05_AI_AGENT_SPEC.md):
- Structured errors distinguishing transient issues (rate limit, timeout) from non-retryable errors.
- Never logs or exposes raw API keys in exception messages.
"""


class AIProviderError(Exception):
    """Base exception for all AI provider adapter failures."""

    def __init__(
        self,
        message: str,
        provider: str | None = None,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.provider = provider
        self.status_code = status_code

    def __str__(self) -> str:
        provider_str = f"[{self.provider}] " if self.provider else ""
        code_str = f" (status={self.status_code})" if self.status_code else ""
        return f"{provider_str}{self.message}{code_str}"


class AIAuthenticationError(AIProviderError):
    """Authentication or authorization failure with AI provider (e.g. invalid API key)."""


class AIRateLimitError(AIProviderError):
    """Provider rate limit or quota exceeded (HTTP 429)."""

    def __init__(
        self,
        message: str,
        provider: str | None = None,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(message, provider=provider, status_code=429)
        self.retry_after_seconds = retry_after_seconds


class AIProviderTimeoutError(AIProviderError):
    """Network connection or execution timeout communicating with AI provider."""


class AIInvalidRequestError(AIProviderError):
    """Malformed request payload, invalid model, or context window exceeded."""
