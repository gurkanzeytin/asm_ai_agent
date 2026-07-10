"""BUG-003A/B regression tests: SQL generation must preserve normalized categorical
values exactly and may only reference identifiers from the retrieved schema context."""
from unittest.mock import AsyncMock

import pytest

from app.database_intelligence.models import ColumnMetadata, DatabaseContext, TableMetadata
from app.llm.interfaces import ILLMProvider
from app.llm.schemas import LLMResponse
from app.parsers import OutputParser
from app.services import SQLService, SQLServiceException
from app.sql_validator.validator import SQLValidator


def _column(name: str) -> ColumnMetadata:
    return ColumnMetadata(name=name, type_name="TEXT", nullable=True, primary_key=(name == "id"))


def _context() -> DatabaseContext:
    doktorlar = TableMetadata(
        name="doktorlar",
        columns=[_column("id"), _column("ad_soyad"), _column("bolum_id"), _column("unvan")],
        primary_keys=["id"],
        foreign_keys=[],
    )
    bolumler = TableMetadata(
        name="bolumler",
        columns=[_column("id"), _column("bolum_adi")],
        primary_keys=["id"],
        foreign_keys=[],
    )
    return DatabaseContext(tables=[doktorlar, bolumler], views=[])


def _provider(*responses: str) -> AsyncMock:
    provider = AsyncMock(spec=ILLMProvider)
    provider.generate.side_effect = [
        LLMResponse(content=content, model="mock-model", latency_ms=1.0)
        for content in responses
    ]
    provider.get_metadata.return_value = {"provider": "mock-provider"}
    return provider


@pytest.mark.asyncio
async def test_bug_003a_literal_preserves_normalized_vocabulary():
    """'Çocuk doktorlarını göster' -> literal must stay 'Cocuk Sagligi', not 'Çocuk Sağlığı'."""
    llm_provider = _provider(
        "SELECT d.ad_soyad, b.bolum_adi FROM doktorlar d "
        "JOIN bolumler b ON d.bolum_id = b.id "
        "WHERE b.bolum_adi = 'Çocuk Sağlığı';"
    )
    service = SQLService(llm_provider, OutputParser(), SQLValidator())

    generated = await service.generate_sql(
        "prompt",
        question="cocuk sagligi doktorlarını göster",
        database_context=_context(),
    )

    assert "'Cocuk Sagligi'" in generated.sql
    assert "Çocuk Sağlığı" not in generated.sql
    # Stored values may differ in case from the normalized vocabulary
    assert "COLLATE NOCASE" in generated.sql.upper()
    assert generated.validation_result.valid is True
    # No repair needed: canonicalization is deterministic post-processing
    assert llm_provider.generate.await_count == 1


@pytest.mark.asyncio
async def test_bug_003a_lowercase_vocabulary_literal_matches_title_case_storage():
    """LLM copying the lowercase normalized value verbatim must still hit 'Cocuk Sagligi'."""
    llm_provider = _provider(
        "SELECT ad_soyad FROM doktorlar WHERE bolum_id = "
        "(SELECT id FROM bolumler WHERE bolum_adi = 'cocuk sagligi');"
    )
    service = SQLService(llm_provider, OutputParser(), SQLValidator())

    generated = await service.generate_sql(
        "prompt",
        question="cocuk sagligi doktorlarını göster",
        database_context=_context(),
    )

    assert "'cocuk sagligi' COLLATE NOCASE" in generated.sql


@pytest.mark.asyncio
async def test_bug_003a_unrelated_literals_left_untouched():
    """Literals not present in the question vocabulary must not be rewritten."""
    llm_provider = _provider(
        "SELECT ad_soyad FROM doktorlar WHERE unvan = 'Uzm. Dr.';"
    )
    service = SQLService(llm_provider, OutputParser(), SQLValidator())

    generated = await service.generate_sql(
        "prompt",
        question="cocuk sagligi doktorlarını göster",
        database_context=_context(),
    )

    assert "'Uzm. Dr.'" in generated.sql


