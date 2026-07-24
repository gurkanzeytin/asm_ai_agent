"""Merkezî Türkçe sunum katmanı (AI-INTELLIGENCE-011).

Teknik metric ID'leri ve ham sayılar kullanıcıya asla doğrudan gösterilmez.
Tüm Türkçe etiketler ve sayı biçimleri bu modülden gelir: backend rapor
şablonları, result reasoning, LLM prompt payload'ı ve API sunumu tek
sözlüğü paylaşır.

Internal canonical id'ler (metric_id, dimension_id, analysis_type,
time_grain, visualization type, ...) hiçbir zaman değiştirilmez — QueryPlan,
metric catalog, SQL alias'ları, context memory ve testler bu id'lere
dayanır. Bu modül SADECE sunum (presentation) katmanıdır: id -> Türkçe
etiket çevirisi. Bilinmeyen bir id asla hata fırlatmaz; okunur bir
biçime çevrilir ve teşhis için loglanır.
"""

import logging
from numbers import Number

logger = logging.getLogger(__name__)

# Teknik alias -> kullanıcıya görünen Türkçe etiket. Frontend'deki
# locales/tr.ts metrik sözlüğü ile eş tutulmalıdır.
METRIC_LABELS_TR: dict[str, str] = {
    "appointment_count": "Toplam Randevu",
    "cohort_total_count": "Son Dakika Randevusu",
    "completed_count": "Gerçekleşen Randevu",
    "completed_rate": "Gerçekleşme Oranı",
    "checked_in_count": "Giriş Yapılmış Randevu",
    "checked_in_rate": "Giriş Yapılma Oranı",
    "no_show_count": "Gelmeyen Randevu",
    "no_show_rate": "Gelmeme Oranı",
    "in_progress_count": "İşlemi Süren Randevu",
    "in_progress_rate": "İşlemde Olanların Oranı",
    "waiting_count": "Bekleyen Randevu",
    "waiting_rate": "Bekleme Oranı",
    "current_period_count": "Mevcut Dönem Randevu Sayısı",
    "baseline_period_count": "Önceki Dönem Randevu Sayısı",
    "absolute_change": "Sayısal Değişim",
    "percentage_change": "Yüzdesel Değişim",
    "rate_point_change": "Oran Farkı",
    "unique_patient_count": "Tekil Hasta Sayısı",
    "unique_doctor_count": "Tekil Doktor Sayısı",
    "comparison_total_count": "Karşılaştırma Toplamı",
    "group_count": "Grup Sayısı",
    "total_appointments": "Toplam Randevu",
    "average_appointments": "Ortalama Randevu",
    "minimum_appointments": "En Düşük Randevu",
    "maximum_appointments": "En Yüksek Randevu",
    "max_to_average_ratio": "En Yüksek / Ortalama Oranı",
    "top_10_percent_share": "İlk %10 Grubun Payı",
    "current_rate": "Mevcut Dönem Oranı",
    "baseline_rate": "Önceki Dönem Oranı",

    # ── app/resources/metric_catalog.json id'leri (AI-INTELLIGENCE-012) ────
    # QueryPlan.metrics / AnalyticsResult.metric_summaries doğrudan bu id'leri
    # taşır; kullanıcıya asla ham snake_case gösterilmez.
    "appointments_per_patient": "Hasta Başına Randevu",
    "repeat_patient_count": "Tekrar Randevu Alan Hasta Sayısı",
    "appointment_duration_average": "Ortalama Randevu Süresi",
    "average_appointment_duration": "Ortalama Randevu Süresi",
    "appointment_duration_minimum": "En Kısa Randevu Süresi",
    "appointment_duration_maximum": "En Uzun Randevu Süresi",
    "appointments_per_doctor": "Doktor Bazlı Randevu Sayısı",
    "appointments_per_department": "Bölüm Bazlı Randevu Sayısı",
    "appointments_per_branch": "Şube Bazlı Randevu Sayısı",
    "appointments_per_source": "Kaynak Bazlı Randevu Sayısı",
    "appointments_per_type": "Tip Bazlı Randevu Sayısı",
    "daily_appointment_count": "Günlük Randevu Sayısı",
    "weekly_appointment_count": "Haftalık Randevu Sayısı",
    "monthly_appointment_count": "Aylık Randevu Sayısı",
    "daily_average_appointment_count": "Günlük Ortalama Randevu Sayısı",
    "appointment_lead_time_average": "Ortalama Randevu Alma Süresi (Lead Time)",
    "same_day_booking_count": "Aynı Gün Alınan Randevu Sayısı",
    "same_day_booking_rate": "Aynı Gün Randevu Oranı",
    "protocol_opening_delay_average": "Ortalama Protokol Açılış Gecikmesi",
    "actual_duration_from_dates": "Fiili Randevu Süresi",
    "duration_difference": "Planlanan-Fiili Süre Farkı",
    "completed_appointment_count": "Gerçekleşen Randevu Sayısı",
    "completed_appointment_rate": "Gerçekleşme Oranı",
    "protocol_created_count": "Protokol Açılan Randevu Sayısı",
    "protocol_conversion_rate": "Protokole Dönüşüm Oranı",
    "protocol_state_based_completion": "Protokol Durumuna Göre Tamamlanma",
    "missing_doctor_count": "Doktor Bilgisi Eksik Kayıt Sayısı",
    "missing_department_count": "Bölüm Bilgisi Eksik Kayıt Sayısı",
    "invalid_date_range_count": "Geçersiz Tarih Aralıklı Kayıt Sayısı",
    "zero_or_negative_duration_count": "Sıfır/Negatif Süreli Kayıt Sayısı",
    "duration_mismatch_count": "Süre Tutarsızlığı Olan Kayıt Sayısı",
    "patient_id_mismatch_count": "Hasta Kimliği Uyuşmayan Kayıt Sayısı",
    "protocol_status_mismatch_count": "Protokol Durum Tutarsızlığı",
}

