import logging
import time
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.application_models.workflow_models import QueryResult
from app.database_intelligence.models import (
    ColumnMetadata,
    DatabaseContext,
    DatabaseSchema,
    SchemaStatistics,
    TableMetadata,
)
from app.database_intelligence.retriever import SchemaRetriever
from app.database_intelligence.schema_graph import SchemaGraph
from app.prompts.loader import PromptLoader
from app.prompts.renderer import DefaultPromptRenderer
from app.services.prompt_service import PromptService
from app.services.report_service import ReportService


def test_sql_prompt_template_is_compact():
    prompt_path = Path("app/prompts/sql_generation.md")
    prompt_text = prompt_path.read_text(encoding="utf-8")

    assert len(prompt_text) < 900
    assert "BAD OUTPUT" not in prompt_text
    assert "GOOD OUTPUT" not in prompt_text


@pytest.mark.asyncio
async def test_schema_context_compression_reduces_unused_columns():
    columns = [
        ColumnMetadata(name="id", type_name="INTEGER", nullable=False, primary_key=True),
        ColumnMetadata(
            name="doktor_id", type_name="INTEGER", nullable=False, primary_key=False
        ),
        ColumnMetadata(name="hasta_id", type_name="INTEGER", nullable=False, primary_key=False),
        ColumnMetadata(name="randevu_tarihi", type_name="DATE", nullable=True, primary_key=False),
        ColumnMetadata(name="randevu_saati", type_name="TEXT", nullable=True, primary_key=False),
        ColumnMetadata(name="telefon", type_name="TEXT", nullable=True, primary_key=False),
        ColumnMetadata(name="adres", type_name="TEXT", nullable=True, primary_key=False),
        ColumnMetadata(name="notlar", type_name="TEXT", nullable=True, primary_key=False),
        ColumnMetadata(
            name="olusturulma_tarihi",
            type_name="DATETIME",
            nullable=True,
            primary_key=False,
        ),
        ColumnMetadata(
            name="guncelleme_tarihi",
            type_name="DATETIME",
            nullable=True,
            primary_key=False,
        ),
    ]
    table = TableMetadata(
        name="randevular",
        columns=columns,
        primary_keys=["id"],
        foreign_keys=[],
    )
    context = DatabaseContext(tables=[table], views=[])
    prompt_service = PromptService(
        schema_cache=AsyncMock(),
        schema_retriever=MagicMock(),
        prompt_loader=PromptLoader(),
        prompt_renderer=DefaultPromptRenderer(),
    )

    compressed = prompt_service._format_context(context, question="Bugunku randevu sayisi nedir?")
    uncompressed = "Table: randevular\n  Columns: " + ", ".join(
        f"{col.name} ({col.type_name}){' [PK]' if col.primary_key else ''}" for col in columns
    )

    assert len(compressed) < len(uncompressed)
    assert "id (INTEGER) [PK]" in compressed
    assert "randevu_tarihi" in compressed
    assert "telefon" not in compressed
    assert "adres" not in compressed


@pytest.mark.asyncio
async def test_template_report_bypasses_llm_for_simple_result():
    prompt_service = AsyncMock()
    llm_provider = AsyncMock()
    generator = AsyncMock()
    service = ReportService(prompt_service, llm_provider, generator=generator)
    query_result = QueryResult(
        columns=["doktor_sayisi"],
        rows=[{"doktor_sayisi": 45}],
        row_count=1,
        execution_time_ms=1.0,
        success=True,
        executed_at=datetime.now(),
        database_provider="sqlite",
    )

    report = await service.generate_report(
        "Kac doktor var?",
        "SELECT COUNT(*) AS doktor_sayisi FROM doktorlar",
        query_result,
    )

    assert report.provider == "template"
    generator.generate.assert_not_called()
    prompt_service.render_report_prompt.assert_not_called()


@pytest.mark.asyncio
async def test_large_list_report_bypasses_llm_regression():
    prompt_service = AsyncMock()
    llm_provider = AsyncMock()
    generator = AsyncMock()
    service = ReportService(prompt_service, llm_provider, generator=generator)
    rows = [{"id": i, "ad_soyad": f"Doktor {i}"} for i in range(45)]
    query_result = QueryResult(
        columns=["id", "ad_soyad"],
        rows=rows,
        row_count=len(rows),
        execution_time_ms=1.0,
        success=True,
        executed_at=datetime.now(),
        database_provider="sqlite",
    )

    started = time.perf_counter()
    report = await service.generate_report(
        "Doktorlari listele",
        "SELECT * FROM doktorlar",
        query_result,
    )
    elapsed_ms = (time.perf_counter() - started) * 1000

    assert elapsed_ms < 100
    assert report.provider == "template"
    assert report.model == "table"
    generator.generate.assert_not_called()
    prompt_service.render_report_prompt.assert_not_called()


def test_schema_retrieval_latency_profile_is_logged(caplog):
    col_id = ColumnMetadata(name="id", type_name="INTEGER", nullable=False, primary_key=True)
    table = TableMetadata(
        name="doktorlar",
        columns=[col_id],
        primary_keys=["id"],
        foreign_keys=[],
        comment="Doktor randevu bilgileri",
    )
    schema = DatabaseSchema(
        tables={"doktorlar": table},
        views={},
        statistics=SchemaStatistics(
            table_count=1,
            column_count=1,
            foreign_key_count=0,
            view_count=0,
        ),
        fingerprint="fp-performance",
    )

    class FakeIndex:
        last_embedding_error = None

        async def search(self, query, k=5):
            return [("doktorlar", 0.9)]

    class FakeCache:
        async def get_graph(self):
            return SchemaGraph(schema)

        async def get_index(self):
            return FakeIndex()

    retriever = SchemaRetriever(schema_cache=FakeCache(), match_threshold=1)

    started = time.perf_counter()
    with caplog.at_level(logging.INFO):
        context = retriever.retrieve_context("En yogun doktor kim?", schema)
    elapsed_ms = (time.perf_counter() - started) * 1000

    assert elapsed_ms < 500
    assert [table.name for table in context.tables] == ["doktorlar"]
    profile = next(
        rec for rec in caplog.records if rec.message == "Schema retrieval performance profile."
    )
    assert profile.query_analysis_ms >= 0
    assert profile.semantic_search_ms >= 0
    assert profile.graph_traversal_ms >= 0
    assert profile.ranking_ms >= 0
