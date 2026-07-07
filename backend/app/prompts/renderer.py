from abc import ABC, abstractmethod
from typing import Any


class PromptRendererError(Exception):
    """Exception raised when variable interpolation or template rendering fails."""

    pass


class IPromptRenderer(ABC):
    """Abstract base class establishing a template-agnostic contract for prompt rendering."""

    @abstractmethod
    def render(self, template: str, variables: dict[str, Any]) -> str:
        """Interpolates context parameters into the target prompt template text.

        Args:
            template: The raw string template containing placeholders.
            variables: Key-value parameters dictionary containing contextual variables.

        Returns:
            str: Rendered text ready for LLM consumption.
        """
        pass


class DefaultPromptRenderer(IPromptRenderer):
    """Default string-based renderer.

    Can be seamlessly substituted with a Jinja2PromptRenderer in future sprints.
    """

    def render(self, template: str, variables: dict[str, Any]) -> str:
        """Interpolates arguments into the template using standard Python substitution mechanics."""
        try:
            return template.format(**variables)
        except KeyError as e:
            error_msg = f"Missing required parameter for template interpolation: {e}"
            raise PromptRendererError(error_msg) from e
        except Exception as e:
            error_msg = f"Error during prompt template rendering: {e}"
            raise PromptRendererError(error_msg) from e


# Export default instanced handler
prompt_renderer = DefaultPromptRenderer()