# Doğrulanmış RandevuDurumu değerleri -> okunur Türkçe durum adı.
STATUS_LABELS_TR: dict[str, str] = {
    "completed": "Gerçekleşti",
    "checked_in": "Giriş Yapılmış",
    "no_show": "Gelmedi",
    "in_progress": "İşlem Sürmekte",
    "waiting": "Beklemede",
}

# Gruplama sütunu (dimension) id -> Türkçe etiket. Hem ham SQL/şema sütun
# adlarını (SubeAdi, DoktorId, ...) hem de context/planning katmanının
# kullandığı jenerik İngilizce kısa id'leri (branch, doctor, ...) kapsar —
# hangi katman hangi biçimde taşırsa taşısın aynı sözlükten çözülür.
DIMENSION_LABELS_TR: dict[str, str] = {
    "SubeAdi": "Şube",
    "GenelRandevuBolumAdi": "Bölüm",
    "BolumId": "Bölüm",
    "RandevuTipiAdi": "Randevu Tipi",
    "RandevuDurumu": "Randevu Durumu",
    "GenelRandevuKaynakAdi": "Randevu Kaynağı",
    "DoktorId": "Doktor",
    "DoktorAdi": "Doktor",
    "Uyruk": "Uyruk",
    "CinsiyetId": "Cinsiyet",
    "KategoriAdi": "Kategori",
    "HizmetAdi": "Hizmet",
    "RandevuyuVeren": "Randevuyu Veren",
    "BaslangicTarihi": "Başlangıç Tarihi",
    "BitisTarihi": "Bitiş Tarihi",
    "RandevuSuresi": "Randevu Süresi",
    "HastaAdi": "Hasta Adı",
    "HastaSoyadi": "Hasta Soyadı",
    "DogumTarihi": "Doğum Tarihi",
    "CreatedDate": "Oluşturulma Tarihi",
    "age_group": "Yaş Grubu",
    # Jenerik canonical dimension id'leri (context/analytical_signals, API).
    "branch": "Şube",
    "doctor": "Doktor",
    "department": "Bölüm",
    "status": "Randevu Durumu",
    "service": "Hizmet",
    "category": "Kategori",
    "source": "Randevu Kaynağı",
    "type": "Randevu Tipi",
    "date": "Tarih",
}

