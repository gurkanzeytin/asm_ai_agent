"""Regression contract for the 2026-08-03 live category validation."""

from app.planning.value_resolver import resolve_value
from app.semantics import catalog
from app.semantics.schema_knowledge import load_schema_knowledge


def _column(name: str):
    return next(item for item in catalog.load_column_catalog().columns if item.column == name)


def test_complete_live_category_sets_are_typed_and_exhaustive():
    expected = {
        "RandevuDurumu": {
            "Beklemede",
            "Gelmedi",
            "Gerçekleşti",
            "Giriş Yapılmış",
            "İşlem Sürmekte",
        },
        "CinsiyetId": {"E", "K", "D"},
        "RandevuTipiAdi": {"Poliklinik", "Radyoloji", "Kemoterapi", "Ameliyat"},
    }

    for column_name, values in expected.items():
        spec = _column(column_name)
        assert spec.values_verified
        assert spec.known_values_complete
        assert spec.verified_distinct_count == len(values)
        assert set(spec.known_values) == values
        assert spec.values_verified_at == "2026-08-03"

    assert "İptal" not in _column("RandevuDurumu").known_values


def test_nationality_profile_stays_live_grounded_not_prompt_embedded():
    nationality = _column("Uyruk")

    assert nationality.values_verified
    assert not nationality.known_values_complete
    assert nationality.verified_distinct_count == 149
    assert nationality.known_values == ["Türkiye"]
    assert "ValueCatalog" in nationality.value_notes


def test_dirty_iraq_values_require_clarification_instead_of_guessing():
    result = resolve_value("nationality", "iraklı", ["Irak", "Irak 2"])

    assert not result.grounded
    assert result.clarification_required
    assert result.match_type == "ambiguous"
    assert set(result.alternatives) == {"Irak", "Irak 2"}


def test_english_demonym_has_explicit_source_data_coverage_limit():
    result = resolve_value(
        "nationality", "ingiliz", ["Ingiltere", "Birleşik Krallık"]
    )

    assert result.grounded
    assert result.matched_value == "Ingiltere"
    assert "Birleşik Krallık" not in result.alternatives


def test_llm_schema_distinguishes_complete_and_partial_value_sets():
    knowledge = load_schema_knowledge()
    by_name = {column.name: column for column in knowledge.columns}

    assert by_name["RandevuTipiAdi"].value_grounding == "verified"
    assert by_name["RandevuTipiAdi"].known_values_complete
    assert by_name["Uyruk"].value_grounding == "partial"
    assert not by_name["Uyruk"].known_values_complete

    rendered = knowledge.render_for_llm()
    assert "verified_distinct_count=149" in rendered
    assert "Kaynak ülke adları tam normalize değildir" in rendered
