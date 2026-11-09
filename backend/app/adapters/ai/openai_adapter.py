"""OpenAI-compatible AI Provider Adapter (PI-040).

Rules (02_SYSTEM_ARCHITECTURE.md, 05_AI_AGENT_SPEC.md):
- Standard OpenAI Chat Completions endpoint integration via httpx.AsyncClient.
- Handles tool calling payload formatting and response parsing.
- Implements exponential backoff retries for transient 429 and 5xx errors.
- Maps error statuses to typed domain exceptions.
- Never reveals API keys in error messages or logs.
"""

import asyncio
import contextlib
import time
from typing import Any

import httpx

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
from app.adapters.ai.telemetry import log_ai_completion_metadata
from app.core.config import Settings


class OpenAIProviderAdapter:
    """OpenAI-compatible provider adapter with resilience and tool calling."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.provider = "openai"
        self.model = settings.ai_model
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.settings.ai_timeout_seconds)
        return self._client

    async def aclose(self) -> None:
        """Close underlying HTTP client session."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    def _build_payload(
        self,
        messages: list[ChatMessage],
        tools: list[ToolDefinition] | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        formatted_messages: list[dict[str, Any]] = []
        for msg in messages:
            entry: dict[str, Any] = {"role": msg.role}
            if msg.content is not None:
                entry["content"] = msg.content
            if msg.name:
                entry["name"] = msg.name
            if msg.tool_call_id:
                entry["tool_call_id"] = msg.tool_call_id
            if msg.tool_calls:
                entry["tool_calls"] = [
                    tc.model_dump() if hasattr(tc, "model_dump") else tc for tc in msg.tool_calls
                ]
            formatted_messages.append(entry)

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": formatted_messages,
            "temperature": temperature,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if self.settings.ai_reasoning_effort:
            payload["reasoning_effort"] = self.settings.ai_reasoning_effort
        if tools:
            payload["tools"] = [
                t.model_dump() if hasattr(t, "model_dump") else t for t in tools
            ]
        return payload

    async def complete(
        self,
        messages: list[ChatMessage],
        tools: list[ToolDefinition] | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> AICompletionResult:
        """Execute chat completion with exponential backoff retries."""
        api_key = self.settings.ai_api_key.get_secret_value() if self.settings.ai_api_key else ""
        base_url = (self.settings.ai_base_url or "https://api.openai.com/v1").rstrip("/")
        url = f"{base_url}/chat/completions"

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = self._build_payload(
            messages=messages,
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        client = self._get_client()
        max_retries = self.settings.ai_max_retries
        start_time = time.perf_counter()

        for attempt in range(max_retries + 1):
            try:
                resp = await client.post(url, headers=headers, json=payload)
            except httpx.TimeoutException as exc:
                if attempt >= max_retries:
                    raise AIProviderTimeoutError(
                        f"OpenAI request timed out after {self.settings.ai_timeout_seconds}s",
                        provider=self.provider,
                    ) from exc
                await asyncio.sleep(min(0.5 * (2**attempt), 8.0))
                continue
            except httpx.RequestError as exc:
                if attempt >= max_retries:
                    raise AIProviderError(
                        f"Network transport error: {exc}",
                        provider=self.provider,
                    ) from exc
                await asyncio.sleep(min(0.5 * (2**attempt), 8.0))
                continue

            latency_ms = int((time.perf_counter() - start_time) * 1000)

            # Success
            if resp.status_code == 200:
                data = resp.json()
                choice = data["choices"][0]
                msg_data = choice["message"]

                parsed_tool_calls: list[ToolCallItem] = []
                if "tool_calls" in msg_data and msg_data["tool_calls"]:
                    for tc in msg_data["tool_calls"]:
                        fn = tc["function"]
                        parsed_tool_calls.append(
                            ToolCallItem(
                                id=tc["id"],
                                type="function",
                                function=ToolCallFunction(
                                    name=fn["name"],
                                    arguments=fn["arguments"],
                                ),
                            )
                        )

                raw_usage = data.get("usage", {})
                usage = AIUsageMetadata(
                    prompt_tokens=raw_usage.get("prompt_tokens", 0),
                    completion_tokens=raw_usage.get("completion_tokens", 0),
                    total_tokens=raw_usage.get("total_tokens", 0),
                )

                result = AICompletionResult(
                    message=ChatMessage(
                        role="assistant",
                        content=msg_data.get("content"),
                        tool_calls=parsed_tool_calls if parsed_tool_calls else None,
                    ),
                    tool_calls=parsed_tool_calls,
                    usage=usage,
                    model=data.get("model", self.model),
                    provider=self.provider,
                    latency_ms=latency_ms,
                )
                log_ai_completion_metadata(result, status="completed")
                return result

            # Retryable errors
            if resp.status_code == 429:
                retry_header = resp.headers.get("Retry-After")
                retry_after = float(retry_header) if retry_header else min(0.5 * (2**attempt), 8.0)
                if attempt >= max_retries:
                    raise AIRateLimitError(
                        "OpenAI rate limit or quota exceeded",
                        provider=self.provider,
                        retry_after_seconds=retry_after,
                    )
                await asyncio.sleep(retry_after)
                continue

            if resp.status_code in (500, 502, 503, 504):
                if attempt >= max_retries:
                    raise AIProviderError(
                        f"OpenAI server error (HTTP {resp.status_code})",
                        provider=self.provider,
                        status_code=resp.status_code,
                    )
                await asyncio.sleep(min(0.5 * (2**attempt), 8.0))
                continue

            # Non-retryable errors
            err_msg = resp.text
            with contextlib.suppress(Exception):
                err_json = resp.json()
                if isinstance(err_json, dict) and "error" in err_json:
                    err_payload = err_json["error"]
                    if isinstance(err_payload, dict) and "message" in err_payload:
                        err_msg = str(err_payload["message"])

            if resp.status_code in (401, 403):
                raise AIAuthenticationError(
                    f"Authentication failed with OpenAI: {err_msg}",
                    provider=self.provider,
                    status_code=resp.status_code,
                )
            if resp.status_code == 400:
                raise AIInvalidRequestError(
                    f"Invalid request to OpenAI: {err_msg}",
                    provider=self.provider,
                    status_code=400,
                )

            raise AIProviderError(
                f"OpenAI error (HTTP {resp.status_code}): {err_msg}",
                provider=self.provider,
                status_code=resp.status_code,
            )

        raise AIProviderError("Exhausted retries without response", provider=self.provider)