# Analiz tipi (AnalyticsIntent / analytics_type) -> Türkçe etiket.
ANALYSIS_TYPE_LABELS_TR: dict[str, str] = {
    "trend": "Eğilim Analizi",
    "comparison": "Karşılaştırma Analizi",
    "growth_rate": "Büyüme Oranı Analizi",
    "percentage_change": "Yüzdesel Değişim Analizi",
    "ranking": "Sıralama Analizi",
    "distribution": "Dağılım Analizi",
    "average": "Ortalama Analizi",
    "median": "Medyan Analizi",
    "minimum": "Minimum Analizi",
    "maximum": "Maksimum Analizi",
    "time_series": "Zaman Serisi Analizi",
    "correlation": "Korelasyon Analizi",
    "forecast": "Tahmin Analizi",
    "general": "Genel Analiz",
    "summary": "Özet Analiz",
    "list": "Liste Görünümü",
    "none": "Sonuç Yok",
}

# Zaman kırılımı (time_grain / grouping_granularity) -> Türkçe etiket.
TIME_GRAIN_LABELS_TR: dict[str, str] = {
    "hour": "Saat",
    "day": "Gün",
    "week": "Hafta",
    "month": "Ay",
    "quarter": "Çeyrek",
    "year": "Yıl",
}

# Görselleştirme tipi (VisualizationType) -> Türkçe etiket.
VISUALIZATION_LABELS_TR: dict[str, str] = {
    "CARD": "Kart",
    "TABLE": "Tablo",
    "BAR_CHART": "Çubuk Grafik",
    "LINE_CHART": "Çizgi Grafik",
    "PIE_CHART": "Pasta Grafik",
    "GROUPED_BAR_CHART": "Gruplanmış Çubuk Grafik",
    "MULTI_SERIES_BAR_CHART": "Çoklu Seri Çubuk Grafik",
}

# Sonuç şekli (DataShape) -> Türkçe etiket.
RESULT_SHAPE_LABELS_TR: dict[str, str] = {
    "empty": "Boş Sonuç",
    "single_value": "Tekil Değer",
    "single_row": "Tekil Kayıt",
    "time_series": "Zaman Serisi",
    "categorical": "Kategorik Dağılım",
    "tabular": "Tablo",
}

# Sıralama yönü -> Türkçe etiket.
RANKING_DIRECTION_LABELS_TR: dict[str, str] = {
    "ASC": "Artan",
    "DESC": "Azalan",
    "top": "En Yüksek",
    "bottom": "En Düşük",
}


def _fallback_label(identifier: str, kind: str) -> str:
    """Never raises, never leaks raw snake_case: converts to a readable
    title-cased form and logs the miss so the mapping can be extended."""
    if not identifier:
        return ""
    logger.warning("presentation: unmapped %s id '%s' — using fallback label.", kind, identifier)
    return identifier.replace("_", " ").replace("-", " ").strip().title()


def label_for(metric_id: str) -> str:
    """Metric/alias için Türkçe etiket; bilinmeyen id okunur hale getirilir."""
    if metric_id in METRIC_LABELS_TR:
        return METRIC_LABELS_TR[metric_id]
    return metric_id.replace("_", " ").strip().title()


def get_metric_label(metric_id: str | None) -> str:
    """Safe resolver: canonical metric id -> Türkçe etiket.

    Falls back to the shared metric catalog (app/resources/metric_catalog.json)
    business name before giving up to the generic snake_case-to-title fallback,
    so every catalog metric gets a correct label even if it is not yet
    hand-mapped above.
    """
    if not metric_id:
        return ""
    if metric_id in METRIC_LABELS_TR:
        return METRIC_LABELS_TR[metric_id]
    catalog_name = _catalog_metric_name(metric_id)
    if catalog_name:
        return catalog_name
    return _fallback_label(metric_id, "metric")


def _catalog_metric_name(metric_id: str) -> str | None:
    try:
        from app.semantics.catalog import load_metric_catalog

        spec = load_metric_catalog().by_id().get(metric_id)
    except Exception:  # pragma: no cover — catalog must never break presentation
        return None
    if spec is None or not spec.name:
        return None
    return spec.name[:1].upper() + spec.name[1:]


