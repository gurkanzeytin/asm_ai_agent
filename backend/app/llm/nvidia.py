import asyncio
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import openai

from app.llm.exceptions import (
    LLMAuthenticationError,
    LLMConnectionError,
    LLMException,
    LLMRateLimitError,
    LLMResponseError,
    LLMTimeoutError,
)
from app.llm.interfaces import ILLMProvider
from app.llm.remote_policy import enforce_remote_data_policy
from app.llm.schemas import LLMResponse

logger = logging.getLogger(__name__)

# Errors worth a bounded retry: transient network/availability conditions.
# Authentication and bad-request errors are never retried — the same
# credentials/payload will fail again identically.
_RETRIABLE_EXCEPTIONS = (
    openai.APITimeoutError,
    openai.APIConnectionError,
    openai.RateLimitError,
    openai.InternalServerError,
)


@dataclass(frozen=True)
class NvidiaModelProfile:
    """Per-model request shape and defaults for a NVIDIA NIM-hosted model.

    All NVIDIA models share one client, one API key, and one base URL — only
    the request payload built for ``chat.completions.create`` differs. Adding
    a new model means adding a profile entry here, never a new provider class.
    """

    model_id: str
    supports_thinking: bool
    supports_streaming: bool
    supports_structured_output: bool
    default_temperature: float
    default_top_p: float
    recommended_max_tokens: int
    extra_body: dict[str, Any] | None = field(default=None)
    # Name of the chat_template_kwargs key used to toggle reasoning mode for this
    # model. DeepSeek uses "thinking"; Nemotron uses "enable_thinking". Only ever
    # read when `supports_thinking` is True, so models that never think (GLM) are
    # unaffected by this default.
    thinking_key: str = field(default="thinking")


def _deepseek_profile(model_id: str) -> NvidiaModelProfile:
    """Legacy/default profile: mirrors the provider's pre-multi-model behavior exactly.

    Temperature/top_p/max_tokens are read from settings (not fixed constants) so
    existing NVIDIA_TEMPERATURE/NVIDIA_TOP_P/NVIDIA_MAX_TOKENS overrides keep working
    for DeepSeek and for any unrecognized model id, unchanged from before this profile
    system existed.
    """
    from app.core.config import settings

    return NvidiaModelProfile(
        model_id=model_id,
        supports_thinking=True,
        supports_streaming=False,
        supports_structured_output=True,
        default_temperature=settings.NVIDIA_TEMPERATURE,
        default_top_p=settings.NVIDIA_TOP_P,
        recommended_max_tokens=settings.NVIDIA_MAX_TOKENS,
        extra_body=None,
    )


def _glm_profile(model_id: str) -> NvidiaModelProfile:
    """GLM-5.2 profile: NVIDIA's officially documented request-compatible defaults.

    Deliberately omits DeepSeek's ``chat_template_kwargs.thinking`` extra_body —
    that field is unverified for GLM's NVIDIA endpoint and must not be sent
    until NVIDIA's GLM documentation explicitly confirms support for it.
    """
    from app.core.config import settings

    return NvidiaModelProfile(
        model_id=model_id,
        supports_thinking=False,
        supports_streaming=False,
        supports_structured_output=True,
        default_temperature=1.0,
        default_top_p=1.0,
        recommended_max_tokens=settings.NVIDIA_MAX_TOKENS,
        extra_body=None,
    )


def _nemotron_profile(model_id: str) -> NvidiaModelProfile:
    """Nemotron 3 Ultra profile: verified working NVIDIA-hosted model for genuinely
    complex insight-generation tasks (see app.insights.routing).

    Fixed defaults per the verified smoke test (temperature=0.1, top_p=0.95,
    max_tokens=1024) rather than the shared NVIDIA_* settings, so this profile's
    request shape is stable regardless of what another model's settings override
    to. Reasoning is toggled via ``chat_template_kwargs.enable_thinking`` — a
    different key than DeepSeek's ``thinking`` — so ``thinking_key`` distinguishes
    the two; ``_build_extra_body`` never sends both.
    """
    return NvidiaModelProfile(
        model_id=model_id,
        supports_thinking=True,
        supports_streaming=False,
        supports_structured_output=True,
        default_temperature=0.1,
        default_top_p=0.95,
        recommended_max_tokens=1024,
        extra_body=None,
        thinking_key="enable_thinking",
    )


