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
    """Builds SQL Server engine keyword options for the configured database URL.

    Never include the connection URL itself in log output: it may contain secrets.

    Args:
        database_url: SQLAlchemy async connection string.

    Returns:
        dict: Keyword options for create_async_engine.

    Raises:
        DatabaseInitializationError: If the URL is not an async SQL Server URL.
    """
    if not database_url.startswith("mssql+aioodbc"):
        raise DatabaseInitializationError(
            "Unsupported DATABASE_URL scheme: Microsoft SQL Server is the only supported "
            "runtime database and requires the async 'mssql+aioodbc' driver. Configure "
            "DB_SERVER/DB_DATABASE/DB_DRIVER (or a 'mssql+aioodbc://...' DATABASE_URL)."
        )
    return {
        "echo": settings.DATABASE_ECHO,
        "future": True,
        "pool_size": settings.DATABASE_POOL_SIZE,
        "max_overflow": 5,
        "pool_pre_ping": True,
        "pool_recycle": 1800,
        # Login timeout forwarded to the ODBC driver via aioodbc/pyodbc.
        "connect_args": {"timeout": settings.DATABASE_CONNECT_TIMEOUT},
    }


def _warn_if_odbc_driver_missing() -> None:
    """Logs a clear warning when the configured Microsoft ODBC driver is not installed.

    The hard failure happens at first connection; this makes the root cause obvious
    at startup without preventing offline work (tests, tooling) on machines
    without the driver.
    """
    try:
        import pyodbc
    except ImportError as e:
        raise DatabaseInitializationError(
            "The 'pyodbc' package is required for SQL Server connectivity but is not "
            "installed. Run: pip install -r requirements.txt"
        ) from e
    installed = pyodbc.drivers()
    if settings.DB_DRIVER and settings.DB_DRIVER not in installed:
        logger.warning(
            f"Configured ODBC driver '{settings.DB_DRIVER}' was not found among installed "
            f"drivers. Install 'Microsoft ODBC Driver 18 for SQL Server' before connecting."
        )


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

_warn_if_odbc_driver_missing()


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
