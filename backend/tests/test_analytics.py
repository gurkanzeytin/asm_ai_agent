"""Regression tests for AI-ANALYTICS-001 — Analytics Intelligence Layer Foundation.

All analytics are deterministic: no LLM, no network, no randomness.
"""

from datetime import datetime

import pytest

from app.agent.nodes.analyze_results import AnalyzeResultsNode
from app.agent.state import AgentState
from app.analytics import calculators
from app.analytics.analytics_engine import AnalyticsEngine
from app.analytics.intent_detector import AnalyticsIntentDetector
from app.analytics.models import AnalyticsIntent, DataShape, VisualizationType
from app.analytics.visualization_selector import VisualizationSelector
from app.application_models.workflow_models import QueryResult


def _query_result(columns, rows) -> QueryResult:
    return QueryResult(
        columns=columns,
        rows=rows,
        row_count=len(rows),
        execution_time_ms=1.0,
        success=True,
        executed_at=datetime(2026, 7, 13, 12, 0, 0),
        database_provider="mssql",
    )


TIME_SERIES_RESULT = _query_result(
    ["ay", "randevu_sayisi"],
    [
        {"ay": "2026-01", "randevu_sayisi": 201},
        {"ay": "2026-02", "randevu_sayisi": 240},
        {"ay": "2026-03", "randevu_sayisi": 260},
        {"ay": "2026-04", "randevu_sayisi": 234},
        {"ay": "2026-05", "randevu_sayisi": 412},
        {"ay": "2026-06", "randevu_sayisi": 240},
    ],
)

CATEGORICAL_RESULT = _query_result(
    ["bolum", "randevu_sayisi"],
    [
        {"bolum": "Kardiyoloji", "randevu_sayisi": 120},
        {"bolum": "Psikiyatri", "randevu_sayisi": 180},
        {"bolum": "Dermatoloji", "randevu_sayisi": 60},
    ],
)


# ── Part 1: Analytics intent detection ────────────────────────────────────────


@pytest.mark.parametrize(
    ("question", "expected_intents"),
    [
        ("Son 6 ayın randevularını analiz et", {AnalyticsIntent.TREND}),
        ("Geçen aya göre artış oranı nedir?", {AnalyticsIntent.GROWTH_RATE}),
        ("Hangi bölüm daha yoğun?", {AnalyticsIntent.COMPARISON}),
        ("En hızlı büyüyen bölüm", {AnalyticsIntent.RANKING, AnalyticsIntent.GROWTH_RATE}),
        ("Ortalama günlük randevu", {AnalyticsIntent.AVERAGE, AnalyticsIntent.TIME_SERIES}),
        ("Randevuların bölümlere göre dağılımı", {AnalyticsIntent.DISTRIBUTION}),
        ("Medyan bekleme süresi nedir", {AnalyticsIntent.MEDIAN}),
        ("En yüksek randevu sayısı", {AnalyticsIntent.MAXIMUM, AnalyticsIntent.RANKING}),
        ("Gelecek ay için tahmin", {AnalyticsIntent.FORECAST}),
        ("Yaş ile randevu sayısı arasındaki ilişki", {AnalyticsIntent.CORRELATION}),
    ],
)
def test_analytics_intent_detection(question, expected_intents):
    detected = set(AnalyticsIntentDetector().detect(question))

    assert expected_intents.issubset(detected)


def test_primary_intent_precedence():
    detector = AnalyticsIntentDetector()

    intents = detector.detect("Son 6 ayın randevularını analiz et")
    assert detector.primary_intent(intents) == AnalyticsIntent.TREND

    assert detector.primary_intent([]) == AnalyticsIntent.GENERAL


def test_intent_detection_is_diacritic_insensitive():
    detector = AnalyticsIntentDetector()

    assert AnalyticsIntent.DISTRIBUTION in detector.detect("bolumlere gore dagilim")
    assert AnalyticsIntent.TREND in detector.detect("randevulari ANALIZ et")


# ── Part 3: Calculators ───────────────────────────────────────────────────────


def test_basic_calculators():
    values = [201, 240, 260, 234, 412, 240]

    assert calculators.total(values) == 1587
    assert calculators.average(values) == 264.5
    assert calculators.median(values) == 240
    assert calculators.minimum(values) == 201
    assert calculators.maximum(values) == 412
    assert calculators.count(values) == 6


def test_change_calculators():
    values = [100.0, 150.0]

    assert calculators.difference(values) == 50.0
    assert calculators.percentage_difference(values) == 50.0
    assert calculators.growth_rate(values) == 50.0


