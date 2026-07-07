import logging
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import SessionLocal

logger = logging.getLogger(__name__)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency to retrieve transactional asynchronous database sessions.

    Enforces lifespan logging of session context creation and destruction.

    Yields:
        AsyncSession: Active database query session.
    """
    logger.info("Initializing context: creating new database AsyncSession instance...")
    async with SessionLocal() as session:
        try:
            yield session
        finally:
            logger.info("Closing database AsyncSession context...")
            await session.close()
