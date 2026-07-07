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

        self.base_url = (base_url or settings.OLLAMA_BASE_URL).rstrip("/")
        self.model = model or settings.OLLAMA_MODEL
        self.timeout = timeout if timeout is not None else getattr(settings, "OLLAMA_TIMEOUT", 30.0)
        self.retry_count = (
            retry_count if retry_count is not None else getattr(settings, "LLM_RETRY_COUNT", 3)
        )

        # Persistent HTTP client reused across requests
        self._client = httpx.AsyncClient(timeout=self.timeout)

    async def generate(self, prompt: str) -> LLMResponse:
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

        retries = self.retry_count
        backoff = 0.5
        last_exception = None
        response_json = None
        start_time = time.perf_counter()
        request_timestamp = datetime.now(timezone.utc).isoformat()

        for attempt in range(retries + 1):
            try:
                response = await self._client.post(url, json=payload)
                if response.status_code in (502, 503, 504):
                    response.raise_for_status()
                response.raise_for_status()
                response_json = response.json()
                last_exception = None
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

        # Structured metadata logging without printing prompt/response content
        log_extra = {
            "model_name": self.model,
            "request_timestamp": request_timestamp,
            "latency": latency_ms,
            "prompt_length": len(prompt),
            "response_length": len(response_content),
            "provider": "ollama",
        }
        logger.info("LLM request completed successfully", extra=log_extra)

        return LLMResponse(
            content=response_content,
            model=self.model,
            latency_ms=latency_ms,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
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
