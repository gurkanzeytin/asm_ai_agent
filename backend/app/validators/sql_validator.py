import re


class SQLValidator:
    """Security validation engine for generated SQL queries."""

    @staticmethod
    def is_safe_query(query: str) -> bool:
        """Verifies if a query is restricted strictly to read-only statements.

        Args:
            query: SQL code to evaluate.

        Returns:
            bool: True if safe, False if mutation command detected.
        """
        forbidden = [
            r"\bINSERT\b",
            r"\bUPDATE\b",
            r"\bDELETE\b",
            r"\bDROP\b",
            r"\bALTER\b",
            r"\bTRUNCATE\b",
            r"\bGRANT\b",
            r"\bREVOKE\b",
            r"\bCREATE\b",
        ]

        for command in forbidden:
            if re.search(command, query, re.IGNORECASE):
                return False

        return True
