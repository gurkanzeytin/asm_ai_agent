import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class PromptLoaderError(Exception):
    """Raised when a prompt file cannot be resolved or loaded from disk."""

    pass


class PromptLoader:
    """Singleton service to locate, read, and cache prompt template markdown files."""

    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, prompts_dir: Path | None = None):
        if getattr(self, "_initialized", False):
            return

        self.prompts_dir = prompts_dir or Path(__file__).parent
        self._cache: dict[str, str] = {}
        self._initialized = True
        logger.info(f"PromptLoader singleton initialized targeting: {self.prompts_dir}")

    def get_prompt(self, name: str) -> str:
        """Retrieves prompt contents, reading from disk once then resolving from memory cache."""
        if not name.endswith(".md"):
            name = f"{name}.md"

        if name in self._cache:
            logger.debug(f"Prompt cached hit: '{name}' fetched from memory.")
            return self._cache[name]

        file_path = self.prompts_dir / name
        if not file_path.exists():
            error_msg = f"Prompt resource '{name}' could not be found at path: {file_path}"
            logger.error(error_msg)
            raise PromptLoaderError(error_msg)

        try:
            logger.info(f"Reading prompt '{name}' from disk path...")
            with open(file_path, encoding="utf-8") as file:
                content = file.read()
            self._cache[name] = content
            return content
        except Exception as e:
            error_msg = f"Failed to parse prompt file '{name}': {e}"
            logger.error(error_msg)
            raise PromptLoaderError(error_msg) from e

    def clear_cache(self) -> None:
        """Clears the internal cache registry. Useful for testing or hot-reload updates."""
        logger.info("Clearing PromptLoader cache registry.")
        self._cache.clear()


# Export singleton instance
prompt_loader = PromptLoader()