def get_dimension_label(dimension_id: str | None) -> str:
    """Safe resolver: canonical dimension/column id -> Türkçe etiket."""
    if not dimension_id:
        return ""
    if dimension_id in DIMENSION_LABELS_TR:
        return DIMENSION_LABELS_TR[dimension_id]
    return _fallback_label(dimension_id, "dimension")


def get_analysis_type_label(value: str | None) -> str:
    """Safe resolver: analysis type / AnalyticsIntent value -> Türkçe etiket."""
    if not value:
        return ""
    if value in ANALYSIS_TYPE_LABELS_TR:
        return ANALYSIS_TYPE_LABELS_TR[value]
    return _fallback_label(value, "analysis_type")


def get_time_grain_label(value: str | None) -> str:
    """Safe resolver: time grain / grouping_granularity -> Türkçe etiket."""
    if not value:
        return ""
    if value in TIME_GRAIN_LABELS_TR:
        return TIME_GRAIN_LABELS_TR[value]
    return _fallback_label(value, "time_grain")


def get_visualization_label(value: str | None) -> str:
    """Safe resolver: VisualizationType value -> Türkçe etiket."""
    if not value:
        return ""
    if value in VISUALIZATION_LABELS_TR:
        return VISUALIZATION_LABELS_TR[value]
    return _fallback_label(value, "visualization_type")


def get_result_shape_label(value: str | None) -> str:
    """Safe resolver: DataShape value -> Türkçe etiket."""
    if not value:
        return ""
    if value in RESULT_SHAPE_LABELS_TR:
        return RESULT_SHAPE_LABELS_TR[value]
    return _fallback_label(value, "result_shape")


def get_ranking_direction_label(value: str | None) -> str:
    """Safe resolver: ranking direction (ASC/DESC/top/bottom) -> Türkçe etiket."""
    if not value:
        return ""
    if value in RANKING_DIRECTION_LABELS_TR:
        return RANKING_DIRECTION_LABELS_TR[value]
    return _fallback_label(value, "ranking_direction")


def get_status_label(status_id: str | None) -> str:
    """Safe resolver: RandevuDurumu status key -> Türkçe etiket."""
    if not status_id:
        return ""
    if status_id in STATUS_LABELS_TR:
        return STATUS_LABELS_TR[status_id]
    return _fallback_label(status_id, "status")


def format_number(value: Number | None) -> str:
    """Tam sayıları Türkçe binlik ayraçla biçimler: 678866 -> '678.866'."""
    if value is None or isinstance(value, bool) or not isinstance(value, Number):
        return "—"
    number = float(value)
    if number == int(number):
        return f"{int(number):,}".replace(",", ".")
    # Ondalıklı büyük sayı: binlik nokta + ondalık virgül
    whole, frac = f"{number:,.1f}".split(".")
    return whole.replace(",", ".") + "," + frac


def format_percent(value: Number | None, decimals: int = 1) -> str:
    """Yüzdeleri Türkçe biçimler: 73.409332 -> '%73,4'."""
    if value is None or isinstance(value, bool) or not isinstance(value, Number):
        return "—"
    formatted = f"{float(value):.{decimals}f}".replace(".", ",")
    return f"%{formatted}"


def format_value(metric_id: str, value: Number | None) -> str:
    """Alias adına göre doğru Türkçe biçimi seçer (oran mı sayı mı)."""
    lowered = metric_id.lower()
    if (
        lowered.endswith(("_rate", "_percentage", "_share", "_ratio"))
        or lowered in ("percentage_change", "rate_point_change")
        or "oran" in lowered
        or "yuzde" in lowered
    ):
        return format_percent(value)
    return format_number(value)


# ── SQL result table column presentation (AI-INTELLIGENCE-013) ─────────────
#
# The "SQL Sonucu" table renders raw QueryResult column keys (SubeAdi,
# appointment_duration_average, ...) directly today. `column_metadata` is
# additive presentation metadata attached alongside the unchanged `columns`/
# `rows` contract: raw keys stay the source of truth for data access,
# sorting, filtering, exports, and API stability. Only the label is
# translated for display.

