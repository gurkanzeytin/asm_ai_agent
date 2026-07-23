"""Doctor display-name enrichment (DOCTOR-DISPLAY-NAME-ENRICHMENT-001).

DoktorId stays the canonical analytical grouping key everywhere (QueryPlan,
generated SQL, internal sorting/joins/drill-down). This module only resolves
a human-readable display label for an already-grouped result, applied AFTER
SQL execution — never by adding a JOIN to generated analytical SQL and never
by regrouping/merging rows by name.

Resolution priority per DoktorId:
    1. official_lookup      — Hasta.uv_HizmetKaynakListesi (KaynakTipiAdi = 'Doktor')
    2. historical_fallback  — dominant stable token parsed from
                               dbo.vw_RandevuRaporu.GenelRandevuKaynakAdi
    3. id_fallback           — "DoktorId: <id>" (never an empty label, never an
                               arbitrary guess presented as fact)

Both lookups are batched (never one query per row/result). The official
lookup is small and cached broadly with a bounded TTL; historical fallback is
resolved only for the DoktorId values missing from the official lookup in
the current result, via a single grouped/aggregated query — never per-row
XML/string processing inside SQL.

A lookup failure degrades to id_fallback and never fails the analytical
query (see `enrich_query_result_with_doctor_labels`).
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field

from app.application_models.workflow_models import QueryResult
from app.planning.models import QueryPlan
from app.repositories.interfaces import IAnalyticalRepository
from app.semantics.view_mapping import fold

logger = logging.getLogger(__name__)

DOKTOR_ID_COLUMN = "DoktorId"
DOKTOR_ADI_COLUMN = "DoktorAdi"

SOURCE_OFFICIAL_LOOKUP = "official_lookup"
SOURCE_HISTORICAL_FALLBACK = "historical_fallback"
SOURCE_ID_FALLBACK = "id_fallback"

_OFFICIAL_LOOKUP_QUERY = """
SELECT KaynakId AS DoktorId, KaynakAdi AS DoktorAdi
FROM Hasta.uv_HizmetKaynakListesi
WHERE KaynakTipiAdi = N'Doktor'
  AND KaynakId IS NOT NULL
  AND KaynakAdi IS NOT NULL
GROUP BY KaynakId, KaynakAdi
"""

_NON_DOCTOR_LABELS_QUERY = """
SELECT DISTINCT KaynakAdi
FROM Hasta.uv_HizmetKaynakListesi
WHERE KaynakTipiAdi <> N'Doktor'
  AND KaynakAdi IS NOT NULL
"""

_HISTORICAL_FALLBACK_QUERY_TEMPLATE = """
SELECT DoktorId, GenelRandevuKaynakAdi, COUNT_BIG(*) AS KullanilmaSayisi
FROM dbo.vw_RandevuRaporu
WHERE DoktorId IN ({placeholders})
  AND GenelRandevuKaynakAdi IS NOT NULL
