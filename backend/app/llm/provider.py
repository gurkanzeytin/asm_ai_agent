import logging

from app.core.config import settings
from app.llm.interfaces import ILLMProvider
from app.llm.ollama import OllamaProvider

logger = logging.getLogger(__name__)


class LLMFactory:
    """Factory class to retrieve cached, singleton LLM provider instances.

    Guarantees that only a single instance of each provider is created and reused,
    preserving persistent HTTP clients and connection pools.
    """

    _instances: dict[str, ILLMProvider] = {}

    @classmethod
    def get_provider(cls, provider_type: str | None = None) -> ILLMProvider:
        """Retrieves or instantiates the requested LLM Provider singleton.

        Reads the active provider type from central configurations if not specified.

        Args:
            provider_type: Optional string name of the provider (e.g. 'ollama').

        Returns:
            ILLMProvider: A shared concrete provider instance.

        Raises:
            ValueError: If the configured provider type is unknown or unsupported.
        """
        if provider_type is None:
            provider_type = getattr(settings, "LLM_PROVIDER", "ollama")

        provider_key = provider_type.strip().lower()

        if provider_key not in cls._instances:
            if provider_key == "ollama":
                logger.info("Instantiating new singleton OllamaProvider instance.")
                cls._instances[provider_key] = OllamaProvider()
            elif provider_key == "gemini":
                logger.info("Instantiating new singleton GeminiProvider instance.")
                from app.llm.gemini import GeminiProvider
                cls._instances[provider_key] = GeminiProvider()
            else:
                logger.error(f"Unsupported LLM provider requested: {provider_type}")
                raise ValueError(f"Unsupported LLM provider: {provider_type}")

        provider_instance = cls._instances[provider_key]
        
        # Log selection diagnostics
        logger.info(
            "\n================ LLM PROVIDER =================\n"
            f"Configured provider : {settings.LLM_PROVIDER}\n"
            f"Resolved provider   : {provider_key}\n"
            f"Provider class      : {provider_instance.__class__.__name__}\n"
            f"Model               : {getattr(provider_instance, 'model', 'unknown')}\n"
            "=============================================="
        )

        return provider_instance

    @classmethod
    async def clear_providers(cls) -> None:
        """Closes and clears all cached provider instances to free resources."""
        for provider_key, provider in list(cls._instances.items()):
            try:
                await provider.close()
            except Exception as e:
                logger.warning(f"Error closing provider '{provider_key}': {e}")
        cls._instances.clear()
