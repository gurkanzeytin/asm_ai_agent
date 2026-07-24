"""Grounded distinct-value catalog for filter resolution (AI-INTELLIGENCE-016).

Loads approved distinct values for supported low/medium-cardinality columns on
dbo.vw_RandevuRaporu directly from the database — never guessed, never
invented. High-cardinality columns (doctor / appointment source) never get a
full distinct load; they only support a bounded prefix search that returns a
handful of top candidates. Patient-level identifier columns (HastaAdi,
HastaSoyadi, HastaId, ...) are never listed here and can never be queried
through this module.
"""

import logging
import time
from dataclasses import dataclass, field

from sqlalchemy import text

from app.core.config import settings

logger = logging.getLogger(__name__)

VIEW_NAME = "dbo.vw_RandevuRaporu"

# field -> (column, cardinality tier). "high" tier columns never get a full
# distinct load — only `search_candidates()` (bounded prefix search) applies.
FIELD_COLUMNS: dict[str, tuple[str, str]] = {
    "branch": ("SubeAdi", "low"),
    "department": ("GenelRandevuBolumAdi", "low"),
    "service": ("HizmetAdi", "medium"),
    "category": ("KategoriAdi", "low"),
    "appointment_source": ("GenelRandevuKaynakAdi", "high"),
    "doctor": ("GenelRandevuKaynakAdi", "high"),
    "appointment_status": ("RandevuDurumu", "low"),
    "appointment_type": ("RandevuTipiAdi", "low"),
    "nationality": ("Uyruk", "medium"),
    "gender": ("CinsiyetId", "low"),
}

_DISTINCT_LIMIT = 500  # low/medium cardinality safety cap
_SEARCH_LIMIT = 10  # high cardinality bounded search cap

# Columns whose stored values are comma-separated composites
# ("Genel Cerrahi, Ameliyathane, "). Grounding must happen against the ATOMIC
# elements — an equality filter on the raw composite value is meaningless.
_COMPOSITE_FIELDS = {"department"}


def _split_composite_values(values: list[str]) -> list[str]:
    """Splits comma-separated composite values into deduplicated atomic parts,
    preserving first-seen order and dropping empty fragments."""
    seen: set[str] = set()
    atomic: list[str] = []
    for value in values:
        for part in value.split(","):
            cleaned = part.strip()
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            atomic.append(cleaned)
    return atomic


@dataclass
class _CacheEntry:
    values: list[str] = field(default_factory=list)
    fetched_at: float = 0.0


class ValueCatalog:
    """In-memory TTL cache of grounded distinct column values (mirrors SchemaCache)."""

    def __init__(self, session_factory=None) -> None:
        if session_factory is None:
            from app.database.session import SessionLocal as session_factory  # noqa: N813
        self._session_factory = session_factory
        self._cache: dict[str, _CacheEntry] = {}
        self._search_cache: dict[tuple[str, str], _CacheEntry] = {}
        self.cache_ttl: float = getattr(settings, "SCHEMA_CACHE_TTL", 3600.0)

    async def get_distinct_values(self, field_name: str) -> list[str]:
        """Full distinct value list for a low/medium-cardinality field. TTL-cached."""
        column, tier = FIELD_COLUMNS.get(field_name, (None, None))
        if column is None or tier == "high":
            return []
        cached = self._cache.get(field_name)
        now = time.perf_counter()
        if cached is not None and (now - cached.fetched_at) <= self.cache_ttl:
            return cached.values
        values = await self._query_distinct(column)
        if field_name in _COMPOSITE_FIELDS:
            values = _split_composite_values(values)
        self._cache[field_name] = _CacheEntry(values=values, fetched_at=now)
        return values

    async def search_candidates(
        self, field_name: str, prefix: str, limit: int = _SEARCH_LIMIT
    ) -> list[str]:
        """Bounded prefix search for a high-cardinality field (e.g. doctor). Never
        loads the full column into memory or into a prompt — only up to `limit`
        matching values, cached per (field, prefix)."""
        column, _tier = FIELD_COLUMNS.get(field_name, (None, None))
        if column is None or not prefix.strip():
            return []
        key = (field_name, prefix.strip().lower())
        cached = self._search_cache.get(key)
        now = time.perf_counter()
        if cached is not None and (now - cached.fetched_at) <= self.cache_ttl:
            return cached.values
        values = await self._query_prefix(column, prefix.strip(), limit)
        self._search_cache[key] = _CacheEntry(values=values, fetched_at=now)
        return values

    async def _query_distinct(self, column: str) -> list[str]:
        sql = text(
            f"SELECT DISTINCT TOP {_DISTINCT_LIMIT} [{column}] AS value "
            f"FROM {VIEW_NAME} WHERE [{column}] IS NOT NULL"
        )
        return await self._run(sql, {})

    async def _query_prefix(self, column: str, prefix: str, limit: int) -> list[str]:
        escaped = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        sql = text(
            f"SELECT DISTINCT TOP {limit} [{column}] AS value "
            f"FROM {VIEW_NAME} WHERE [{column}] IS NOT NULL "
            f"AND [{column}] LIKE :prefix ESCAPE '\\'"
        )
        return await self._run(sql, {"prefix": f"{escaped}%"})

    async def _run(self, sql, params: dict) -> list[str]:
        try:
            async with self._session_factory() as session:
                result = await session.execute(sql, params)
                return [row[0] for row in result.fetchall() if row[0] is not None]
        except Exception as error:
            logger.warning("Value catalog query failed: %s", error)
            return []

    def invalidate(self) -> None:
        """Clears cached distinct-value and prefix-search results."""
        self._cache.clear()
        self._search_cache.clear()
