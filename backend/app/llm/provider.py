from abc import ABC, abstractmethod
from typing import Any


class LLMProvider(ABC):
    """Abstract interface representing a Large Language Model provider.

    Allows swapping backend models (Ollama, OpenAI, Anthropic, HuggingFace)
    without modifying the business logic of nodes or agent systems.
    """

    @abstractmethod
    async def generate(self, prompt: str, **kwargs: Any) -> str:
        """Sends a text prompt to the LLM and returns the text response.

        Args:
            prompt: Formatted user and system prompt string.
            **kwargs: Extra hyperparameters (temperature, max_tokens, etc.).

        Returns:
            str: Generated text answer from the LLM.
        """
        pass
