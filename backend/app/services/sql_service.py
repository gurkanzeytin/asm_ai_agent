import logging

from sqlalchemy import text

from app.database.session import SessionLocal

logger = logging.getLogger(__name__)


class SQLService:
    """Handles raw SQL query operations safely within database transactions."""

    @staticmethod
    async def execute_query(query: str) -> list[dict]:
        """Runs validated query statements against the database.

        Args:
            query: SQL code to execute.

        Returns:
            list[dict]: List of row maps matching result sets.
        """
        logger.info(f"SQLService: Running statement query: {query}")

        async with SessionLocal() as session:
            try:
                result = await session.execute(text(query))
                if result.returns_rows:
                    return [dict(row) for row in result.mappings().all()]
                return []
            except Exception as e:
                logger.error(f"SQLService database query failed: {e}")
                raise
