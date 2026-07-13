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
        """Invokes the LLM provider to synthesize a standard narrative report.

        Thinking mode is disabled: reasoning models (e.g. qwen3) otherwise spend the
        entire OLLAMA_TIMEOUT read window inside the <think> block, which times out
        every analytical (LLM-path) report while template-path reports keep working.
        """
        return await llm_provider.generate(prompt, think=False)