def test_change_calculators_guard_edge_cases():
    assert calculators.difference([5.0]) is None
    assert calculators.percentage_difference([0.0, 10.0]) is None
    assert calculators.growth_rate([]) is None
    assert calculators.average([]) is None
    assert calculators.median([]) is None
    assert calculators.total([]) == 0.0


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ([10, 20, 30, 40], "upward"),
        ([40, 30, 20, 10], "downward"),
        ([100, 101, 100, 99], "stable"),
        ([5], None),
    ],
)
def test_trend_direction(values, expected):
    assert calculators.trend_direction(values) == expected


def test_ranking_calculators_are_deterministic_on_ties():
    items = [("B", 10.0), ("A", 10.0), ("C", 5.0)]

    assert calculators.rank(items) == [("A", 10.0), ("B", 10.0), ("C", 5.0)]
    assert calculators.top_n(items, 2) == [("A", 10.0), ("B", 10.0)]
    assert calculators.bottom_n(items, 1) == [("C", 5.0)]


def test_largest_change():
    labels = ["Jan", "Feb", "Mar", "Apr", "May"]
    values = [200, 210, 205, 208, 400]

    assert calculators.largest_change(labels, values) == "May"


# ── Part 2/3: Analytics engine ────────────────────────────────────────────────


def test_engine_trend_analysis_on_time_series():
    engine = AnalyticsEngine()

    result = engine.analyze("Son 6 ayın randevularını analiz et", TIME_SERIES_RESULT)

    assert result.analytics_type == "trend"
    assert result.data_shape == DataShape.TIME_SERIES
    assert result.metrics["total"] == 1587
    assert result.metrics["highest_value"] == 412
    assert result.metrics["lowest_value"] == 201
    assert result.metrics["growth_rate"] == pytest.approx(19.4, abs=0.1)
    assert result.metrics["trend_direction"] == "upward"
    assert result.metrics["highest_period"] == "2026-05"
    assert result.metrics["largest_change"] == "2026-05"
    assert result.visualization.type == VisualizationType.LINE_CHART


def test_engine_comparison_on_categorical():
    engine = AnalyticsEngine()

    result = engine.analyze("Hangi bölüm daha yoğun?", CATEGORICAL_RESULT)

    assert result.analytics_type == "comparison"
    assert result.data_shape == DataShape.CATEGORICAL
    assert result.metrics["top_category"] == "Psikiyatri"
    assert result.metrics["bottom_category"] == "Dermatoloji"
    assert result.metrics["ranking"][0] == {"label": "Psikiyatri", "value": 180.0}
    assert result.metrics["distribution"]["Psikiyatri"] == 50.0
    assert result.visualization.type == VisualizationType.BAR_CHART


def test_engine_growth_rate_intent():
    engine = AnalyticsEngine()

    result = engine.analyze("Geçen aya göre artış oranı nedir?", TIME_SERIES_RESULT)

    assert result.analytics_type == "growth_rate"
    assert AnalyticsIntent.GROWTH_RATE in result.intents
    assert result.metrics["growth_rate"] is not None


def test_engine_average_intent():
    engine = AnalyticsEngine()

    result = engine.analyze("Ortalama günlük randevu", TIME_SERIES_RESULT)

    assert result.analytics_type == "average"
    assert result.metrics["average"] == 264.5


def test_engine_ranking_intent():
    engine = AnalyticsEngine()

    result = engine.analyze("En fazla randevusu olan ilk 3 bölüm", CATEGORICAL_RESULT)

    assert AnalyticsIntent.RANKING in result.intents
    assert [entry["label"] for entry in result.metrics["top_n"]] == [
        "Psikiyatri",
        "Kardiyoloji",
        "Dermatoloji",
    ]


def test_engine_empty_result():
    engine = AnalyticsEngine()
    empty = _query_result(["ad_soyad"], [])

    result = engine.analyze("Doktorları listele", empty)

    assert result.data_shape == DataShape.EMPTY
    assert result.analytics_type == "none"
    assert result.metrics == {"count": 0}
    assert result.visualization.type == VisualizationType.TABLE


def test_engine_single_value_result():
    engine = AnalyticsEngine()
    single = _query_result(["randevu_sayisi"], [{"randevu_sayisi": 42}])

    result = engine.analyze("Bugün kaç randevu oluşturuldu?", single)

    assert result.data_shape == DataShape.SINGLE_VALUE
    assert result.metrics["total"] == 42
    assert result.insights["value"] == 42
    assert result.visualization.type == VisualizationType.CARD


