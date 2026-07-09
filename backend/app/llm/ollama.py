import asyncio
import logging
import time
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any

import httpx

from app.llm.exceptions import (
    LLMConnectionError,
    LLMException,
    LLMResponseError,
    LLMTimeoutError,
)
from app.llm.interfaces import ILLMProvider
from app.llm.schemas import LLMResponse

logger = logging.getLogger(__name__)


class OllamaProvider(ILLMProvider):
    """Ollama API implementation of the ILLMProvider abstraction."""

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        timeout: float | None = None,
        retry_count: int | None = None,
    ):
        from app.core.config import settings
        from app.shared.exceptions import ConfigurationError

        self.base_url = (base_url or settings.OLLAMA_BASE_URL)
        if self.base_url:
            self.base_url = self.base_url.rstrip("/")
        self.model = model or settings.OLLAMA_MODEL
        self.timeout = timeout if timeout is not None else getattr(settings, "OLLAMA_TIMEOUT", 30.0)
        self.retry_count = (
            retry_count if retry_count is not None else getattr(settings, "LLM_RETRY_COUNT", 3)
        )

        # Fail fast if base URL is missing
        if not self.base_url:
            logger.critical("Startup validation error: Ollama provider selected but OLLAMA_BASE_URL is missing.")
            raise ConfigurationError("Ollama provider selected but OLLAMA_BASE_URL is missing.")

        # Initialize cached client and loop association immediately
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        self._client_loop = loop
        self._cached_client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=10.0,
                write=10.0,
                read=self.timeout,
                pool=10.0,
            )
        )
        # Log diagnostics
        logger.info(
            "Ollama initialized\n"
            f"model={self.model}\n"
            f"base_url={self.base_url}"
        )

    @property
    def _client(self) -> httpx.AsyncClient:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if not hasattr(self, "_client_loop") or self._client_loop is not loop:
            self._client_loop = loop
            self._cached_client = httpx.AsyncClient(
                timeout=httpx.Timeout(
                    connect=10.0,
                    write=10.0,
                    read=self.timeout,
                    pool=10.0,
                )
            )
        return self._cached_client

    async def generate(
        self,
        prompt: str,
        think: bool = True,
        options: dict[str, Any] | None = None,
    ) -> LLMResponse:
        """Invokes the Ollama local API server to generate text with retry logic."""
        url = f"{self.base_url}/api/generate"
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.0,
            },
        }
        if not think:
            payload["think"] = False
        if options:
            payload["options"].update(options)


        retries = self.retry_count
        backoff = 0.5
        last_exception = None
        response_json = None
        start_time = time.perf_counter()
        request_timestamp = datetime.now(timezone.utc).isoformat()

        for attempt in range(retries + 1):
            try:
                logger.debug(
                    "Ollama HTTP request starting",
                    extra={
                        "attempt": attempt + 1,
                        "total_attempts": retries + 1,
                        "base_url": self.base_url,
                        "endpoint": url,
                        "model": self.model,
                        "read_timeout": self.timeout,
                        "payload_keys": list(payload.keys()),
                    },
                )
                response = await self._client.post(url, json=payload)
                if response.status_code == 400 and "think" in payload:
                    logger.warning("Ollama server returned 400 Bad Request for think option. Retrying request without 'think' parameter.")
                    del payload["think"]
                    response = await self._client.post(url, json=payload)
                if response.status_code in (502, 503, 504):
                    response.raise_for_status()
                response.raise_for_status()
                response_json = response.json()
                last_exception = None
                logger.debug(
                    "Ollama HTTP response received",
                    extra={
                        "http_status": response.status_code,
                        "response_bytes": len(response.content),
                        "model": self.model,
                    },
                )
                break  # Successful response, exit retry loop
            except (httpx.ConnectError, httpx.ConnectTimeout, httpx.TimeoutException) as e:
                last_exception = e
                if attempt == retries:
                    break
                logger.warning(
                    f"Transient network/timeout error on attempt {attempt + 1}/{retries + 1}: {e}. Retrying in {backoff}s..."
                )
                await asyncio.sleep(backoff)
                backoff *= 2
            except httpx.HTTPStatusError as e:
                if e.response.status_code in (502, 503, 504):
                    last_exception = e
                    if attempt == retries:
                        break
                    logger.warning(
                        f"Transient status code {e.response.status_code} on attempt {attempt + 1}/{retries + 1}. Retrying in {backoff}s..."
                    )
                    await asyncio.sleep(backoff)
                    backoff *= 2
                else:
                    logger.error(f"Non-retriable HTTP status error: {e.response.status_code}")
                    raise LLMResponseError(
                        f"Ollama returned HTTP error status: {e.response.status_code}"
                    ) from e
            except httpx.RequestError as e:
                last_exception = e
                if attempt == retries:
                    break
                logger.warning(
                    f"Request error on attempt {attempt + 1}/{retries + 1}: {e}. Retrying in {backoff}s..."
                )
                await asyncio.sleep(backoff)
                backoff *= 2
            except Exception as e:
                logger.error(f"Unexpected non-retriable error in Ollama: {e}")
                raise LLMException(f"Unexpected error in Ollama provider: {e}") from e

        # Handle final exception if retry limits exceeded
        if last_exception:
            if isinstance(last_exception, httpx.TimeoutException):
                logger.error(f"Ollama request timed out after {retries} retries.")
                raise LLMTimeoutError(
                    f"Ollama request timed out after {retries} retries: {last_exception}"
                ) from last_exception
            elif isinstance(last_exception, (httpx.ConnectError, httpx.ConnectTimeout)):
                logger.error(f"Ollama connection failed after {retries} retries.")
                raise LLMConnectionError(
                    f"Ollama connection failed after {retries} retries: {last_exception}"
                ) from last_exception
            elif isinstance(last_exception, httpx.HTTPStatusError):
                logger.error(
                    f"Ollama returned HTTP status {last_exception.response.status_code} after {retries} retries."
                )
                raise LLMResponseError(
                    f"Ollama returned transient HTTP error status after {retries} retries: {last_exception.response.status_code}"
                ) from last_exception
            else:
                logger.error(f"Ollama request failed: {last_exception}")
                raise LLMException(f"Ollama request failed: {last_exception}") from last_exception

        if response_json is None:
            raise LLMResponseError("Ollama returned an empty response body.")

        latency_ms = (time.perf_counter() - start_time) * 1000
        response_content = response_json.get("response", "")
        prompt_tokens = response_json.get("prompt_eval_count")
        completion_tokens = response_json.get("eval_count")

        done = response_json.get("done", False)
        done_reason = response_json.get("done_reason")

        finish_reason = "other"
        if done_reason:
            done_reason_lower = done_reason.lower()
            if "stop" in done_reason_lower:
                finish_reason = "stop"
            elif "length" in done_reason_lower or "limit" in done_reason_lower:
                finish_reason = "max_tokens"
            else:
                finish_reason = done_reason_lower
        elif done:
            finish_reason = "stop"

        # Structured metadata logging without printing prompt/response content
        log_extra = {
            "provider": "ollama",
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
        """Asynchronously streams generated responses from Ollama.

        Not implemented in this version.
        """
        raise NotImplementedError("Streaming is not yet implemented for OllamaProvider.")
        yield  # type: ignore # unreachable, makes Python treat it as a generator

    async def health_check(self) -> bool:
        """Verifies Ollama availability by querying the lightweight /api/tags endpoint."""
        try:
            url = f"{self.base_url}/api/tags"
            response = await self._client.get(url)
            return response.status_code == 200
        except Exception:
            return False

    def get_metadata(self) -> dict[str, Any]:
        """Returns diagnostic metadata about the current Ollama provider configuration."""
        return {
            "provider": "ollama",
            "model": self.model,
            "timeout": self.timeout,
            "retry_count": self.retry_count,
            "capabilities": {
                "streaming": False,
                "text_generation": True,
            },
        }

    async def close(self) -> None:
        """Cleanly disposes of the persistent HTTP client."""
        await self._client.aclose()

    async def embed(self, text: str) -> list[float]:
        """Generates semantic vector embeddings for a given text string using Ollama."""
        try:
            cleaned_text = text.strip()
            if not cleaned_text:
                return [0.0] * 768
            url = f"{self.base_url}/api/embeddings"
            payload = {
                "model": self.model,  # fall back to configured generation model (e.g. qwen3:8b)
                "prompt": cleaned_text
            }
            res = await self._client.post(url, json=payload, timeout=self.timeout)
            res.raise_for_status()
            return res.json()["embedding"]
        except Exception as e:
            logger.error(f"OllamaProvider: embedding generation failed: {e}")
            raise LLMResponseError(f"Embedding failed: {e}") from e
