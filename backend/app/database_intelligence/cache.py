import logging
import time
from typing import Optional

from app.core.config import settings
from app.database_intelligence.exceptions import SchemaCacheError
from app.database_intelligence.interfaces import IDatabaseInspector
from app.database_intelligence.models import DatabaseSchema

logger = logging.getLogger(__name__)


class SchemaCache:
    """In-memory cache for DatabaseSchema metadata.

    Governs cache verification, expiration checks, and automatic refresh hooks.
    """

    def __init__(self, inspector: IDatabaseInspector):
        self.inspector = inspector
        self._cached_schema: Optional[DatabaseSchema] = None
        self._last_fetched: float = 0.0

        # Read configurations from central Settings
        self.cache_enabled: bool = getattr(settings, "SCHEMA_CACHE_ENABLED", True)
        self.cache_ttl: float = getattr(settings, "SCHEMA_CACHE_TTL", 3600.0)
        self.auto_refresh: bool = getattr(settings, "AUTO_REFRESH_SCHEMA", True)

    async def get_schema(self) -> DatabaseSchema:
        """Retrieves database schema from cache, refreshing if missing or expired."""
        if not self.cache_enabled:
            logger.info("Schema cache is disabled. Inspecting database schema directly.")
            return await self.inspector.inspect_schema()

        now = time.perf_counter()
        is_expired = (now - self._last_fetched) > self.cache_ttl

        if self._cached_schema is None:
            logger.info("Schema cache miss. Running database inspection.")
            await self.refresh()
        elif is_expired:
            if self.auto_refresh:
                logger.info("Schema cache expired. Running auto-refresh database inspection.")
                await self.refresh()
            else:
                logger.warning(
                    "Schema cache expired but AUTO_REFRESH_SCHEMA is disabled. Returning stale cached schema."
                )
        else:
            logger.debug("Schema cache hit.")

        if self._cached_schema is None:
            raise SchemaCacheError("Database schema could not be retrieved or cached.")

        return self._cached_schema

    async def refresh(self) -> None:
        """Forces immediate refresh of the database schema cache."""
        logger.info("Initiating database schema cache refresh operation.")
        try:
            self._cached_schema = await self.inspector.inspect_schema()
            self._last_fetched = time.perf_counter()
            logger.info(
                "Database schema cache refreshed successfully.",
                extra={"fingerprint": self._cached_schema.fingerprint},
            )
        except Exception as e:
            logger.error(f"Failed to refresh schema cache: {e}")
            raise SchemaCacheError(f"Failed to refresh schema cache: {e}") from e

    def invalidate(self) -> None:
        """Clears the cached schema structure."""
        logger.info("Invalidating database schema cache.")
        self._cached_schema = None
        self._last_fetched = 0.0

    @property
    def current_version(self) -> Optional[str]:
        """Returns the active schema fingerprint version string if cached."""
        return self._cached_schema.fingerprint if self._cached_schema else None
