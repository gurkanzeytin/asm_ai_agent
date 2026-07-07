import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class PromptBuilder:
    """Helper to locate, read, and interpolate external markdown prompt templates."""

    @staticmethod
    def load_prompt(template_name: str, **kwargs) -> str:
        """Reads a prompt template file and injects parameters.

        Args:
            template_name: Filename of the prompt (e.g., 'system_prompt.md').
            **kwargs: Template placeholders and corresponding replacements.

        Returns:
            str: Formatted prompt text.
        """
        # Resolve path relative to app root
        prompts_dir = Path(__file__).parent.parent / "prompts"
        file_path = prompts_dir / template_name

        if not file_path.exists():
            error_msg = f"Prompt template '{template_name}' not found at {file_path}"
            logger.error(error_msg)
            raise FileNotFoundError(error_msg)

        with open(file_path, encoding="utf-8") as file:
            content = file.read()

        try:
            return content.format(**kwargs)
        except KeyError as e:
            logger.error(f"Missing formatting key {e} for prompt {template_name}")
            raise
