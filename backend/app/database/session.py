import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.shared.exceptions import AppBaseException

logger = logging.getLogger(__name__)


class DatabaseInitializationError(AppBaseException):
    """Exception raised when the database engine cannot be initialized.

    This is usually caused by database configuration issues.
    """

    pass


logger.info("Initializing database infrastructure configurations...")

# Validate DATABASE_URL existence
if not settings.DATABASE_URL:
    logger.critical("Database initialization failed: DATABASE_URL is not defined.")
    raise DatabaseInitializationError(
        "DATABASE_URL variable must be provided in system configurations."
    )

try:
    logger.info("Creating asynchronous database engine instance...")

    # Standard connection parameters
    engine_options = {
        "echo": settings.DATABASE_ECHO,
        "future": True,
    }

    # Configure connection pools specifically for PostgreSQL backends
    if settings.DATABASE_URL.startswith("postgresql"):
        engine_options["pool_size"] = settings.DATABASE_POOL_SIZE
        engine_options["max_overflow"] = 10
    elif settings.DATABASE_URL.startswith("sqlite"):
        engine_options["connect_args"] = {"check_same_thread": False}

    engine = create_async_engine(settings.DATABASE_URL, **engine_options)
    logger.info(
        f"Async database engine created successfully (DATABASE_ECHO={settings.DATABASE_ECHO})."
    )

except Exception as e:
    logger.critical(f"Async database engine creation threw critical exception: {e}")
    raise DatabaseInitializationError(f"Database engine instantiation failed: {str(e)}") from e

# Define transactional session maker factory
SessionLocal = async_sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
    class_=AsyncSession,
)
