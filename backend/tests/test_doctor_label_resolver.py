"""DOCTOR-DISPLAY-NAME-ENRICHMENT-001 resolver unit tests (A-J from the spec).

Covers: official lookup + dedup, historical fallback token parsing/weighting/
device-rejection/tie-breaking, team/resource labels, no-match id_fallback,
same-name-different-id grouping integrity, empty results, and DB failure
degradation. No live database — a fake IAnalyticalRepository stands in.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.application_models.workflow_models import QueryResult
from app.services.doctor_label_resolver import (
    DOKTOR_ADI_COLUMN,
    DOKTOR_ID_COLUMN,
    SOURCE_HISTORICAL_FALLBACK,
    SOURCE_ID_FALLBACK,
    SOURCE_OFFICIAL_LOOKUP,
    DoctorLabelResolver,
    enrich_query_result_with_doctor_labels,
    normalize_token,
    parse_source_tokens,
    question_requests_doctor_id,
    resolve_historical_entry,
)


def make_query_result(columns: list[str], rows: list[dict]) -> QueryResult:
    return QueryResult(
        columns=columns,
        rows=rows,
        row_count=len(rows),
        execution_time_ms=1.0,
        success=True,
        executed_at=datetime.now(UTC),
        database_provider="mssql",
    )


class FakeRepository:
    """Minimal IAnalyticalRepository stand-in: dispatches by which literal
    query template is executed, ignoring exact whitespace."""

    def __init__(
        self,
        official_rows: list[dict] | None = None,
        non_doctor_rows: list[dict] | None = None,
        historical_rows: list[dict] | None = None,
        raise_on: str | None = None,
    ):
        self.official_rows = official_rows or []
        self.non_doctor_rows = non_doctor_rows or []
        self.historical_rows = historical_rows or []
        self.raise_on = raise_on
        self.queries: list[str] = []

    async def execute_query(self, query: str, params: dict | None = None):
        self.queries.append(query)
        if "Hasta.uv_HizmetKaynakListesi" in query and "KaynakTipiAdi = N'Doktor'" in query:
            if self.raise_on == "official":
                raise RuntimeError("simulated official lookup failure")
            return self.official_rows
        if "KaynakTipiAdi <> N'Doktor'" in query:
            if self.raise_on == "non_doctor":
                raise RuntimeError("simulated non-doctor lookup failure")
            return self.non_doctor_rows
        if "dbo.vw_RandevuRaporu" in query:
            if self.raise_on == "historical":
                raise RuntimeError("simulated historical fallback failure")
            return self.historical_rows
        raise AssertionError(f"unexpected query: {query}")

    async def execute_readonly_query(self, sql: str):
        raise NotImplementedError

    async def execute_scalar(self, query: str, params: dict | None = None):
        raise NotImplementedError

    async def fetch_paged_query(self, query: str, *, skip=0, limit=100, params=None):
        raise NotImplementedError


# ── Pure helper tests ────────────────────────────────────────────────────────


def test_parse_source_tokens_trims_and_drops_empty():
    assert parse_source_tokens("SDS-Endoskopi-2,ABDULKADİR KEMAL TAHAOĞLU, ,") == [
        "SDS-Endoskopi-2",
        "ABDULKADİR KEMAL TAHAOĞLU",
    ]


def test_normalize_token_folds_but_does_not_mutate_display_text():
    assert normalize_token("ÇAĞATAY ÖKTENLİ") == "cagatay oktenli"


class TestQuestionRequestsDoctorId:
    @pytest.mark.parametrize(
        "question",
        ["Doktor ID'lerini de göster.", "doktorid bilgisiyle göster", "Kaynak ID nedir?"],
    )
    def test_true_cases(self, question):
        assert question_requests_doctor_id(question) is True

    def test_false_for_plain_grouping_question(self):
        assert question_requests_doctor_id("Doktor bazında randevu sayılarını göster.") is False

    def test_false_for_none(self):
        assert question_requests_doctor_id(None) is False


# A. Official lookup


@pytest.mark.asyncio
async def test_official_lookup_resolves_known_doctor():
    repo = FakeRepository(official_rows=[{"DoktorId": 7773, "DoktorAdi": "ÇAĞATAY ÖKTENLİ"}])
    resolver = DoctorLabelResolver(repo)

    entries = await resolver.resolve([7773])

    assert entries[7773].display_name == "ÇAĞATAY ÖKTENLİ"
    assert entries[7773].source == SOURCE_OFFICIAL_LOOKUP


@pytest.mark.asyncio
async def test_official_lookup_enriches_result_without_changing_count_or_raw_id():
    repo = FakeRepository(official_rows=[{"DoktorId": 7773, "DoktorAdi": "ÇAĞATAY ÖKTENLİ"}])
    resolver = DoctorLabelResolver(repo)
    result = make_query_result(
        [DOKTOR_ID_COLUMN, "appointment_count"], [{"DoktorId": 7773, "appointment_count": 43232}]
    )

    enriched = await enrich_query_result_with_doctor_labels(result, None, resolver)

    assert enriched.rows[0][DOKTOR_ADI_COLUMN] == "ÇAĞATAY ÖKTENLİ"
    assert enriched.rows[0]["appointment_count"] == 43232
    assert enriched.rows[0][DOKTOR_ID_COLUMN] == 7773
    assert enriched.row_count == result.row_count
    assert DOKTOR_ID_COLUMN in enriched.hidden_columns


# B. Official lookup deduplication


@pytest.mark.asyncio
async def test_official_lookup_dedups_same_doctor_across_branches():
    repo = FakeRepository(
        official_rows=[
            {"DoktorId": 100, "DoktorAdi": "AHMET YILMAZ"},
            {"DoktorId": 100, "DoktorAdi": "AHMET YILMAZ"},
        ]
    )
    resolver = DoctorLabelResolver(repo)

    entries = await resolver.resolve([100])

    assert len(entries) == 1
    assert entries[100].display_name == "AHMET YILMAZ"

    result = make_query_result(
        [DOKTOR_ID_COLUMN, "appointment_count"], [{"DoktorId": 100, "appointment_count": 10}]
    )
    enriched = await enrich_query_result_with_doctor_labels(result, None, resolver)
    assert enriched.row_count == 1
    assert enriched.rows[0]["appointment_count"] == 10


# C. Historical fallback — simple doctor label


def test_historical_fallback_selects_simple_label():
    entry = resolve_historical_entry(
        9999, [("FATMA ELA TAHMAZ GÜNDOĞDU,", 12)], known_non_doctor_normalized=set()
    )
    assert entry.display_name == "FATMA ELA TAHMAZ GÜNDOĞDU"
    assert entry.source == SOURCE_HISTORICAL_FALLBACK


# D. Historical fallback — device plus doctor


def test_historical_fallback_rejects_known_device_token():
    known_non_doctor = {normalize_token("SDS-Endoskopi-2")}
    entry = resolve_historical_entry(
        8888,
        [("SDS-Endoskopi-2,ABDULKADİR KEMAL TAHAOĞLU,", 30)],
        known_non_doctor_normalized=known_non_doctor,
    )
    assert entry.display_name == "ABDULKADİR KEMAL TAHAOĞLU"
    assert entry.source == SOURCE_HISTORICAL_FALLBACK


# E. Historical fallback — multiple resources, weighted deterministic pick


def test_historical_fallback_picks_weighted_dominant_token_deterministically():
    entry = resolve_historical_entry(
        7000,
        [
            ("DR A, DR B,", 5),
            ("DR A,", 50),
            ("DR C,", 3),
        ],
        known_non_doctor_normalized=set(),
    )
    # DR A: 5 + 50 = 55, DR B: 5, DR C: 3 -> DR A wins unambiguously.
    assert entry.display_name == "DR A"
    assert entry.conflicting_candidate_count == 2

    # Re-running must be fully deterministic (no arbitrary MAX-string behavior).
    entry_again = resolve_historical_entry(
        7000,
        [("DR A, DR B,", 5), ("DR A,", 50), ("DR C,", 3)],
        known_non_doctor_normalized=set(),
    )
    assert entry_again.display_name == entry.display_name


def test_historical_fallback_tied_candidates_prefer_id_fallback():
    entry = resolve_historical_entry(
        6000, [("DR A,", 10), ("DR B,", 10)], known_non_doctor_normalized=set()
    )
    assert entry.source == SOURCE_ID_FALLBACK
    assert entry.display_name == "DoktorId: 6000"


# F. Team/resource label


def test_team_label_accepted_as_stable_historical_display_without_person_claim():
    entry = resolve_historical_entry(
        5000, [("AMELİYAT EKİBİ,", 20)], known_non_doctor_normalized=set()
    )
    assert entry.display_name == "AMELİYAT EKİBİ"
    assert entry.source == SOURCE_HISTORICAL_FALLBACK
    assert not entry.display_name.startswith(("Dr.", "Uzm.", "Prof.", "Op."))


# G. No match


def test_no_official_and_no_reliable_historical_candidate_falls_back_to_id():
    entry = resolve_historical_entry(12345, [], known_non_doctor_normalized=set())
    assert entry.display_name == "DoktorId: 12345"
    assert entry.source == SOURCE_ID_FALLBACK


@pytest.mark.asyncio
async def test_no_match_anywhere_resolves_via_resolver():
    repo = FakeRepository(official_rows=[], non_doctor_rows=[], historical_rows=[])
    resolver = DoctorLabelResolver(repo)

    entries = await resolver.resolve([12345])

    assert entries[12345].display_name == "DoktorId: 12345"
    assert entries[12345].source == SOURCE_ID_FALLBACK


# H. Same name, multiple IDs — rows never merged


@pytest.mark.asyncio
async def test_same_resolved_name_for_two_ids_keeps_rows_separate():
    repo = FakeRepository(
        official_rows=[
            {"DoktorId": 1, "DoktorAdi": "AYNI İSİM"},
            {"DoktorId": 2, "DoktorAdi": "AYNI İSİM"},
        ]
    )
    resolver = DoctorLabelResolver(repo)
    result = make_query_result(
        [DOKTOR_ID_COLUMN, "appointment_count"],
        [
            {"DoktorId": 1, "appointment_count": 10},
            {"DoktorId": 2, "appointment_count": 25},
        ],
    )

    enriched = await enrich_query_result_with_doctor_labels(result, None, resolver)

    assert enriched.row_count == 2
    names = [row[DOKTOR_ADI_COLUMN] for row in enriched.rows]
    assert names == ["AYNI İSİM", "AYNI İSİM"]
    counts = [row["appointment_count"] for row in enriched.rows]
    assert counts == [10, 25]
    ids = [row[DOKTOR_ID_COLUMN] for row in enriched.rows]
    assert ids == [1, 2]


# I. Empty result


@pytest.mark.asyncio
async def test_empty_result_is_returned_unchanged():
    repo = FakeRepository()
    resolver = DoctorLabelResolver(repo)
    result = make_query_result([DOKTOR_ID_COLUMN, "appointment_count"], [])

    enriched = await enrich_query_result_with_doctor_labels(result, None, resolver)

    assert enriched.row_count == 0
    assert enriched.rows == []
    assert not repo.queries  # never queried the DB for an empty result


# J. Lookup database failure


@pytest.mark.asyncio
async def test_official_lookup_failure_degrades_to_id_fallback_without_raising():
    repo = FakeRepository(raise_on="official")
    resolver = DoctorLabelResolver(repo)
    result = make_query_result(
        [DOKTOR_ID_COLUMN, "appointment_count"], [{"DoktorId": 42, "appointment_count": 3}]
    )

    enriched = await enrich_query_result_with_doctor_labels(result, None, resolver)

    assert enriched.row_count == 1
    assert enriched.rows[0][DOKTOR_ADI_COLUMN] == "DoktorId: 42"
    assert enriched.rows[0]["appointment_count"] == 3


@pytest.mark.asyncio
async def test_historical_fallback_failure_degrades_to_id_fallback_without_raising():
    repo = FakeRepository(official_rows=[], non_doctor_rows=[], raise_on="historical")
    resolver = DoctorLabelResolver(repo)

    entries = await resolver.resolve([555])

    assert entries[555].display_name == "DoktorId: 555"
    assert entries[555].source == SOURCE_ID_FALLBACK


@pytest.mark.asyncio
async def test_enrichment_never_raises_when_resolver_is_none():
    result = make_query_result(
        [DOKTOR_ID_COLUMN, "appointment_count"], [{"DoktorId": 42, "appointment_count": 3}]
    )
    enriched = await enrich_query_result_with_doctor_labels(result, None, resolver=None)
    assert enriched is result


# Explicit doctor-ID request keeps DoktorId visible (test K, resolver-level slice)


@pytest.mark.asyncio
async def test_explicit_doctor_id_request_does_not_hide_doktor_id_column():
    repo = FakeRepository(official_rows=[{"DoktorId": 7773, "DoktorAdi": "ÇAĞATAY ÖKTENLİ"}])
    resolver = DoctorLabelResolver(repo)
    result = make_query_result(
        [DOKTOR_ID_COLUMN, "appointment_count"], [{"DoktorId": 7773, "appointment_count": 5}]
    )

    enriched = await enrich_query_result_with_doctor_labels(
        result, None, resolver, raw_question="Doktor ID'lerini de göster."
    )

    assert DOKTOR_ID_COLUMN not in enriched.hidden_columns
    assert enriched.rows[0][DOKTOR_ID_COLUMN] == 7773


# Cache TTL / batching behavior


@pytest.mark.asyncio
async def test_official_lookup_is_loaded_once_and_reused_across_calls():
    repo = FakeRepository(official_rows=[{"DoktorId": 1, "DoktorAdi": "A"}])
    resolver = DoctorLabelResolver(repo, ttl_seconds=3600.0)

    await resolver.resolve([1])
    await resolver.resolve([1])

    official_query_count = sum(
        1 for q in repo.queries if "KaynakTipiAdi = N'Doktor'" in q
    )
    assert official_query_count == 1


@pytest.mark.asyncio
async def test_historical_fallback_batches_all_unmatched_ids_in_one_query():
    repo = FakeRepository(
        official_rows=[],
        non_doctor_rows=[],
        historical_rows=[
            {"DoktorId": 1, "GenelRandevuKaynakAdi": "DR A,", "KullanilmaSayisi": 5},
            {"DoktorId": 2, "GenelRandevuKaynakAdi": "DR B,", "KullanilmaSayisi": 7},
        ],
    )
    resolver = DoctorLabelResolver(repo)

    entries = await resolver.resolve([1, 2])

    historical_query_count = sum(1 for q in repo.queries if "dbo.vw_RandevuRaporu" in q)
    assert historical_query_count == 1
    assert entries[1].display_name == "DR A"
    assert entries[2].display_name == "DR B"
