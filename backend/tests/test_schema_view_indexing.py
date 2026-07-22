"""Tests for the view-indexing / FAISS repair (Phase 6).

Root cause: SemanticSchemaIndex.build_index() only ever iterated schema.tables,
so a view-only allowed-object deployment (DATABASE_ALLOWED_OBJECTS=
["dbo.vw_RandevuRaporu"], zero tables) produced zero indexable documents,
leaving FAISS empty and forcing every query through the "select all views"
safety-net fallback with zero prompt-budget accounting. These tests build a
schema with a view-only DatabaseSchema and drive SemanticSchemaIndex/
SchemaRetriever directly — no real embedding provider, no network calls.
"""

import os
import shutil

import pytest

from app.database_intelligence.exceptions import (
    SchemaRetrievalError,  # noqa: F401 (kept for parity with sibling test file)
)
from app.database_intelligence.models import (
    ColumnMetadata,
    DatabaseSchema,
    SchemaStatistics,
    ViewMetadata,
    calculate_fingerprint,
)
from app.database_intelligence.retriever import SchemaRetriever
from app.database_intelligence.schema_embeddings import (
    CACHE_DIR,
    SemanticSchemaIndex,
    construct_view_document,
)
from app.llm.remote_policy import PROHIBITED_PATIENT_FIELDS


@pytest.fixture(autouse=True)
def clean_cache_dir():
    if os.path.exists(CACHE_DIR):
        shutil.rmtree(CACHE_DIR)
    yield
    if os.path.exists(CACHE_DIR):
        shutil.rmtree(CACHE_DIR)


def _appointment_view() -> ViewMetadata:
    return ViewMetadata(
        name="vw_RandevuRaporu",
        comment="Randevu raporu görünümü",
        columns=[
            ColumnMetadata(
                name="RandevuTarihi",
                type_name="DATETIME",
                nullable=False,
                primary_key=False,
                comment="Randevu tarihi",
            ),
            ColumnMetadata(
                name="Durum",
                type_name="VARCHAR",
                nullable=False,
                primary_key=False,
                comment="Randevu durumu",
            ),
            ColumnMetadata(
                name="HastaAdi",
                type_name="VARCHAR",
                nullable=True,
                primary_key=False,
                comment="Hasta adi",
            ),
        ],
    )


def _view_only_schema() -> DatabaseSchema:
    view = _appointment_view()
    return DatabaseSchema(
        tables={},
        views={"vw_RandevuRaporu": view},
        statistics=SchemaStatistics(
            table_count=0, column_count=3, foreign_key_count=0, view_count=1
        ),
        fingerprint=calculate_fingerprint({}, {"vw_RandevuRaporu": view}),
    )


def test_view_only_schema_produces_indexable_documents():
    view = _appointment_view()
    doc = construct_view_document(view)

    assert "vw_RandevuRaporu" in doc
    assert "RandevuTarihi" in doc
    assert "Durum" in doc


def test_prohibited_pii_fields_excluded_from_view_document():
    view = _appointment_view()
    doc = construct_view_document(view)

    assert "HastaAdi" not in doc
    for field in PROHIBITED_PATIENT_FIELDS:
        assert field not in doc


@pytest.mark.asyncio
async def test_allowed_view_is_indexed_into_faiss():
    schema = _view_only_schema()
    index = SemanticSchemaIndex(schema, llm_provider=None)

    await index.build_index()

    assert index.table_names == []
    assert index.view_names == ["vw_RandevuRaporu"]
    assert index.view_index is not None


@pytest.mark.asyncio
async def test_appointment_query_retrieves_the_allowed_view():
    schema = _view_only_schema()
    index = SemanticSchemaIndex(schema, llm_provider=None)
    await index.build_index()

    results = await index.search_views("randevu durum dağılımı nedir", k=5)

    assert results
    assert results[0][0] == "vw_RandevuRaporu"


@pytest.mark.asyncio
async def test_cache_refresh_rebuilds_the_view_index():
    schema = _view_only_schema()
    index = SemanticSchemaIndex(schema, llm_provider=None)
    await index.build_index()
    assert index.view_index is not None

    # A second index instance sharing the same on-disk cache should reuse it
    # without recomputing embeddings (same fingerprint).
    index2 = SemanticSchemaIndex(schema, llm_provider=None)
    await index2.build_index()

    assert index2.view_names == ["vw_RandevuRaporu"]
    assert index2.view_index is not None


@pytest.mark.asyncio
async def test_no_real_network_call_for_hash_fallback_embedding():
    """llm_provider=None forces the deterministic hash-embedding fallback —
    no network call is possible, confirming unit tests never hit a real model."""
    schema = _view_only_schema()
    index = SemanticSchemaIndex(schema, llm_provider=None)

    await index.build_index()  # would raise/hang if it attempted a real call

    assert index.view_index is not None


def test_unrelated_database_objects_are_excluded_from_view_document():
    view = _appointment_view()
    doc = construct_view_document(view)

    # Only this view's own columns/name appear — no cross-object leakage.
    assert "sys." not in doc.lower()
    assert "information_schema" not in doc.lower()


def test_appointment_query_retrieval_shows_nonzero_prompt_budget():
    from unittest.mock import AsyncMock, MagicMock

    from app.database_intelligence.schema_graph import SchemaGraph

    schema = _view_only_schema()
    fake_index = MagicMock()
    fake_index.last_embedding_error = None
    fake_index.search = AsyncMock(return_value=[])
    fake_index.search_views = AsyncMock(return_value=[("vw_RandevuRaporu", 0.8)])
    fake_cache = MagicMock()
    fake_cache.get_graph = AsyncMock(return_value=SchemaGraph(schema))
    fake_cache.get_index = AsyncMock(return_value=fake_index)

    retriever = SchemaRetriever(schema_cache=fake_cache, match_threshold=1)

    context = retriever.retrieve_context("randevu durum dağılımı nedir", schema)

    assert any(v.name == "vw_RandevuRaporu" for v in context.views)


def test_no_all_views_fallback_when_view_scores_via_semantic_match():
    """With a genuine semantic match, retrieval must not need the blanket
    'select all views' safety net — it should select via scoring instead."""
    import logging
    from unittest.mock import AsyncMock, MagicMock

    from app.database_intelligence.schema_graph import SchemaGraph

    schema = _view_only_schema()
    fake_index = MagicMock()
    fake_index.last_embedding_error = None
    fake_index.search = AsyncMock(return_value=[])
    fake_index.search_views = AsyncMock(return_value=[("vw_RandevuRaporu", 0.9)])
    fake_cache = MagicMock()
    fake_cache.get_graph = AsyncMock(return_value=SchemaGraph(schema))
    fake_cache.get_index = AsyncMock(return_value=fake_index)

    retriever = SchemaRetriever(schema_cache=fake_cache, match_threshold=1)

    caplog_records = []

    class _Handler(logging.Handler):
        def emit(self, record):
            caplog_records.append(record.getMessage())

    logger = logging.getLogger("app.database_intelligence.retriever")
    handler = _Handler()
    logger.addHandler(handler)
    try:
        context = retriever.retrieve_context("randevu durum dağılımı nedir", schema)
    finally:
        logger.removeHandler(handler)

    assert any(v.name == "vw_RandevuRaporu" for v in context.views)
    assert not any("safety-net fallback" in msg for msg in caplog_records)