def test_engine_single_row_result():
    engine = AnalyticsEngine()
    row = _query_result(
        ["ad_soyad", "randevu_sayisi"],
        [{"ad_soyad": "Tekbay Aksu", "randevu_sayisi": 155}],
    )

    result = engine.analyze("En fazla randevusu olan doktor kim?", row)

    assert result.data_shape == DataShape.SINGLE_ROW
    assert result.visualization.type == VisualizationType.CARD


def test_engine_large_dataset_recommends_table():
    engine = AnalyticsEngine()
    rows = [{"ad_soyad": f"Doktor {i:03d}", "randevu_sayisi": i} for i in range(100)]
    large = _query_result(["ad_soyad", "randevu_sayisi"], rows)

    result = engine.analyze("Doktorları listele", large)

    assert result.visualization.type == VisualizationType.TABLE
    assert "Large result list" in result.visualization.reason
    assert result.metrics["count"] == 100


def test_engine_ignores_id_columns_for_metrics():
    engine = AnalyticsEngine()
    data = _query_result(
        ["id", "bolum", "randevu_sayisi"],
        [
            {"id": 1, "bolum": "Kardiyoloji", "randevu_sayisi": 10},
            {"id": 2, "bolum": "Psikiyatri", "randevu_sayisi": 30},
        ],
    )

    result = engine.analyze("Bölümleri karşılaştır", data)

    assert result.metric_column == "randevu_sayisi"
    assert result.label_column == "bolum"
    assert result.metrics["total"] == 40


def test_engine_is_deterministic():
    engine = AnalyticsEngine()

    first = engine.analyze("Son 6 ayın randevularını analiz et", TIME_SERIES_RESULT)
    second = engine.analyze("Son 6 ayın randevularını analiz et", TIME_SERIES_RESULT)

    assert first.metrics == second.metrics
    assert first.insights == second.insights
    assert first.visualization == second.visualization


def test_engine_prepares_insight_fields():
    engine = AnalyticsEngine()

    result = engine.analyze("Son 6 ayın randevularını analiz et", TIME_SERIES_RESULT)

    assert result.insights["trend"] == "upward"
    assert result.insights["growth_rate"] == result.metrics["growth_rate"]
    assert result.insights["largest_change"] == "2026-05"
    assert result.insights["total"] == 1587


# ── Part 4: Visualization selector ────────────────────────────────────────────


@pytest.mark.parametrize(
    ("shape", "intents", "row_count", "categories", "expected"),
    [
        (DataShape.EMPTY, [], 0, 0, VisualizationType.TABLE),
        (DataShape.SINGLE_VALUE, [], 1, 0, VisualizationType.CARD),
        (DataShape.SINGLE_ROW, [], 1, 0, VisualizationType.CARD),
        (DataShape.TIME_SERIES, [], 6, 6, VisualizationType.LINE_CHART),
        (DataShape.CATEGORICAL, [], 3, 3, VisualizationType.BAR_CHART),
        (
            DataShape.CATEGORICAL,
            [AnalyticsIntent.DISTRIBUTION],
            3,
            3,
            VisualizationType.PIE_CHART,
        ),
        (
            DataShape.CATEGORICAL,
            [AnalyticsIntent.DISTRIBUTION],
            10,
            10,
            VisualizationType.BAR_CHART,  # too many slices for a pie
        ),
        (DataShape.CATEGORICAL, [], 100, 100, VisualizationType.TABLE),
        (DataShape.TABULAR, [], 12, 0, VisualizationType.TABLE),
    ],
)
def test_visualization_selection(shape, intents, row_count, categories, expected):
    recommendation = VisualizationSelector().select(
        data_shape=shape,
        intents=intents,
        row_count=row_count,
        category_count=categories,
    )

    assert recommendation.type == expected
    assert recommendation.reason


# ── Pipeline integration ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_analyze_results_node_populates_state():
    node = AnalyzeResultsNode()
    state = AgentState(
        question="Son 6 ayın randevularını analiz et",
        query_result=TIME_SERIES_RESULT,
    )

    result = await node.execute(state)

    assert result.analytics is not None
    assert result.analytics.analytics_type == "trend"
    assert "analyze_results" in result.completed_nodes
    assert "analyze_results" in result.node_timings
    assert result.errors == []


