"""AI-INTELLIGENCE-012: centralized Turkish presentation labels.

Verifies that internal canonical identifiers (metric ids, dimension ids,
analysis types, time grains, visualization types) are never surfaced
directly to the user, and that every currently supported id resolves to a
correct Turkish label via app.reporting.presentation.
"""

from app.agent.nodes.generate_report import GenerateReportNode
from app.agent.state import AgentState
from app.analytics.models import AnalyticsResult, DataShape, MetricSummary
from app.application_models.generated_report import GeneratedReport
from app.insights.prompt_builder import InsightPromptBuilder
from app.reporting.presentation import (
    ANALYSIS_TYPE_LABELS_TR,
    DIMENSION_LABELS_TR,
    METRIC_LABELS_TR,
    TIME_GRAIN_LABELS_TR,
    VISUALIZATION_LABELS_TR,
    get_analysis_type_label,
    get_dimension_label,
    get_metric_label,
    get_time_grain_label,
    get_visualization_label,
)
from app.semantics.catalog import load_metric_catalog

# Internal identifiers that must never leak into rendered, user-facing text.
_FORBIDDEN_RAW_IDENTIFIERS = [
    "monthly_appointment_count",
    "weekly_appointment_count",
    "daily_appointment_count",
    "appointment_count",
    "completed_appointment_rate",
    "appointment_duration_average",
    "metric_summaries",
    "comparison_sufficient",
    "time_grain",
]


# ── 1. Every catalog metric has a Turkish label ────────────────────────────


def test_every_catalog_metric_has_a_turkish_label():
    catalog = load_metric_catalog()
    for metric in catalog.metrics:
        label = get_metric_label(metric.id)
        assert label, f"metric '{metric.id}' resolved to an empty label"
        assert "_" not in label, f"metric '{metric.id}' leaked snake_case: {label!r}"


def test_hand_mapped_metric_ids_never_fall_back_to_the_catalog_derivation():
    # These ids must be explicit in METRIC_LABELS_TR (task-specified wording),
    # not derived generically from the catalog's sentence-case `name` field.
    for metric_id in (
        "monthly_appointment_count",
        "weekly_appointment_count",
        "daily_appointment_count",
        "completed_appointment_rate",
        "no_show_rate",
        "appointment_duration_average",
        "average_appointment_duration",
        "unique_patient_count",
        "appointments_per_branch",
        "appointments_per_doctor",
        "appointments_per_department",
        "appointment_count",
    ):
        assert metric_id in METRIC_LABELS_TR


def test_monthly_appointment_count_renders_as_aylik_randevu_sayisi():
    assert get_metric_label("monthly_appointment_count") == "Aylık Randevu Sayısı"


def test_aliases_share_the_same_label():
    assert get_metric_label("appointment_duration_average") == get_metric_label(
        "average_appointment_duration"
    )


# ── 2. Dimension labels ─────────────────────────────────────────────────────


def test_dimension_labels_cover_documented_ids():
    for dimension_id in (
        "branch",
        "doctor",
        "department",
        "status",
        "service",
        "category",
        "source",
        "date",
        "SubeAdi",
        "DoktorId",
        "GenelRandevuBolumAdi",
        "RandevuDurumu",
    ):
        label = get_dimension_label(dimension_id)
        assert label and "_" not in label
    assert DIMENSION_LABELS_TR["branch"] == "Şube"
    assert DIMENSION_LABELS_TR["doctor"] == "Doktor"
    assert DIMENSION_LABELS_TR["department"] == "Bölüm"
    assert DIMENSION_LABELS_TR["status"] == "Randevu Durumu"


# ── 3. Analysis type / time grain / visualization labels ───────────────────


def test_analysis_type_labels():
    assert ANALYSIS_TYPE_LABELS_TR["distribution"] == "Dağılım Analizi"
    assert ANALYSIS_TYPE_LABELS_TR["trend"] == "Eğilim Analizi"
    assert ANALYSIS_TYPE_LABELS_TR["comparison"] == "Karşılaştırma Analizi"
    assert ANALYSIS_TYPE_LABELS_TR["ranking"] == "Sıralama Analizi"
    assert ANALYSIS_TYPE_LABELS_TR["general"] and "_" not in get_analysis_type_label("general")


def test_time_grain_labels():
    assert TIME_GRAIN_LABELS_TR["month"] == "Ay"
    assert TIME_GRAIN_LABELS_TR["week"] == "Hafta"
    assert TIME_GRAIN_LABELS_TR["day"] == "Gün"
    assert TIME_GRAIN_LABELS_TR["quarter"] == "Çeyrek"
    assert TIME_GRAIN_LABELS_TR["year"] == "Yıl"
    assert get_time_grain_label("month") == "Ay"


