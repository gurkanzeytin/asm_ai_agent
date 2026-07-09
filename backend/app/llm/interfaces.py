from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any

from app.llm.schemas import LLMResponse


class ILLMProvider(ABC):
    """Abstract interface representing a Large Language Model provider.

    Enables swapping backend models (Ollama, OpenAI, Anthropic, HuggingFace)
    without modifying the business logic of nodes or agent systems.
    """

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        think: bool = True,
        options: dict[str, Any] | None = None,
    ) -> LLMResponse:
        """Sends a text prompt to the LLM and returns the typed LLMResponse.

        Args:
            prompt: Formatted user and system prompt string.
            think: Bypass or enable thinking/reasoning mode if supported.
            options: Custom provider key-value overrides.

        Returns:
            LLMResponse: Typed response object containing text and metadata.
        """
        pass

    @abstractmethod
    async def stream_generate(self, prompt: str) -> AsyncIterator[LLMResponse]:
        """Asynchronously streams generated tokens/responses from the LLM.

        Args:
            prompt: Formatted user and system prompt string.

        Returns:
            AsyncIterator[LLMResponse]: Stream of LLMResponse chunks.
        """
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """Verifies that the configured LLM provider is reachable and active.

        Returns:
            bool: True if reachable, False otherwise.
        """
        pass

    @abstractmethod
    def get_metadata(self) -> dict[str, Any]:
        """Returns provider-specific diagnostics metadata.

        Returns:
            dict[str, Any]: Dictionary containing diagnostic and capability details.
        """
        pass

    @abstractmethod
    async def close(self) -> None:
        """Cleanly disposes of any cached resources (e.g. HTTP clients)."""
        pass

    @abstractmethod
    async def embed(self, text: str) -> list[float]:
        """Generates semantic vector embeddings for a given text string.

        Args:
            text: Input text string to embed.

        Returns:
            list[float]: Embedding vector values.
        """
        pass