@pytest.mark.asyncio
async def test_analyze_results_node_skips_on_missing_result():
    node = AnalyzeResultsNode()
    state = AgentState(question="Doktorları listele")

    result = await node.execute(state)

    assert result.analytics is None
    assert "analyze_results" not in result.completed_nodes
    assert result.errors == []  # skip is non-fatal


@pytest.mark.asyncio
async def test_analyze_results_node_skips_on_upstream_errors():
    node = AnalyzeResultsNode()
    state = AgentState(
        question="Doktorları listele",
        query_result=CATEGORICAL_RESULT,
        errors=["upstream failure"],
    )

    result = await node.execute(state)

    assert result.analytics is None
    assert result.errors == ["upstream failure"]


@pytest.mark.asyncio
async def test_analyze_results_node_failure_is_non_fatal():
    class ExplodingEngine:
        def analyze(self, question, query_result):
            raise RuntimeError("boom")

    node = AnalyzeResultsNode(analytics_engine=ExplodingEngine())
    state = AgentState(question="Analiz et", query_result=CATEGORICAL_RESULT)

    result = await node.execute(state)

    assert result.analytics is None
    assert result.errors == []
    assert "analyze_results" in result.node_timings


# ═══════════════════════ Multi-metric analytics (Phase 7/8) ══════════════════


from app.planning.models import QueryPlan  # noqa: E402

_MULTI_METRIC_COLUMNS = [
    "sube_adi",
    "appointment_count",
    "completed_appointment_rate",
    "appointment_duration_average",
]
MULTI_METRIC_RESULT = _query_result(
    _MULTI_METRIC_COLUMNS,
    [
        {
            "sube_adi": "Merkez",
            "appointment_count": 120,
            "completed_appointment_rate": 80.0,
            "appointment_duration_average": 25.0,
        },
        {
            "sube_adi": "Kadikoy",
            "appointment_count": 90,
            "completed_appointment_rate": 70.0,
            "appointment_duration_average": 30.0,
        },
    ],
)


def _multi_metric_plan() -> QueryPlan:
    return QueryPlan(
        question="Subelere gore randevu sayisi, gerceklesme orani ve ortalama sure",
        dimensions=["SubeAdi"],
        metrics=["appointment_count", "completed_appointment_rate", "appointment_duration_average"],
    )


def test_metric_summaries_preserved_independently():
    engine = AnalyticsEngine()
    plan = _multi_metric_plan()
    aliases = {
        "appointment_count": "appointment_count",
        "completed_appointment_rate": "completed_appointment_rate",
        "appointment_duration_average": "appointment_duration_average",
    }
    result = engine.analyze(
        "Subelere gore randevu sayisi, gerceklesme orani ve ortalama sure",
        MULTI_METRIC_RESULT,
        plan=plan,
        metric_aliases=aliases,
    )
    assert set(result.metric_summaries) == {
        "appointment_count",
        "completed_appointment_rate",
        "appointment_duration_average",
    }
    count_summary = result.metric_summaries["appointment_count"]
    assert count_summary.total == 210
    assert count_summary.top_dimension == "Merkez"
    rate_summary = result.metric_summaries["completed_appointment_rate"]
    assert rate_summary.top_dimension == "Merkez"
    duration_summary = result.metric_summaries["appointment_duration_average"]
    assert duration_summary.top_dimension == "Kadikoy"


def test_metric_summaries_do_not_affect_legacy_metric_column_selection():
    # Regression guard: metric_column/_profile_columns behavior must stay
    # exactly as before, regardless of metric_summaries being computed.
    engine = AnalyticsEngine()
    plan = _multi_metric_plan()
    result = engine.analyze(
        "Subelere gore randevu sayisi, gerceklesme orani ve ortalama sure",
        MULTI_METRIC_RESULT,
        plan=plan,
        metric_aliases={},
    )
    assert result.metric_column in MULTI_METRIC_RESULT.columns


def test_visualization_selects_grouped_bar_for_multi_metric_categorical():
    selector = VisualizationSelector()
    recommendation = selector.select(
        data_shape=DataShape.CATEGORICAL,
        intents=[AnalyticsIntent.COMPARISON],
        row_count=2,
        category_count=2,
        metric_count=3,
    )
    assert recommendation.type == VisualizationType.GROUPED_BAR_CHART


def test_visualization_stays_single_series_bar_for_one_metric():
    selector = VisualizationSelector()
    recommendation = selector.select(
        data_shape=DataShape.CATEGORICAL,
        intents=[AnalyticsIntent.COMPARISON],
        row_count=2,
        category_count=2,
        metric_count=1,
    )
    assert recommendation.type == VisualizationType.BAR_CHART


