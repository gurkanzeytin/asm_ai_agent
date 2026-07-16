import logging

from sqlalchemy import event
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

def build_engine_options(database_url: str) -> dict:
    """Builds dialect-aware engine keyword options for the configured database URL.

    Never include the connection URL itself in log output: it may contain secrets.

    Args:
        database_url: SQLAlchemy async connection string.

    Returns:
        dict: Keyword options for create_async_engine.

    Raises:
        DatabaseInitializationError: If an unsupported SQL Server driver scheme is used.
    """
    engine_options: dict = {
        "echo": settings.DATABASE_ECHO,
        "future": True,
    }

    if database_url.startswith("postgresql"):
        # Configure connection pools specifically for PostgreSQL backends
        engine_options["pool_size"] = settings.DATABASE_POOL_SIZE
        engine_options["max_overflow"] = 10
    elif database_url.startswith("sqlite"):
        engine_options["connect_args"] = {"check_same_thread": False}
    elif database_url.startswith("mssql"):
        if not database_url.startswith("mssql+aioodbc"):
            raise DatabaseInitializationError(
                "SQL Server requires the async 'mssql+aioodbc' driver scheme. "
                "Update DATABASE_URL to use 'mssql+aioodbc://...'."
            )
        engine_options["pool_size"] = settings.DATABASE_POOL_SIZE
        engine_options["max_overflow"] = 5
        engine_options["pool_pre_ping"] = True
        engine_options["pool_recycle"] = 1800
        # Login timeout forwarded to the ODBC driver via aioodbc/pyodbc.
        engine_options["connect_args"] = {"timeout": settings.DATABASE_CONNECT_TIMEOUT}

    return engine_options


try:
    logger.info("Creating asynchronous database engine instance...")
    engine = create_async_engine(
        settings.DATABASE_URL, **build_engine_options(settings.DATABASE_URL)
    )
    logger.info(
        f"Async database engine created successfully (DATABASE_ECHO={settings.DATABASE_ECHO})."
    )
except DatabaseInitializationError:
    raise
except Exception as e:
    logger.critical(f"Async database engine creation threw critical exception: {e}")
    raise DatabaseInitializationError(f"Database engine instantiation failed: {str(e)}") from e


if settings.DATABASE_URL.startswith("mssql"):

    @event.listens_for(engine.sync_engine, "connect")
    def _set_mssql_query_timeout(dbapi_connection, connection_record):  # noqa: ARG001
        """Best-effort per-connection query timeout on the underlying pyodbc connection."""
        raw = getattr(dbapi_connection, "driver_connection", dbapi_connection)
        inner = getattr(raw, "_conn", raw)
        try:
            inner.timeout = settings.DATABASE_QUERY_TIMEOUT
        except Exception:
            logger.warning("Could not apply DATABASE_QUERY_TIMEOUT to the SQL Server connection.")

# Define transactional session maker factory
SessionLocal = async_sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
    class_=AsyncSession,
)
