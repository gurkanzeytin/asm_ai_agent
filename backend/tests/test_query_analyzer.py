import json
import logging
from datetime import date

import pytest

from app.database_intelligence.models import (
    ColumnMetadata,
    DatabaseSchema,
    SchemaStatistics,
    TableMetadata,
)
from app.database_intelligence.retriever import SchemaRetriever
from app.database_intelligence.schema_graph import SchemaGraph
from app.services.query_analyzer import QueryAnalyzer


def test_query_analyzer_synonym_resolution_and_rewrite():
    analyzer = QueryAnalyzer(today=date(2026, 7, 10))

    analysis = analyzer.analyze("En yoğun doktor kim?")

    assert analysis.normalized_query == "en fazla randevusu olan doktor kim"
    assert "yoğun -> en fazla randevu" in analysis.matched_synonyms
    assert {entity.entity_type for entity in analysis.entities} == {"Doctor", "Appointment"}
    assert analysis.confidence > 0.7


def test_query_analyzer_entity_extraction_with_turkish_suffixes():
    analyzer = QueryAnalyzer(today=date(2026, 7, 10))

    analysis = analyzer.analyze("Kardiyoloji doktorlarının yazdığı reçeteler")

    entity_types = {entity.entity_type for entity in analysis.entities}
    assert {"Department", "Doctor", "Prescription"}.issubset(entity_types)


def test_query_analyzer_temporal_normalization():
    analyzer = QueryAnalyzer(today=date(2026, 7, 10))

    analysis = analyzer.analyze("Geçen ay kaç hasta geldi?")

    assert analysis.detected_dates
    date_range = analysis.detected_dates[0]
    assert date_range.start_date == date(2026, 6, 1)
    assert date_range.end_date == date(2026, 6, 30)
    assert date_range.granularity == "month"
    assert any(entity.entity_type == "Patient" for entity in analysis.entities)


@pytest.mark.parametrize(
    ("query", "expected_start", "expected_end"),
    [
        ("son 7 gün randevuları", date(2026, 7, 4), date(2026, 7, 10)),
        ("2025 yılında hasta sayısı", date(2025, 1, 1), date(2025, 12, 31)),
        ("Ocak ayında randevu sayısı", date(2026, 1, 1), date(2026, 1, 31)),
    ],
)
def test_query_analyzer_temporal_variants(query, expected_start, expected_end):
    analyzer = QueryAnalyzer(today=date(2026, 7, 10))

    analysis = analyzer.analyze(query)

    assert analysis.detected_dates[0].start_date == expected_start
    assert analysis.detected_dates[0].end_date == expected_end


@pytest.mark.parametrize(
    ("query", "expected_normalized", "expected_synonym"),
    [
        (
            "Kalp doktorlarını listele",
            "kardiyoloji doktorlarını listele",
            "kalp -> kardiyoloji",
        ),
        (
            "Çocuk doktorlarını göster",
            "cocuk sagligi doktorlarını göster",
            "çocuk -> çocuk sağlığı",
        ),
        (
            "Pediatri doktorları",
            "cocuk sagligi doktorları",
            "pediatri -> çocuk sağlığı",
        ),
        (
            "Kadın doğum doktorları",
            "kadin hastaliklari ve dogum doktorları",
            "kadın doğum -> kadın hastalıkları ve doğum",
        ),
        (
            "Hekim listesi",
            "doktor listesi",
            "hekim -> doktor",
        ),
        (
            "Hekimleri göster",
            "doktorları göster",
            "hekim -> doktor",
        ),
        (
            "Hekimleri listele",
            "doktorları listele",
            "hekim -> doktor",
        ),
        (
            "Hekime sor",
            "doktora sor",
            "hekim -> doktor",
        ),
        (
            "Muayeneleri göster",
            "randevuları göster",
            "muayene -> randevu",
        ),
        (
            "Muayene sayısı",
            "randevu sayısı",
            "muayene -> randevu",
        ),
        (
            "En yoğun klinik",
            "en fazla randevusu olan poliklinik",
            "klinik -> poliklinik",
        ),
        (
            "Kaç kontrol yapıldı",
            "kaç kontrol randevusu yapıldı",
            "kontrol -> kontrol randevusu",
        ),
    ],
)
def test_query_analyzer_domain_synonym_normalization(
    query, expected_normalized, expected_synonym
):
    analyzer = QueryAnalyzer(today=date(2026, 7, 10))

    analysis = analyzer.analyze(query)

    assert analysis.normalized_query == expected_normalized
    assert expected_synonym in analysis.matched_synonyms


def test_query_analyzer_kalp_rewrite_detects_department_entity():
    analyzer = QueryAnalyzer(today=date(2026, 7, 10))

    analysis = analyzer.analyze("Kalp doktorlarını listele")

    assert {"Department", "Doctor"}.issubset(
        {entity.entity_type for entity in analysis.entities}
    )


def test_query_analyzer_cocuk_rewrite_requires_department_context():
    analyzer = QueryAnalyzer(today=date(2026, 7, 10))

    analysis = analyzer.analyze("Kaç çocuk hasta geldi")

    assert "sagligi" not in analysis.normalized_query
    assert "çocuk -> çocuk sağlığı" not in analysis.matched_synonyms


def test_query_analyzer_kontrol_randevu_not_rewritten_twice():
    analyzer = QueryAnalyzer(today=date(2026, 7, 10))

    analysis = analyzer.analyze("Kontrol randevusu sayısı")

    assert analysis.normalized_query == "kontrol randevusu sayısı"


def test_query_analyzer_kbb_rewrite():
    analyzer = QueryAnalyzer(today=date(2026, 7, 10))

    analysis = analyzer.analyze("KBB doktorları")

    assert analysis.normalized_query == "kulak burun bogaz bolumundeki doktorlar"
    assert "kbb -> kulak burun bogaz" in analysis.matched_synonyms
    assert {"Department", "Doctor"}.issubset({entity.entity_type for entity in analysis.entities})


