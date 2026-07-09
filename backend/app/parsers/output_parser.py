import re

from app.parsers.interfaces import IOutputParser


class OutputParser(IOutputParser):
    """Output parser implementation providing utilities to parse and clean LLM responses."""

    def parse_sql(self, text: str) -> str:
        """Extracts the executable SQL query from the text, ignoring conversational wrappers.

        Supported patterns:
        - Case 1: Pure SQL statement starting with SELECT/WITH.
        - Case 2: Fenced SQL code blocks: ```sql SELECT ... ``` or ``` SELECT ... ```.
        - Case 3: Conversational wrappers, e.g. "Here is the SQL query: SELECT ...; Explanation".
        """
        # 1. Clean basic outer whitespace
        cleaned = text.strip()

        # 2. Check for markdown code block fences
        code_block_match = re.search(
            r"```(?:sql)?\s*(.*?)\s*```", cleaned, re.DOTALL | re.IGNORECASE
        )
        if code_block_match:
            candidate = code_block_match.group(1).strip()
        else:
            candidate = cleaned

        # 3. Strip quotes and backticks
        candidate = candidate.strip('"`')

        # 4. Search for SELECT or WITH at word boundaries, matching until the first semicolon
        select_match = re.search(r"(\b(?:SELECT|WITH)\b.*?;)", candidate, re.DOTALL | re.IGNORECASE)
        if select_match:
            return select_match.group(1).strip('"` ').strip()

        # 5. If no semicolon is found, match from SELECT or WITH to the end of the string
        select_no_semi_match = re.search(r"(\b(?:SELECT|WITH)\b.*)", candidate, re.DOTALL | re.IGNORECASE)
        if select_no_semi_match:
            return select_no_semi_match.group(1).strip('"` ').strip()

        # 6. Fallback if no SELECT/WITH block matches
        return candidate.strip('"` ').strip()
