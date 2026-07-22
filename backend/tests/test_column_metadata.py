"""AI-INTELLIGENCE-013: SQL result table column presentation contract.

`column_metadata` is additive presentation metadata attached to
QueryResultSchema — raw `columns`/`rows` keys must never change, only the
Türkçe label/format/unit hints for the frontend table header.
"""

from datetime import UTC, datetime

from app.api.v1.endpoints.reports import _map_to_response
from app.application_models.workflow_models import QueryResult as WorkflowQueryResult
from app.application_models.workflow_result import WorkflowResult
from app.reporting.presentation import build_column_metadata, get_column_label


def _query_result(columns: list[str]) -> WorkflowQueryResult:
    return WorkflowQueryResult(
        columns=columns,
        rows=[dict.fromkeys(columns, 1)],
        row_count=1,
        execution_time_ms=1.0,
        success=True,
        executed_at=datetime.now(UTC),
        database_provider="mssql",
    )


# ── 1. Raw keys are never renamed ───────────────────────────────────────────


def test_column_metadata_keys_match_raw_columns_exactly():
    columns = ["SubeAdi", "appointment_duration_average", "completed_appointment_rate"]
    metadata = build_column_metadata(columns)
    assert [m["key"] for m in metadata] == columns


def test_query_result_rows_keep_raw_keys_when_column_metadata_is_attached():
    qr = _query_result(["SubeAdi", "appointment_count"])
    result = WorkflowResult(
        question="test",
        query_result=qr,
        generated_sql="SELECT 1",
    )
    response = _map_to_response(result)
    assert response.query_result is not None
    assert response.query_result.columns == ["SubeAdi", "appointment_count"]
    assert set(response.query_result.rows[0].keys()) == {"SubeAdi", "appointment_count"}
    assert [m.key for m in response.query_result.column_metadata] == [
        "SubeAdi",
        "appointment_count",
    ]


# ── 2. Turkish labels for metric aliases ────────────────────────────────────


def test_metric_alias_columns_get_turkish_labels():
    metadata = build_column_metadata(
        ["monthly_appointment_count", "completed_appointment_rate", "appointment_count"]
    )
    labels = {m["key"]: m["label"] for m in metadata}
    assert labels["monthly_appointment_count"] == "Aylık Randevu Sayısı"
    assert labels["completed_appointment_rate"] == "Gerçekleşme Oranı"
    assert labels["appointment_count"] == "Toplam Randevu"


# ── 3. Turkish labels for dimension/view columns ───────────────────────────


def test_view_column_dimensions_get_turkish_labels():
    metadata = build_column_metadata(
        [
            "SubeAdi",
            "RandevuDurumu",
            "GenelRandevuBolumAdi",
            "DoktorId",
            "HizmetAdi",
            "KategoriAdi",
            "GenelRandevuKaynakAdi",
            "BaslangicTarihi",
            "BitisTarihi",
            "RandevuSuresi",
            "HastaAdi",
            "HastaSoyadi",
            "DogumTarihi",
            "CinsiyetId",
            "Uyruk",
            "CreatedDate",
        ]
    )
    labels = {m["key"]: m["label"] for m in metadata}
    assert labels["SubeAdi"] == "Şube"
    assert labels["RandevuDurumu"] == "Randevu Durumu"
    assert labels["GenelRandevuBolumAdi"] == "Bölüm"
    assert labels["DoktorId"] == "Doktor"
    assert labels["HizmetAdi"] == "Hizmet"
    assert labels["KategoriAdi"] == "Kategori"
    assert labels["GenelRandevuKaynakAdi"] == "Randevu Kaynağı"
    assert labels["BaslangicTarihi"] == "Başlangıç Tarihi"
    assert labels["BitisTarihi"] == "Bitiş Tarihi"
    assert labels["RandevuSuresi"] == "Randevu Süresi"
    assert labels["HastaAdi"] == "Hasta Adı"
    assert labels["HastaSoyadi"] == "Hasta Soyadı"
    assert labels["DogumTarihi"] == "Doğum Tarihi"
    assert labels["CinsiyetId"] == "Cinsiyet"
    assert labels["Uyruk"] == "Uyruk"
    assert labels["CreatedDate"] == "Oluşturulma Tarihi"


# ── 4. Resolution priority: planned metadata beats generic catalog ────────


def test_resolved_metrics_take_priority_over_generic_catalog():
    # "appointment_count" is a known metric id; explicitly marking it resolved
    # for this turn must not change its label (both paths agree), but proves
    # the resolved_metrics branch is exercised without raising.
    label = get_column_label(
        "appointment_count", resolved_metrics=["appointment_count"], resolved_dimensions=None
    )
    assert label == "Toplam Randevu"


def test_resolved_dimensions_resolve_ambiguous_raw_columns():
    label = get_column_label("branch", resolved_metrics=None, resolved_dimensions=["branch"])
    assert label == "Şube"


# ── 5. Unknown columns get a readable fallback, never raw snake_case ──────


def test_unknown_column_gets_readable_fallback():
    metadata = build_column_metadata(["some_future_column_xyz"])
    assert metadata[0]["label"] == "Some Future Column Xyz"
    assert "_" not in metadata[0]["label"]


def test_unknown_pascal_case_column_gets_readable_fallback():
    label = get_column_label("SomeUnmappedColumn")
    assert label  # never empty, never raises
    assert "_" not in label


# ── 6. Format/unit inference ────────────────────────────────────────────────


def test_format_inference_percentage_integer_duration():
    metadata = {
        m["key"]: m
        for m in build_column_metadata(
            ["completed_appointment_rate", "appointment_count", "RandevuSuresi"]
        )
    }
    assert metadata["completed_appointment_rate"]["format"] == "percentage"
    assert metadata["completed_appointment_rate"]["unit"] == "%"
    assert metadata["appointment_count"]["format"] == "integer"
    assert metadata["RandevuSuresi"]["format"] == "duration"
    assert metadata["RandevuSuresi"]["unit"] == "dakika"


# ── 7. Turkish characters preserved ────────────────────────────────────────


def test_turkish_characters_preserved_in_column_labels():
    label = get_column_label("SubeAdi")
    assert label == "Şube"
    assert "ş" in label.lower() or "Ş" in label