def test_visualization_labels():
    for viz_id in VISUALIZATION_LABELS_TR:
        assert get_visualization_label(viz_id)
    assert get_visualization_label("BAR_CHART") == "Çubuk Grafik"


# ── 4. Fallback behavior: unknown ids never crash, never leak snake_case ──


def test_unknown_metric_id_falls_back_safely():
    assert get_metric_label("monthly_custom_metric") == "Monthly Custom Metric"
    assert get_metric_label(None) == ""
    assert get_metric_label("") == ""


def test_unknown_dimension_and_analysis_type_fall_back_safely():
    assert get_dimension_label("some_unmapped_dimension") == "Some Unmapped Dimension"
    assert get_analysis_type_label("some_unmapped_type") == "Some Unmapped Type"


# ── 5. Canonical IDs remain unchanged internally ────────────────────────────


def test_metric_summary_keeps_canonical_id_alongside_label():
    summary = MetricSummary(
        metric_id="monthly_appointment_count",
        metric_label=get_metric_label("monthly_appointment_count"),
        total=88.0,
        average=12.57,
    )
    assert summary.metric_id == "monthly_appointment_count"
    assert summary.metric_label == "Aylık Randevu Sayısı"


# ── 6. Report rendering: multi-metric "Sorgulanan metrikler" section ──────


def test_reasoning_sections_render_turkish_labels_not_raw_ids():
    node = GenerateReportNode(workflow_service=None)
    analytics = AnalyticsResult(
        analytics_type="summary",
        data_shape=DataShape.SINGLE_ROW,
        metric_summaries={
            "monthly_appointment_count": MetricSummary(
                metric_id="monthly_appointment_count",
                metric_label=get_metric_label("monthly_appointment_count"),
                total=88.0,
                average=12.57,
            ),
            "completed_appointment_rate": MetricSummary(
                metric_id="completed_appointment_rate",
                metric_label=get_metric_label("completed_appointment_rate"),
                average=73.4,
            ),
        },
    )
    state = AgentState(question="aylık randevu sayısı ve gerçekleşme oranı", analytics=analytics)
    report = GeneratedReport(
        title="Sorgu Sonucu",
        markdown="# Sorgu Sonucu",
        provider="template",
        model="table",
    )

    updated = node._append_reasoning_sections(report, state)

    assert "Aylık Randevu Sayısı" in updated.markdown
    assert "Gerçekleşme Oranı" in updated.markdown
    for forbidden in ("monthly_appointment_count", "completed_appointment_rate"):
        assert forbidden not in updated.markdown


def test_forbidden_raw_identifiers_never_appear_in_rendered_report():
    node = GenerateReportNode(workflow_service=None)
    analytics = AnalyticsResult(
        analytics_type="summary",
        data_shape=DataShape.SINGLE_ROW,
        metric_summaries={
            metric_id: MetricSummary(
                metric_id=metric_id,
                metric_label=get_metric_label(metric_id),
                total=1.0,
            )
            for metric_id in ("monthly_appointment_count", "appointment_count")
        },
    )
    state = AgentState(question="test", analytics=analytics)
    report = GeneratedReport(
        title="Sorgu Sonucu", markdown="# Sorgu Sonucu", provider="template", model="table"
    )

    updated = node._append_reasoning_sections(report, state)

    for forbidden in _FORBIDDEN_RAW_IDENTIFIERS:
        assert forbidden not in updated.markdown, f"'{forbidden}' leaked into report markdown"


# ── 7. LLM prompt payload carries metric_label alongside metric_id ────────


def test_insight_prompt_payload_contains_metric_label():
    analytics = AnalyticsResult(
        analytics_type="summary",
        data_shape=DataShape.SINGLE_ROW,
        metric_summaries={
            "monthly_appointment_count": MetricSummary(
                metric_id="monthly_appointment_count",
                metric_label=get_metric_label("monthly_appointment_count"),
                total=88.0,
            ),
        },
    )
    builder = InsightPromptBuilder()
    payload = builder.analytics_payload(analytics)

    summary = payload["metric_summaries"]["monthly_appointment_count"]
    assert summary["metric_id"] == "monthly_appointment_count"
    assert summary["metric_label"] == "Aylık Randevu Sayısı"


def test_insight_prompt_instructs_model_to_use_metric_label():
    from app.prompts.loader import prompt_loader

    template = prompt_loader.get_prompt("insight_generation")
    assert "metric_label" in template
    assert "metric_id" in template


# ── 8. Turkish characters preserved ────────────────────────────────────────


def test_turkish_characters_preserved_in_labels():
    label = get_metric_label("monthly_appointment_count")
    assert "ı" in label or "ş" in label or "ğ" in label or "Ç" in label or "Ş" in label
    assert label == "Aylık Randevu Sayısı"