# ═══════════ Plan-aware shape classification for single-row grouped results ═══


ONE_ROW_MULTI_METRIC_RESULT = _query_result(
    _MULTI_METRIC_COLUMNS,
    [
        {
            "sube_adi": "Merkez",
            "appointment_count": 89,
            "completed_appointment_rate": 76.5,
            "appointment_duration_average": 22.0,
        },
    ],
)


def test_single_grouped_row_classified_as_categorical_not_single_row():
    engine = AnalyticsEngine()
    plan = QueryPlan(
        question="q",
        dimensions=["sube_adi"],
        metrics=["appointment_count", "completed_appointment_rate", "appointment_duration_average"],
    )
    aliases = {
        "appointment_count": "appointment_count",
        "completed_appointment_rate": "completed_appointment_rate",
        "appointment_duration_average": "appointment_duration_average",
    }
    result = engine.analyze(
        "Şubelere göre randevu sayısı ve gerçekleşme oranı",
        ONE_ROW_MULTI_METRIC_RESULT,
        plan=plan,
        metric_aliases=aliases,
    )
    assert result.data_shape == DataShape.CATEGORICAL
    assert set(result.metric_summaries) == set(plan.metrics)
    # No flattening to a single scalar total: all three metrics independently summarized.
    assert result.metric_summaries["appointment_count"].total == 89
    assert result.metric_summaries["completed_appointment_rate"].average == 76.5
    assert result.metric_summaries["appointment_duration_average"].average == 22.0


def test_single_row_without_planned_dimension_stays_single_row():
    # No dimension in the plan: a genuine single-value/summary result must
    # keep its existing (correct) classification — this fix is scoped to
    # plans that actually requested a grouping dimension.
    engine = AnalyticsEngine()
    plan = QueryPlan(question="q", dimensions=[], metrics=["appointment_count"])
    result = _query_result(["appointment_count"], [{"appointment_count": 42}])
    analytics = engine.analyze("Kaç randevu var?", result, plan=plan, metric_aliases={})
    assert analytics.data_shape == DataShape.SINGLE_VALUE


def test_single_row_grouped_result_without_plan_stays_single_row():
    # No plan at all (ad-hoc SQL path) — behavior must be unchanged.
    engine = AnalyticsEngine()
    result = _query_result(
        ["sube_adi", "appointment_count"], [{"sube_adi": "Merkez", "appointment_count": 89}]
    )
    analytics = engine.analyze("Şubelere göre randevu sayısı", result)
    assert analytics.data_shape == DataShape.SINGLE_ROW


# ── Comparison sufficiency (single-category vs. multi-category) ────────────


def test_single_category_result_is_comparison_insufficient():
    engine = AnalyticsEngine()
    plan = QueryPlan(
        question="q",
        dimensions=["sube_adi"],
        metrics=["appointment_count", "completed_appointment_rate", "appointment_duration_average"],
    )
    aliases = {
        "appointment_count": "appointment_count",
        "completed_appointment_rate": "completed_appointment_rate",
        "appointment_duration_average": "appointment_duration_average",
    }
    result = engine.analyze(
        "Şubelere göre randevu sayısı, gerçekleşme oranı ve ortalama süreyi karşılaştır",
        ONE_ROW_MULTI_METRIC_RESULT,
        plan=plan,
        metric_aliases=aliases,
    )
    assert result.data_shape == DataShape.CATEGORICAL
    assert result.comparison_category_count == 1
    assert result.comparison_sufficient is False
    assert result.comparison_limitation_reason
    assert "TEST ASM" not in result.comparison_limitation_reason  # never names the category
    # Metric facts are preserved even though the comparison itself is insufficient.
    assert set(result.metric_summaries) == set(plan.metrics)


def test_two_category_result_is_comparison_sufficient():
    engine = AnalyticsEngine()
    result = engine.analyze("Hangi bölüm daha yoğun?", CATEGORICAL_RESULT)
    assert result.data_shape == DataShape.CATEGORICAL
    assert result.comparison_category_count == 3
    assert result.comparison_sufficient is True
    assert result.comparison_limitation_reason is None


def test_comparison_sufficiency_is_none_for_non_categorical_shapes():
    engine = AnalyticsEngine()
    result = engine.analyze("Son 6 ayın randevularını analiz et", TIME_SERIES_RESULT)
    assert result.data_shape == DataShape.TIME_SERIES
    assert result.comparison_category_count is None
    assert result.comparison_sufficient is None
