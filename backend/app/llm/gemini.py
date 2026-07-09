import asyncio
from collections.abc import AsyncIterator
from datetime import datetime, timezone
import logging
import time
from typing import Any, Optional

from google import genai
from google.genai import types
from google.genai.errors import APIError

from app.llm.exceptions import (
    LLMConnectionError,
    LLMException,
    LLMResponseError,
    LLMTimeoutError,
)
from app.llm.interfaces import ILLMProvider
from app.llm.schemas import LLMResponse

logger = logging.getLogger(__name__)


class GeminiProvider(ILLMProvider):
    """Google Gemini API implementation of the ILLMProvider abstraction using the official Google GenAI SDK."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
    ):
        """Initializes the Gemini provider using configuration settings or explicit options."""
        from app.core.config import settings
        from app.shared.exceptions import ConfigurationError

        self.api_key = api_key or settings.GEMINI_API_KEY
        self.model = model or settings.GEMINI_MODEL

        # Fail fast if API key is missing
        if not self.api_key:
            logger.critical("Startup validation error: Gemini provider selected but GEMINI_API_KEY is missing.")
            raise ConfigurationError("Gemini provider selected but GEMINI_API_KEY is missing.")

        # Initialize cached client and loop association immediately
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        self._client_loop = loop
        self._cached_client = genai.Client(api_key=self.api_key)

        # Log diagnostics prefix/presence safely
        api_key_exists = bool(self.api_key)
        key_prefix = "N/A"
        if api_key_exists and len(self.api_key) >= 2:
            key_prefix = f"{self.api_key[:2]}..."
        elif api_key_exists:
            key_prefix = "..."

        logger.info(
            "Gemini initialized\n"
            f"model={self.model}\n"
            f"api_key_present={api_key_exists}\n"
            f"key_prefix={key_prefix}"
        )

    @property
    def _client(self) -> genai.Client:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if not hasattr(self, "_client_loop") or self._client_loop is not loop:
            self._client_loop = loop
            self._cached_client = genai.Client(api_key=self.api_key)
        return self._cached_client

    async def generate(
        self,
        prompt: str,
        think: bool = True,
        options: Optional[dict[str, Any]] = None,
    ) -> LLMResponse:
        """Asynchronously sends a generation request to the Gemini API with structured metrics extraction."""
        if not self.api_key:
            raise LLMConnectionError("Gemini API key is not configured.")

        # Log parameter support warnings
        if think:
            logger.debug("GeminiProvider: 'think' parameter is unsupported by Gemini and has been ignored.")

        # Map client options to GenerateContentConfig
        config_args = {}
        if options:
            if "temperature" in options:
                config_args["temperature"] = float(options["temperature"])
            if "num_predict" in options:
                val = int(options["num_predict"])
                config_args["max_output_tokens"] = 1024 if val == 200 else val
            if "max_tokens" in options:
                val = int(options["max_tokens"])
                config_args["max_output_tokens"] = 1024 if val == 200 else val

        config = types.GenerateContentConfig(**config_args)
        start_time = time.perf_counter()
        request_timestamp = datetime.now(timezone.utc).isoformat()

        # Log effective GenerateContentConfig before request (DEBUG only)
        logger.debug(
            "Gemini Client sending request with GenerateContentConfig:\n"
            f"  - model: {self.model}\n"
            f"  - temperature: {getattr(config, 'temperature', None)}\n"
            f"  - max_output_tokens: {getattr(config, 'max_output_tokens', None)}\n"
            f"  - top_p: {getattr(config, 'top_p', None)}\n"
            f"  - top_k: {getattr(config, 'top_k', None)}\n"
            f"  - stop_sequences: {getattr(config, 'stop_sequences', None)}"
        )

        try:
            logger.debug(
                "Gemini API request starting",
                extra={
                    "model": self.model,
                    "payload_config": config_args,
                },
            )
            # Call async unified Client .aio interface
            response = await self._client.aio.models.generate_content(
                model=self.model,
                contents=prompt,
                config=config,
            )
        except APIError as e:
            # Map common errors based on HTTP status or messages
            status_code = getattr(e, "code", None)
            message = str(e)
            if status_code in (408, 504) or "timeout" in message.lower():
                logger.error(f"Gemini API request timed out: {e}")
                raise LLMTimeoutError(f"Gemini request timed out: {e}") from e
            elif status_code in (502, 503, 504) or "connection" in message.lower():
                logger.error(f"Gemini API connection error: {e}")
                raise LLMConnectionError(f"Gemini connection failed: {e}") from e
            elif status_code == 400:
                logger.error(f"Gemini API bad request error: {e}")
                raise LLMResponseError(f"Gemini API bad request: {e}") from e
            else:
                logger.error(f"Gemini API exception: {e}")
                raise LLMException(f"Gemini API call failed: {e}") from e
        except Exception as e:
            logger.error(f"Unexpected error in Gemini Provider: {e}")
            raise LLMException(f"Unexpected error in Gemini Provider: {e}") from e

        latency_ms = (time.perf_counter() - start_time) * 1000

        # Canonical response extraction with fallback manual concatenation
        response_content = ""
        try:
            response_content = response.text or ""
        except Exception:
            pass

        if not response_content:
            parts = []
            if response.candidates:
                candidate = response.candidates[0]
                if candidate.content and candidate.content.parts:
                    for part in candidate.content.parts:
                        if part.text:
                            parts.append(part.text)
            response_content = "".join(parts)

        # Extract usage metadata
        prompt_tokens = None
        completion_tokens = None
        if response.usage_metadata:
            prompt_tokens = response.usage_metadata.prompt_token_count
            completion_tokens = response.usage_metadata.candidates_token_count

        # Normalize finish reason
        raw_finish_reason = None
        if response.candidates:
            raw_finish_reason = getattr(response.candidates[0], "finish_reason", None)

        finish_reason = "other"
        if raw_finish_reason:
            raw_str = str(raw_finish_reason).upper()
            if "STOP" in raw_str:
                finish_reason = "stop"
            elif "MAX_TOKENS" in raw_str:
                finish_reason = "max_tokens"
            elif "SAFETY" in raw_str:
                finish_reason = "safety"
            else:
                finish_reason = raw_str.lower()

        # Log warning if finish reason is not STOP
        if finish_reason != "stop":
            logger.warning(
                f"Gemini Provider warning: Generation terminated with non-stop reason: {finish_reason}. "
                "This may indicate that the output was truncated or blocked."
            )

        # Log (DEBUG only) full raw Gemini response details
        if logger.isEnabledFor(logging.DEBUG):
            candidate_count = len(response.candidates) if response.candidates else 0
            parts_count = 0
            if response.candidates and response.candidates[0].content and response.candidates[0].content.parts:
                parts_count = len(response.candidates[0].content.parts)

            logger.debug(
                "\n================ GEMINI RAW RESPONSE ================\n"
                f"effective model name: {self.model}\n"
                f"max_output_tokens used: {config_args.get('max_output_tokens')}\n"
                f"candidate count: {candidate_count}\n"
                f"parts count: {parts_count}\n"
                f"candidate.finish_reason: {raw_finish_reason}\n"
                f"usage: {response.usage_metadata}\n"
                f"response.text:\n{response_content}\n"
                "====================================================="
            )

        # Structured metadata logging to match Ollama
        log_extra = {
            "provider": "gemini",
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
        raise NotImplementedError("Streaming is not yet implemented for GeminiProvider.")
        yield  # type: ignore

    async def health_check(self) -> bool:
        """Verifies if the Gemini provider is configured correctly without calling external network APIs."""
        return bool(self.api_key)

    def get_metadata(self) -> dict[str, Any]:
        """Exposes capability metadata for diagnostic discovery."""
        return {
            "provider": "gemini",
            "model": self.model,
            "capabilities": {
                "streaming": False,
                "text_generation": True,
                "thinking": False,
            },
        }

    async def close(self) -> None:
        """Cleanly disposes of the internal client."""
        await self._client.aio.aclose()

    async def embed(self, text: str) -> list[float]:
        """Generates semantic vector embeddings using Gemini's text-embedding-004 model."""
        try:
            cleaned_text = text.strip()
            if not cleaned_text:
                return [0.0] * 768
            res = await self._client.aio.models.embed_content(
                model="text-embedding-004",
                contents=cleaned_text
            )
            if res and res.embedding and res.embedding.values:
                return res.embedding.values
            raise LLMResponseError("Gemini embedding response was empty.")
        except Exception as e:
            logger.error(f"GeminiProvider: embedding generation failed: {e}")
            raise LLMResponseError(f"Embedding failed: {e}") from e
