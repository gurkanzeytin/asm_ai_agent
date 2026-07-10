from unittest.mock import AsyncMock

import pytest

from app.database_intelligence.models import (
    ColumnMetadata,
    DatabaseSchema,
    ForeignKeyMetadata,
    SchemaStatistics,
    TableMetadata,
)
from app.database_intelligence.retriever import SchemaRetriever
from app.database_intelligence.schema_graph import SchemaGraph
from app.llm.interfaces import ILLMProvider
from app.llm.schemas import LLMResponse
from app.parsers.output_parser import OutputParser
from app.services.sql_service import SQLService
from app.sql_validator.validator import SQLValidator


def _column(name: str, primary_key: bool = False) -> ColumnMetadata:
    return ColumnMetadata(
        name=name,
        type_name="INTEGER" if primary_key or name.endswith("_id") or name == "id" else "TEXT",
        nullable=not primary_key,
        primary_key=primary_key,
    )


def _table(
    name: str,
    columns: list[ColumnMetadata],
    foreign_keys: list[ForeignKeyMetadata] | None = None,
) -> TableMetadata:
    return TableMetadata(
        name=name,
        columns=columns,
        primary_keys=["id"] if any(column.name == "id" and column.primary_key for column in columns) else [],
        foreign_keys=foreign_keys or [],
    )


def _schema() -> DatabaseSchema:
    tables = {
        "doktorlar": _table(
            "doktorlar",
            [_column("id", primary_key=True), _column("ad_soyad"), _column("bolum_id")],
            [ForeignKeyMetadata(constrained_columns=["bolum_id"], referred_table="bolumler", referred_columns=["id"])],
        ),
        "hastalar": _table(
            "hastalar",
            [_column("id", primary_key=True), _column("ad_soyad")],
        ),
        "bolumler": _table(
            "bolumler",
            [_column("id", primary_key=True), _column("bolum_adi")],
        ),
        "randevular": _table(
            "randevular",
            [_column("id", primary_key=True), _column("doktor_id"), _column("hasta_id"), _column("bolum_id")],
            [
                ForeignKeyMetadata(constrained_columns=["doktor_id"], referred_table="doktorlar", referred_columns=["id"]),
                ForeignKeyMetadata(constrained_columns=["hasta_id"], referred_table="hastalar", referred_columns=["id"]),
                ForeignKeyMetadata(constrained_columns=["bolum_id"], referred_table="bolumler", referred_columns=["id"]),
            ],
        ),
        "receteler": _table(
            "receteler",
            [_column("id", primary_key=True), _column("doktor_id"), _column("hasta_id")],
            [
                ForeignKeyMetadata(constrained_columns=["doktor_id"], referred_table="doktorlar", referred_columns=["id"]),
                ForeignKeyMetadata(constrained_columns=["hasta_id"], referred_table="hastalar", referred_columns=["id"]),
            ],
        ),
    }
    return DatabaseSchema(
        tables=tables,
        views={},
        statistics=SchemaStatistics(
            table_count=len(tables),
            column_count=sum(len(table.columns) for table in tables.values()),
            foreign_key_count=sum(len(table.foreign_keys) for table in tables.values()),
            view_count=0,
        ),
        fingerprint="aggregation-schema",
    )


class FakeIndex:
    last_embedding_error = None

    async def search(self, query, k=5):
        return []


class FakeCache:
    def __init__(self, schema: DatabaseSchema):
        self.schema = schema

    async def get_graph(self):
        return SchemaGraph(self.schema)

    async def get_index(self):
        return FakeIndex()


@pytest.mark.parametrize(
    ("question", "expected_tables"),
    [
        ("En cok randevusu olan doktor kim?", {"doktorlar", "randevular"}),
        ("En az randevusu olan doktor kim?", {"doktorlar", "randevular"}),
        ("En cok recete yazan doktor kim?", {"doktorlar", "receteler"}),
        ("En cok hastasi olan doktor kim?", {"doktorlar", "hastalar", "randevular"}),
        ("En yogun bolum hangisi?", {"bolumler", "randevular"}),
    ],
)
def test_aggregation_retrieval_includes_descriptive_entity_tables(question, expected_tables):
    schema = _schema()
    retriever = SchemaRetriever(schema_cache=FakeCache(schema), max_tables=5)

    context = retriever.retrieve_context(question, schema)

    selected = {table.name for table in context.tables}
    assert expected_tables.issubset(selected)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("raw_sql", "forbidden_columns", "required_fragments"),
    [
        (
            "SELECT r.doktor_id, d.ad_soyad, COUNT(*) AS randevu_sayisi "
            "FROM randevular r JOIN doktorlar d ON r.doktor_id = d.id "
            "GROUP BY r.doktor_id, d.ad_soyad ORDER BY randevu_sayisi DESC LIMIT 1;",
            {"doktor_id"},
            {"ad_soyad", "randevu_sayisi"},
        ),
        (
            "SELECT r.doktor_id, d.ad_soyad, COUNT(*) AS randevu_sayisi "
            "FROM randevular r JOIN doktorlar d ON r.doktor_id = d.id "
            "GROUP BY r.doktor_id, d.ad_soyad ORDER BY randevu_sayisi ASC LIMIT 1;",
            {"doktor_id"},
            {"ad_soyad", "randevu_sayisi"},
        ),
        (
            "SELECT receteler.doktor_id, doktorlar.ad_soyad, COUNT(*) AS recete_sayisi "
            "FROM receteler JOIN doktorlar ON receteler.doktor_id = doktorlar.id "
            "GROUP BY receteler.doktor_id, doktorlar.ad_soyad ORDER BY recete_sayisi DESC LIMIT 1;",
            {"doktor_id"},
            {"ad_soyad", "recete_sayisi"},
        ),
        (
            "SELECT r.doktor_id, d.ad_soyad, COUNT(DISTINCT r.hasta_id) AS hasta_sayisi "
            "FROM randevular r JOIN doktorlar d ON r.doktor_id = d.id "
            "GROUP BY r.doktor_id, d.ad_soyad ORDER BY hasta_sayisi DESC LIMIT 1;",
            {"doktor_id"},
            {"ad_soyad", "hasta_sayisi"},
        ),
        (
            "SELECT r.bolum_id, b.bolum_adi, COUNT(*) AS randevu_sayisi "
            "FROM randevular r JOIN bolumler b ON r.bolum_id = b.id "
            "GROUP BY r.bolum_id, b.bolum_adi ORDER BY randevu_sayisi DESC LIMIT 1;",
            {"bolum_id"},
            {"bolum_adi", "randevu_sayisi"},
        ),
    ],
)
async def test_aggregation_sql_projection_removes_ids_when_descriptive_columns_exist(
    raw_sql,
    forbidden_columns,
    required_fragments,
):
    llm_provider = AsyncMock(spec=ILLMProvider)
    llm_provider.generate.return_value = LLMResponse(
        content=raw_sql,
        model="mock-model",
        latency_ms=1.0,
    )
    llm_provider.get_metadata.return_value = {"provider": "mock-provider"}
    service = SQLService(llm_provider, OutputParser(), SQLValidator())

    generated = await service.generate_sql("prompt")
    normalized = generated.sql.lower()
    select_clause = normalized.split(" from ", 1)[0]

    for column in forbidden_columns:
        assert column not in select_clause
    for fragment in required_fragments:
        assert fragment in select_clause
    assert generated.validation_result.valid is True