def test_query_analyzer_debug_diagnostics(caplog):
    analyzer = QueryAnalyzer(today=date(2026, 7, 10))

    with caplog.at_level(logging.INFO):
        analyzer.analyze("Muayene sayısı")

    record = next(rec for rec in caplog.records if "QUERY ANALYSIS" in rec.message)
    assert record.original_query == "Muayene sayısı"
    assert record.normalized_query == "randevu sayısı"
    assert "muayene -> randevu" in record.matched_synonyms


def test_query_analyzer_hot_reload(tmp_path):
    synonyms_path = tmp_path / "domain_synonyms.json"
    synonyms_path.write_text(
        json.dumps(
            {
                "entities": {
                    "Doctor": {"canonical": "doktor", "terms": ["doktor"]},
                },
                "rewrites": [],
            }
        ),
        encoding="utf-8",
    )
    analyzer = QueryAnalyzer(synonyms_path=synonyms_path, today=date(2026, 7, 10))
    assert analyzer.analyze("hekim listesi").entities == []

    synonyms_path.write_text(
        json.dumps(
            {
                "entities": {
                    "Doctor": {"canonical": "doktor", "terms": ["doktor", "hekim"]},
                },
                "rewrites": [],
            }
        ),
        encoding="utf-8",
    )

    analysis = analyzer.analyze("hekim listesi")

    assert any(entity.entity_type == "Doctor" for entity in analysis.entities)


@pytest.mark.asyncio
async def test_schema_retriever_uses_normalized_query_and_entity_boost():
    col_id = ColumnMetadata(name="id", type_name="INTEGER", nullable=False, primary_key=True)
    table_doctors = TableMetadata(
        name="doktorlar",
        columns=[col_id],
        primary_keys=["id"],
        foreign_keys=[],
        comment="Doktor randevu bilgileri",
    )
    schema = DatabaseSchema(
        tables={"doktorlar": table_doctors},
        views={},
        statistics=SchemaStatistics(
            table_count=1,
            column_count=1,
            foreign_key_count=0,
            view_count=0,
        ),
        fingerprint="fp-query-analysis",
    )

    class FakeIndex:
        last_embedding_error = None

        def __init__(self):
            self.search_queries = []

        async def search(self, query, k=5):
            self.search_queries.append(query)
            return []

    fake_index = FakeIndex()
    fake_cache = type(
        "FakeCache",
        (),
        {
            "get_graph": lambda self: _async_value(SchemaGraph(schema)),
            "get_index": lambda self: _async_value(fake_index),
        },
    )()
    retriever = SchemaRetriever(schema_cache=fake_cache, match_threshold=1)

    context = retriever.retrieve_context("En yoğun doktor kim?", schema)

    assert fake_index.search_queries == ["en fazla randevusu olan doktor kim"]
    assert [table.name for table in context.tables] == ["doktorlar"]
    assert context.normalized_query == "en fazla randevusu olan doktor kim"


@pytest.mark.asyncio
async def test_schema_retriever_resolves_cocuk_to_real_department_vocabulary():
    col_id = ColumnMetadata(name="id", type_name="INTEGER", nullable=False, primary_key=True)
    table_doctors = TableMetadata(
        name="doktorlar",
        columns=[col_id],
        primary_keys=["id"],
        foreign_keys=[],
        comment="Doktor bilgileri",
    )
    table_departments = TableMetadata(
        name="bolumler",
        columns=[col_id],
        primary_keys=["id"],
        foreign_keys=[],
        comment="Bolum adlari: Kardiyoloji, Cocuk Sagligi",
    )
    schema = DatabaseSchema(
        tables={"doktorlar": table_doctors, "bolumler": table_departments},
        views={},
        statistics=SchemaStatistics(
            table_count=2,
            column_count=2,
            foreign_key_count=0,
            view_count=0,
        ),
        fingerprint="fp-cocuk-sagligi",
    )

    class FakeIndex:
        last_embedding_error = None

        def __init__(self):
            self.search_queries = []

        async def search(self, query, k=5):
            self.search_queries.append(query)
            return []

    fake_index = FakeIndex()
    fake_cache = type(
        "FakeCache",
        (),
        {
            "get_graph": lambda self: _async_value(SchemaGraph(schema)),
            "get_index": lambda self: _async_value(fake_index),
        },
    )()
    retriever = SchemaRetriever(schema_cache=fake_cache, match_threshold=1)

    context = retriever.retrieve_context("Çocuk doktorlarını göster", schema)

    assert fake_index.search_queries == ["cocuk sagligi doktorlarını göster"]
    assert context.normalized_query == "cocuk sagligi doktorlarını göster"
    retrieved = {table.name for table in context.tables}
    assert {"doktorlar", "bolumler"}.issubset(retrieved)


@pytest.mark.asyncio
async def test_generate_sql_node_receives_normalized_query():
    from unittest.mock import AsyncMock

    from app.agent.nodes.generate_sql import GenerateSQLNode
    from app.agent.state import AgentState
    from app.database_intelligence.models import DatabaseContext

    workflow_service = AsyncMock()
    context = DatabaseContext(
        tables=[],
        views=[],
        normalized_query="kardiyoloji doktorlarını listele",
    )
    state = AgentState(question="Kalp doktorlarını listele", database_context=context)

    await GenerateSQLNode(workflow_service).execute(state)

    workflow_service.execute_sql_generation.assert_awaited_once_with(
        "kardiyoloji doktorlarını listele",
        database_context=context,
        error_feedback=None,
        query_plan=None,
    )


async def _async_value(value):
    return value
