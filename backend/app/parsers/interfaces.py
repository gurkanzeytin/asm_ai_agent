from abc import ABC, abstractmethod


class IOutputParser(ABC):
    """Abstract interface for parsing and extracting query formats from raw LLM output text."""

    @abstractmethod
    def parse_sql(self, text: str) -> str:
        """Extracts pure SQL query strings from markdown blocks or raw response text.

        Args:
            text: Raw LLM response string.

        Returns:
            str: Normalized executable SQL query.
        """
        pass
