import logging

import httpx

from app.core.config import settings
from app.llm.provider import LLMProvider

logger = logging.getLogger(__name__)


class OllamaProvider(LLMProvider):
    """Ollama API implementation of the LLMProvider abstraction."""

    def __init__(self, base_url: str | None = None, model: str | None = None):
        self.base_url = base_url or settings.OLLAMA_BASE_URL
        self.model = model or settings.OLLAMA_MODEL

    async def generate(self, prompt: str, **kwargs) -> str:
        """Invokes the Ollama local API server to generate text.

        Falls back to a standard mock string if the connection is refused,
        ensuring local tests and dry runs do not block developer setup.
        """
        url = f"{self.base_url}/api/generate"
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": kwargs.get("temperature", 0.0),
                "num_predict": kwargs.get("max_tokens", 512),
            },
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=payload, timeout=30.0)
                response.raise_for_status()
                result = response.json()
                return result.get("response", "")
        except (httpx.ConnectError, httpx.HTTPStatusError) as e:
            logger.warning(f"Ollama connection error: {e}. Returning simulation placeholder.")
            # Graceful simulation fallback for dry-runs
            return f"[Simulated Ollama response for {self.model} model]"