@pytest.mark.asyncio
async def test_bug_003b_unknown_column_triggers_regeneration():
    """'Hekimleri listele' -> bolumler.adi rejected, repaired bolumler.bolum_adi accepted."""
    llm_provider = _provider(
        "SELECT doktorlar.id, doktorlar.ad_soyad, bolumler.adi AS bolum_adi "
        "FROM doktorlar JOIN bolumler ON doktorlar.bolum_id = bolumler.id;",
        "SELECT doktorlar.id, doktorlar.ad_soyad, bolumler.bolum_adi "
        "FROM doktorlar JOIN bolumler ON doktorlar.bolum_id = bolumler.id;",
    )
    service = SQLService(llm_provider, OutputParser(), SQLValidator())

    generated = await service.generate_sql(
        "prompt",
        question="doktorları listele",
        database_context=_context(),
    )

    assert llm_provider.generate.await_count == 2
    repair_prompt = llm_provider.generate.await_args_list[1].args[0]
    assert "bolumler.adi" in repair_prompt
    assert "bolumler.bolum_adi" in generated.sql
    assert "bolumler.adi AS" not in generated.sql


@pytest.mark.asyncio
async def test_bug_003b_persistent_unknown_identifier_is_rejected():
    """SQL still referencing unknown identifiers after repair must never be returned."""
    bad_sql = (
        "SELECT doktorlar.ad_soyad, bolumler.adi FROM doktorlar "
        "JOIN bolumler ON doktorlar.bolum_id = bolumler.id;"
    )
    llm_provider = _provider(bad_sql, bad_sql)
    service = SQLService(llm_provider, OutputParser(), SQLValidator())

    with pytest.raises(SQLServiceException, match="unknown schema identifiers"):
        await service.generate_sql(
            "prompt",
            question="doktorları listele",
            database_context=_context(),
        )
    assert llm_provider.generate.await_count == 2


@pytest.mark.asyncio
async def test_bug_003b_unknown_table_is_rejected():
    bad_sql = "SELECT * FROM hemsireler;"
    llm_provider = _provider(bad_sql, bad_sql)
    service = SQLService(llm_provider, OutputParser(), SQLValidator())

    with pytest.raises(SQLServiceException, match="unknown schema identifiers"):
        await service.generate_sql(
            "prompt",
            question="hemşireleri listele",
            database_context=_context(),
        )


@pytest.mark.asyncio
async def test_schema_guard_skipped_without_database_context():
    """Backward compatibility: no context means no schema identifier enforcement."""
    llm_provider = _provider("SELECT bolumler.adi FROM bolumler;")
    service = SQLService(llm_provider, OutputParser(), SQLValidator())

    generated = await service.generate_sql("prompt")

    assert "bolumler.adi" in generated.sql
    assert llm_provider.generate.await_count == 1


def test_validator_schema_identifiers_accepts_aliases_and_aggregates():
    validator = SQLValidator()
    sql = (
        "SELECT d.ad_soyad, COUNT(*) AS doktor_sayisi FROM doktorlar d "
        "JOIN bolumler b ON d.bolum_id = b.id "
        "GROUP BY d.ad_soyad ORDER BY doktor_sayisi DESC;"
    )

    assert validator.validate_schema_identifiers(sql, _context()) == []


def test_validator_schema_identifiers_flags_unknown_identifiers():
    validator = SQLValidator()
    sql = (
        "SELECT d.ad_soyad, b.adi FROM doktorlar d "
        "JOIN hemsireler h ON h.doktor_id = d.id "
        "JOIN bolumler b ON d.bolum_id = b.id;"
    )

    issues = validator.validate_schema_identifiers(sql, _context())

    assert "unknown table 'hemsireler'" in issues
    assert "unknown column 'b.adi'" in issues
