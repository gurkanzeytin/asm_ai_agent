import re

from app.parsers.interfaces import IOutputParser


class OutputParser(IOutputParser):
    """Output parser implementation providing utilities to parse and clean LLM responses."""

    def parse_sql(self, text: str) -> str:
        """Extracts SQL queries by stripping markdown blocks or quotes."""
        cleaned = text.strip()

        # Regex to locate query within code blocks
        code_block_match = re.search(
            r"```(?:sql)?\s*(.*?)\s*```", cleaned, re.DOTALL | re.IGNORECASE
        )

        if code_block_match:
            query = code_block_match.group(1).strip()
        else:
            query = cleaned

        # Ensure it doesn't contain surrounding quotes or escape artifacts
        query = query.strip('"`')

        return query
