import re


class OutputParser:
    """Utility class to parse and clean Large Language Model outputs."""

    @staticmethod
    def parse_sql(raw_llm_output: str) -> str:
        """Extracts executable SQL queries from raw LLM responses.

        Handles wrapper templates such as markdown blocks (```sql ... ```)
        or trailing semicolons.

        Args:
            raw_llm_output: Raw text output from LLM.

        Returns:
            str: Executable SQL query.
        """
        cleaned = raw_llm_output.strip()

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
