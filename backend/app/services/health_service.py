import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class HealthService:
    """Diagnostic service to aggregate status checks across internal systems."""

    @staticmethod
    async def check_database_liveness(db: AsyncSession) -> bool:
        """Runs a verification query against the active database session.

        Args:
            db: Database session.

        Returns:
            bool: True if DB is online, False otherwise.
        """
        try:
            await db.execute(text("SELECT 1"))
            return True
        except Exception as e:
            logger.error(f"HealthService DB connection test failed: {e}")
            return False
