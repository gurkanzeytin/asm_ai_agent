from abc import ABC, abstractmethod

from app.llm.interfaces import ILLMProvider
from app.llm.schemas import LLMResponse


class IReportGenerator(ABC):
    """Abstract strategy for synthesizing specific types of reports."""

    @abstractmethod
    async def generate(self, prompt: str, llm_provider: ILLMProvider) -> LLMResponse:
        """Sends prompt to LLM and returns the structured LLMResponse.

        Args:
            prompt: Rendered prompt text.
            llm_provider: Active LLM provider interface.

        Returns:
            LLMResponse: Structured response object.
        """
        pass


class NarrativeReportGenerator(IReportGenerator):
    """Default strategy for generating narrative markdown reports."""

    async def generate(self, prompt: str, llm_provider: ILLMProvider) -> LLMResponse:
        """Invokes the LLM provider to synthesize a standard narrative report."""
        return await llm_provider.generate(prompt)