# Exact model_id -> profile factory. Unrecognized model ids fall back to
# `_deepseek_profile`, preserving this provider's original behavior for any
# custom/experimental NVIDIA model string.
#
# DeepSeek V4 Pro is intentionally NOT the default NVIDIA_MODEL (see
# app.core.settings) because its NVIDIA endpoint currently returns 404; its
# profile remains registered only so an explicit, deliberate selection keeps
# working. GPT-OSS-120B and GLM-5.2 are reachable but too slow for active
# insight routing and are likewise never selected by default.
_NVIDIA_MODEL_PROFILE_FACTORIES: dict[str, Any] = {
    "deepseek-ai/deepseek-v4-pro": _deepseek_profile,
    "z-ai/glm-5.2": _glm_profile,
    "nvidia/nemotron-3-ultra-550b-a55b": _nemotron_profile,
}


def resolve_nvidia_model_profile(model_id: str) -> NvidiaModelProfile:
    """Derives the request profile for a NVIDIA model id, defaulting to DeepSeek's shape."""
    factory = _NVIDIA_MODEL_PROFILE_FACTORIES.get(model_id, _deepseek_profile)
    return factory(model_id)


class NvidiaProvider(ILLMProvider):
    """NVIDIA NIM (OpenAI-compatible) API implementation of the ILLMProvider abstraction.

    Uses ``openai.AsyncOpenAI`` pointed at NVIDIA's `integrate.api.nvidia.com` endpoint.
    This is a remote, non-local provider: every outgoing request is screened by
    ``app.llm.remote_policy`` before it leaves the process, rejecting any prompt
    that references patient-level or direct/indirect personal identifiers.
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout: float | None = None,
        retry_count: int | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        thinking: bool | None = None,
    ):
        from app.core.config import settings
        from app.shared.exceptions import ConfigurationError

        self.api_key = (
            api_key if api_key is not None else settings.NVIDIA_API_KEY.get_secret_value()
        )
        self.base_url = (base_url or settings.NVIDIA_BASE_URL).rstrip("/")
        self.model = model or settings.NVIDIA_MODEL
        self.profile = resolve_nvidia_model_profile(self.model)
        self.timeout = timeout if timeout is not None else settings.NVIDIA_TIMEOUT_SECONDS
        self.retry_count = retry_count if retry_count is not None else settings.NVIDIA_MAX_RETRIES
        self.max_tokens = (
            max_tokens if max_tokens is not None else self.profile.recommended_max_tokens
        )
        self.temperature = (
            temperature if temperature is not None else self.profile.default_temperature
        )
        self.top_p = top_p if top_p is not None else self.profile.default_top_p
        self.thinking_default = (
            thinking
            if thinking is not None
            else (self.profile.supports_thinking and settings.NVIDIA_THINKING)
        )

        if not self.api_key:
            logger.critical(
                "Startup validation error: NVIDIA provider selected but NVIDIA_API_KEY is missing."
            )
            raise ConfigurationError("NVIDIA provider selected but NVIDIA_API_KEY is missing.")

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        self._client_loop = loop
        self._cached_client = self._build_client()

        logger.info(
            "NVIDIA provider initialized\n"
            f"model={self.model}\n"
            f"base_url={self.base_url}\n"
            f"thinking_default={self.thinking_default}\n"
            f"api_key_present={bool(self.api_key)}"
        )

    def _build_client(self) -> openai.AsyncOpenAI:
        # Internal SDK retries are disabled (max_retries=0); this provider runs
        # its own small bounded retry loop below so attempt counts are observable.
        return openai.AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=self.timeout,
            max_retries=0,
        )

    @property
    def _client(self) -> openai.AsyncOpenAI:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if not hasattr(self, "_client_loop") or self._client_loop is not loop:
            self._client_loop = loop
            self._cached_client = self._build_client()
        return self._cached_client

    def _build_extra_body(self, thinking: bool) -> dict[str, Any] | None:
        """Builds the model-specific ``extra_body`` payload, or ``None`` if the
        active model's profile declares no request-specific extras.

        The reasoning-toggle key name (``thinking`` for DeepSeek, ``enable_thinking``
        for Nemotron) comes from ``self.profile.thinking_key`` and is only ever sent
        for models whose profile marks ``supports_thinking=True`` — never assumed
        for a model unless NVIDIA's documentation confirms it accepts the field.
        Each call rebuilds this dict fresh from the currently active profile, so a
        model-specific key can never leak into a request for a different model.
        """
        extra_body: dict[str, Any] = dict(self.profile.extra_body or {})
        if self.profile.supports_thinking:
            extra_body["chat_template_kwargs"] = {self.profile.thinking_key: thinking}
        return extra_body or None

    async def generate(
        self,
        prompt: str,
        think: bool = True,
        options: dict[str, Any] | None = None,
    ) -> LLMResponse:
        """Sends a chat completion request to the NVIDIA API with bounded retries.

        ``prompt`` is sent as a single user message, matching how prompts are
        pre-rendered (system + user combined) elsewhere in this codebase. Pass
        ``options={"system": "..."}`` to add a separate system message.
        """
        options = options or {}

        messages: list[dict[str, str]] = options.get("messages") or []
        if not messages:
            system_prompt = options.get("system")
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})

        enforce_remote_data_policy(*(message.get("content", "") for message in messages))

        temperature = options.get("temperature", self.temperature)
        top_p = options.get("top_p", self.top_p)
        max_tokens = options.get("max_tokens") or options.get("num_predict") or self.max_tokens
        # `think=False` always disables reasoning regardless of configuration;
        # `think=True` (the default) defers to the configured deployment default.
        effective_thinking = self.thinking_default if think else False

        retries = self.retry_count
        backoff = 0.5
        last_exception: Exception | None = None
        response = None
        start_time = time.perf_counter()
        request_timestamp = datetime.now(UTC).isoformat()
        attempts_used = 0

        for attempt in range(retries + 1):
            attempts_used = attempt + 1
            try:
                logger.debug(
                    "NVIDIA API request starting",
                    extra={
                        "attempt": attempt + 1,
                        "total_attempts": retries + 1,
                        "model": self.model,
                        "thinking": effective_thinking,
                    },
                )
                response = await self._client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=temperature,
                    top_p=top_p,
                    max_tokens=max_tokens,
                    timeout=self.timeout,
                    extra_body=self._build_extra_body(effective_thinking),
                )
                last_exception = None
                break
            except openai.AuthenticationError as e:
                # Non-retriable: the same credentials will fail again identically.
                logger.error(f"NVIDIA authentication failed: {e}")
                raise LLMAuthenticationError(f"NVIDIA authentication failed: {e}") from e
            except openai.BadRequestError as e:
                logger.error(f"NVIDIA rejected the request: {e}")
                raise LLMResponseError(f"NVIDIA returned a bad request error: {e}") from e
            except _RETRIABLE_EXCEPTIONS as e:
                last_exception = e
                if attempt == retries:
                    break
                logger.warning(
                    f"Transient NVIDIA API error on attempt {attempt + 1}/{retries + 1}: {e}. "
                    f"Retrying in {backoff}s..."
                )
                await asyncio.sleep(backoff)
                backoff *= 2
            except openai.APIStatusError as e:
                logger.error(f"NVIDIA API returned non-retriable status error: {e}")
                raise LLMResponseError(f"NVIDIA API returned an error status: {e}") from e
            except openai.OpenAIError as e:
                logger.error(f"Unexpected NVIDIA client error: {e}")
                raise LLMException(f"Unexpected error in NVIDIA provider: {e}") from e

        if last_exception is not None:
            if isinstance(last_exception, openai.APITimeoutError):
                logger.error(f"NVIDIA request timed out after {attempts_used} attempt(s).")
                raise LLMTimeoutError(
                    f"NVIDIA request timed out after {attempts_used} attempt(s): {last_exception}"
                ) from last_exception
            if isinstance(last_exception, openai.APIConnectionError):
                logger.error(f"NVIDIA connection failed after {attempts_used} attempt(s).")
                raise LLMConnectionError(
                    f"NVIDIA connection failed after {attempts_used} attempt(s): {last_exception}"
                ) from last_exception
            if isinstance(last_exception, openai.RateLimitError):
                logger.error(f"NVIDIA rate limit exceeded after {attempts_used} attempt(s).")
                raise LLMRateLimitError(
                    f"NVIDIA rate limit exceeded after {attempts_used} attempt(s): {last_exception}"
                ) from last_exception
            logger.error(
                f"NVIDIA request failed after {attempts_used} attempt(s): {last_exception}"
            )
            raise LLMException(
                f"NVIDIA request failed after {attempts_used} attempt(s): {last_exception}"
            ) from last_exception

        if response is None or not response.choices:
            raise LLMResponseError("NVIDIA returned a response with no choices.")

        choice = response.choices[0]
        response_content = (choice.message.content or "").strip() if choice.message else ""
        if not response_content:
            raise LLMResponseError("NVIDIA returned an empty completion.")

        latency_ms = (time.perf_counter() - start_time) * 1000
        usage = response.usage
        prompt_tokens = usage.prompt_tokens if usage else None
        completion_tokens = usage.completion_tokens if usage else None
        finish_reason_raw = choice.finish_reason
        finish_reason = "stop" if finish_reason_raw == "stop" else (finish_reason_raw or "other")
        if finish_reason_raw == "length":
            finish_reason = "max_tokens"

        log_extra = {
            "provider": "nvidia",
            "model": self.model,
            "model_name": self.model,
            "latency_ms": latency_ms,
            "latency": latency_ms,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "finish_reason": finish_reason,
            "request_timestamp": request_timestamp,
            "prompt_length": len(prompt),
            "response_length": len(response_content),
            "retry_count": attempts_used - 1,
            "thinking": effective_thinking,
        }
        logger.info("LLM request completed successfully", extra=log_extra)

        return LLMResponse(
            content=response_content,
            model=self.model,
            latency_ms=latency_ms,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            finish_reason=finish_reason,
        )

    async def stream_generate(self, prompt: str) -> AsyncIterator[LLMResponse]:
        """Asynchronously streams generated responses. Not implemented in this version."""
        raise NotImplementedError("Streaming is not yet implemented for NvidiaProvider.")
        yield  # type: ignore # unreachable, makes Python treat it as a generator

    async def health_check(self) -> bool:
        """Verifies the NVIDIA provider is configured, without making a network call."""
        return bool(self.api_key)

    def get_metadata(self) -> dict[str, Any]:
        """Returns diagnostic metadata about the current NVIDIA provider configuration."""
        return {
            "provider": "nvidia",
            "model": self.model,
            "base_url": self.base_url,
            "timeout": self.timeout,
            "retry_count": self.retry_count,
            "thinking_default": self.thinking_default,
            "model_profile": {
                "supports_thinking": self.profile.supports_thinking,
                "supports_streaming": self.profile.supports_streaming,
                "supports_structured_output": self.profile.supports_structured_output,
                "default_temperature": self.profile.default_temperature,
                "default_top_p": self.profile.default_top_p,
                "recommended_max_tokens": self.profile.recommended_max_tokens,
                "thinking_key": (
                    self.profile.thinking_key if self.profile.supports_thinking else None
                ),
            },
            "capabilities": {
                "streaming": False,
                "text_generation": True,
                "embeddings": False,
                "remote": True,
            },
        }

    async def close(self) -> None:
        """Cleanly disposes of the persistent HTTP client."""
        await self._client.close()

    async def embed(self, text: str) -> list[float]:
        """NVIDIA embeddings are not part of this integration; use OllamaProvider for embeddings."""
        raise NotImplementedError(
            "Embeddings are not implemented for NvidiaProvider; the Ollama provider remains "
            "the embedding source for schema retrieval."
        )