GROUP BY DoktorId, GenelRandevuKaynakAdi
"""


@dataclass(frozen=True)
class DoctorLabelEntry:
    """Resolved display label for one DoktorId — diagnostics only, never
    surfaced verbatim to the normal user-facing table."""

    doktor_id: int
    display_name: str
    source: str
    confidence: float | None = None
    conflicting_candidate_count: int = 0


def id_fallback_entry(doktor_id: int) -> DoctorLabelEntry:
    return DoctorLabelEntry(
        doktor_id=doktor_id,
        display_name=f"DoktorId: {doktor_id}",
        source=SOURCE_ID_FALLBACK,
    )


# ── Pure helpers (no I/O — fully unit-testable) ─────────────────────────────


def parse_source_tokens(raw: str) -> list[str]:
    """Splits a comma-separated GenelRandevuKaynakAdi string into trimmed,
    non-empty tokens, preserving original Turkish display text."""
    return [token.strip() for token in raw.split(",") if token.strip()]


def normalize_token(token: str) -> str:
    """Normalizes a token for matching only — never used for display."""
    return fold(token).strip()


def resolve_historical_entry(
    doktor_id: int,
    weighted_sources: list[tuple[str, int]],
    known_non_doctor_normalized: set[str],
) -> DoctorLabelEntry:
    """Selects the highest-confidence stable display token for one DoktorId
    from its weighted (GenelRandevuKaynakAdi, KullanilmaSayisi) rows.

    Deterministic: ties or an entirely device/resource-only candidate set
    fall back to id_fallback rather than presenting an arbitrary guess as
    fact. A token that is not a KNOWN non-doctor resource label is still not
    assumed to be a verified human doctor — it may be a stable team/resource
    label (e.g. "AMELİYAT EKİBİ") and is accepted as such.
    """
    token_weight: dict[str, int] = defaultdict(int)
    token_display: dict[str, str] = {}
    for source_string, weight in weighted_sources:
        for token in parse_source_tokens(source_string or ""):
            normalized = normalize_token(token)
            if not normalized:
                continue
            token_weight[normalized] += int(weight)
            # Deterministic tie-break for the display spelling of a normalized
            # token: keep the first-seen original text in stable (sorted)
            # processing order, never an arbitrary dict-iteration artifact.
            token_display.setdefault(normalized, token)

    candidates = {
        normalized: weight
        for normalized, weight in token_weight.items()
        if normalized not in known_non_doctor_normalized
    }
    if not candidates:
        return id_fallback_entry(doktor_id)

    max_weight = max(candidates.values())
    top_normalized = sorted(
        normalized for normalized, weight in candidates.items() if weight == max_weight
    )
    conflicting_candidate_count = len(candidates) - 1

    if len(top_normalized) > 1:
        # Tied dominant candidates: unreliable — never guess.
        logger.info(
            "Doctor label historical fallback tied for DoktorId=%s (%d tied candidates); "
            "using id_fallback.",
            doktor_id,
            len(top_normalized),
        )
        return id_fallback_entry(doktor_id)

    chosen_normalized = top_normalized[0]
    total_weight = sum(token_weight.values()) or 1
    return DoctorLabelEntry(
        doktor_id=doktor_id,
        display_name=token_display[chosen_normalized],
        source=SOURCE_HISTORICAL_FALLBACK,
        confidence=max_weight / total_weight,
        conflicting_candidate_count=conflicting_candidate_count,
    )


_DOCTOR_ID_REQUEST_MARKERS = (
    "doktor id",
    "doktorid",
    "doktor kimlik",
    "doktor numaras",
    "kaynak id",
    "kaynakid",
)


def question_requests_doctor_id(question: str | None) -> bool:
    """True when the user explicitly asked to see doctor identifiers — the
    only case where the raw DoktorId column is not hidden from the default
    user-facing table once DoktorAdi has been resolved."""
    if not question:
        return False
    folded = fold(question)
    return any(marker in folded for marker in _DOCTOR_ID_REQUEST_MARKERS)


# ── DB-backed resolver ──────────────────────────────────────────────────────


class DoctorLabelResolver:
    """Batched, cached, read-only doctor display-name resolver.

    Official lookup + the non-doctor resource-label set are small and loaded
    broadly with a bounded TTL (mirrors app.database_intelligence.cache.SchemaCache).
    Historical fallback is resolved only for the DoktorId values actually
    missing from the official lookup in the current result — never
    precomputed for the whole appointment history.
    """

    def __init__(
        self,
        repository: IAnalyticalRepository,
        ttl_seconds: float = 3600.0,
    ) -> None:
        self._repository = repository
        self._ttl_seconds = ttl_seconds
        self._official_by_id: dict[int, str] = {}
        self._non_doctor_normalized: set[str] = set()
        self._loaded_at: float = 0.0
        self._loaded = False
        self._lock = asyncio.Lock()

    async def refresh(self) -> None:
        """Forces an immediate reload of the official lookup + non-doctor set."""
        async with self._lock:
            await self._load_locked()

    def invalidate(self) -> None:
        self._loaded = False
        self._loaded_at = 0.0

    async def _ensure_loaded(self) -> None:
        is_expired = self._loaded and (time.monotonic() - self._loaded_at) > self._ttl_seconds
        if self._loaded and not is_expired:
            return
        async with self._lock:
            # Re-check under the lock: another coroutine may have refreshed
            # while this one was waiting.
            is_expired = self._loaded and (time.monotonic() - self._loaded_at) > self._ttl_seconds
            if self._loaded and not is_expired:
                return
            await self._load_locked()

    async def _load_locked(self) -> None:
        try:
            official_rows = await self._repository.execute_query(_OFFICIAL_LOOKUP_QUERY)
            non_doctor_rows = await self._repository.execute_query(_NON_DOCTOR_LABELS_QUERY)
        except Exception as error:
            logger.warning(
                "Doctor label official lookup unavailable; falling back to id_fallback "
                "for this cycle. error_type=%s",
                type(error).__name__,
            )
            return

        by_id: dict[int, list[str]] = defaultdict(list)
        for row in official_rows:
            doktor_id = row.get("DoktorId")
            name = row.get("DoktorAdi")
            if doktor_id is None or not name:
                continue
            by_id[int(doktor_id)].append(str(name))

        resolved: dict[int, str] = {}
        for doktor_id, names in by_id.items():
            distinct_names = sorted(set(names))
            if len(distinct_names) > 1:
                logger.info(
                    "Doctor label official lookup has %d conflicting names for one "
                    "DoktorId; choosing deterministically (max).",
                    len(distinct_names),
                )
            resolved[doktor_id] = distinct_names[-1]

        self._official_by_id = resolved
        self._non_doctor_normalized = {
            normalize_token(str(row.get("KaynakAdi")))
            for row in non_doctor_rows
            if row.get("KaynakAdi")
        }
        self._loaded_at = time.monotonic()
        self._loaded = True

    async def resolve(self, doktor_ids: list[int]) -> dict[int, DoctorLabelEntry]:
        """Batched resolution for every requested DoktorId — never one query
        per row. Always returns an entry for every input id (never empty)."""
        ids = sorted({int(value) for value in doktor_ids if value is not None})
        if not ids:
            return {}

        await self._ensure_loaded()

        entries: dict[int, DoctorLabelEntry] = {}
        unmatched: list[int] = []
        for doktor_id in ids:
            official_name = self._official_by_id.get(doktor_id)
            if official_name:
                entries[doktor_id] = DoctorLabelEntry(
                    doktor_id=doktor_id,
                    display_name=official_name,
                    source=SOURCE_OFFICIAL_LOOKUP,
                )
            else:
                unmatched.append(doktor_id)

        if unmatched:
            grouped = await self._fetch_historical_rows(unmatched)
            for doktor_id in unmatched:
                entries[doktor_id] = resolve_historical_entry(
                    doktor_id, grouped.get(doktor_id, []), self._non_doctor_normalized
                )

        return entries

    async def _fetch_historical_rows(
        self, doktor_ids: list[int]
    ) -> dict[int, list[tuple[str, int]]]:
        placeholders = ", ".join(f":id{index}" for index in range(len(doktor_ids)))
        params = {f"id{index}": doktor_id for index, doktor_id in enumerate(doktor_ids)}
        query = _HISTORICAL_FALLBACK_QUERY_TEMPLATE.format(placeholders=placeholders)
        try:
            rows = await self._repository.execute_query(query, params)
        except Exception as error:
            logger.warning(
                "Doctor label historical fallback lookup failed for %d unmatched "
                "DoktorId values; using id_fallback. error_type=%s",
                len(doktor_ids),
                type(error).__name__,
            )
            return {}

        grouped: dict[int, list[tuple[str, int]]] = defaultdict(list)
        for row in rows:
            doktor_id = row.get("DoktorId")
            source_string = row.get("GenelRandevuKaynakAdi")
            weight = row.get("KullanilmaSayisi")
            if doktor_id is None or not source_string or weight is None:
                continue
            grouped[int(doktor_id)].append((str(source_string), int(weight)))
        return grouped


# ── Result enrichment (the sole write path into QueryResult) ───────────────


async def enrich_query_result_with_doctor_labels(
    query_result: QueryResult,
    plan: QueryPlan | None,
    resolver: DoctorLabelResolver | None,
    *,
    raw_question: str | None = None,
) -> QueryResult:
    """Adds a DoktorAdi display column to an already-executed, already-grouped
    result. Never changes row_count, never merges rows, never touches
    DoktorId or the metric values — purely additive, and always degrades
    gracefully (a lookup failure returns the original result with an
    id_fallback label, never an exception)."""
    if resolver is None or DOKTOR_ID_COLUMN not in query_result.columns or not query_result.rows:
        return query_result

    doktor_ids = [row.get(DOKTOR_ID_COLUMN) for row in query_result.rows]
    try:
        entries = await resolver.resolve([value for value in doktor_ids if value is not None])
    except Exception as error:  # pragma: no cover — resolver.resolve already degrades internally
        logger.warning(
            "Doctor label enrichment failed unexpectedly; returning raw DoktorId. "
            "error_type=%s",
            type(error).__name__,
        )
        entries = {}

    new_rows: list[dict] = []
    for row in query_result.rows:
        doktor_id = row.get(DOKTOR_ID_COLUMN)
        if doktor_id is None:
            display_name = ""
        else:
            entry = entries.get(int(doktor_id)) or id_fallback_entry(int(doktor_id))
            display_name = entry.display_name
        new_rows.append({DOKTOR_ADI_COLUMN: display_name, **row})

    new_columns = [DOKTOR_ADI_COLUMN] + [c for c in query_result.columns if c != DOKTOR_ADI_COLUMN]

    hidden_columns = list(query_result.hidden_columns)
    if not question_requests_doctor_id(raw_question) and DOKTOR_ID_COLUMN not in hidden_columns:
        hidden_columns.append(DOKTOR_ID_COLUMN)

    return query_result.model_copy(
        update={
            "columns": new_columns,
            "rows": new_rows,
            "hidden_columns": hidden_columns,
        }
    )