_DURATION_COLUMNS = {"RandevuSuresi"}
_DATE_COLUMNS = {
    "BaslangicTarihi",
    "BitisTarihi",
    "DogumTarihi",
    "CreatedDate",
    "ProtokolAcilisTarihi",
}
_ID_LIKE_SUFFIX = ("id", "Id", "ID")


def get_column_label(
    column: str,
    resolved_metrics: "list[str] | None" = None,
    resolved_dimensions: "list[str] | None" = None,
) -> str:
    """Resolves a raw QueryResult column key to a Türkçe display label.

    Resolution priority (per AI-INTELLIGENCE-012/013 contract):
      1. planned metric/dimension metadata for this turn (`resolved_metrics`/
         `resolved_dimensions` — exact id match to the column key)
      2. the centralized metric label catalog (`METRIC_LABELS_TR` + metric
         catalog fallback)
      3. the known view-column label mapping (`DIMENSION_LABELS_TR`)
      4. a readable fallback (never raw snake_case/PascalCase passthrough)
    """
    if not column:
        return ""
    if resolved_metrics and column in resolved_metrics:
        return get_metric_label(column)
    if resolved_dimensions and column in resolved_dimensions:
        return get_dimension_label(column)
    if column in METRIC_LABELS_TR:
        return METRIC_LABELS_TR[column]
    if column in DIMENSION_LABELS_TR:
        return DIMENSION_LABELS_TR[column]
    catalog_name = _catalog_metric_name(column)
    if catalog_name:
        return catalog_name
    return _fallback_label(column, "column")


def _infer_column_format(column: str) -> tuple[str, str | None]:
    """Infers a presentation `(format, unit)` pair for a raw column key.

    Never mutates the underlying value — this only tells the frontend how to
    *render* the value that already lives at `row[column]`.
    """
    if column in _DURATION_COLUMNS:
        return "duration", "dakika"
    if column in _DATE_COLUMNS:
        return "datetime" if column == "CreatedDate" else "date", None

    try:
        from app.semantics.catalog import load_metric_catalog

        spec = load_metric_catalog().by_id().get(column)
    except Exception:  # pragma: no cover — catalog must never break formatting
        spec = None
    if spec is not None:
        if spec.result_type == "percentage":
            return "percentage", "%"
        if spec.result_type == "integer":
            return "integer", None
        if spec.result_type == "float":
            lowered = column.lower()
            if "duration" in lowered or "sure" in lowered:
                return "duration", "dakika"
            return "decimal", None

    lowered = column.lower()
    if (
        lowered.endswith(("_rate", "_percentage", "_share", "_ratio"))
        or lowered in ("percentage_change", "rate_point_change")
    ):
        return "percentage", "%"
    if lowered.endswith(_ID_LIKE_SUFFIX) and column not in DIMENSION_LABELS_TR:
        return "text", None
    if lowered.endswith(("_count", "_sayisi")) or lowered in ("count", "row_count"):
        return "integer", None
    return "text", None


def build_column_metadata(
    columns: list[str],
    resolved_metrics: "list[str] | None" = None,
    resolved_dimensions: "list[str] | None" = None,
    hidden_columns: "list[str] | None" = None,
) -> list[dict[str, str | bool | None]]:
    """Builds `[{key, label, format, unit, hidden}, ...]` for a QueryResult's
    raw `columns`, preserving order. Raw keys (and therefore `row[key]`
    access, sorting, filtering, and exports) are completely untouched — this
    is purely additive presentation metadata for the SQL result table header.

    `hidden` (DOCTOR-DISPLAY-NAME-ENRICHMENT-001) flags columns retained in
    the result for internal/diagnostic use (e.g. DoktorId once DoktorAdi has
    been resolved) that the normal user-facing table should not show by
    default — the frontend may still let a user reveal them.
    """
    hidden = set(hidden_columns or [])
    metadata: list[dict[str, str | bool | None]] = []
    for column in columns:
        label = get_column_label(column, resolved_metrics, resolved_dimensions)
        fmt, unit = _infer_column_format(column)
        metadata.append(
            {"key": column, "label": label, "format": fmt, "unit": unit, "hidden": column in hidden}
        )
    return metadata
