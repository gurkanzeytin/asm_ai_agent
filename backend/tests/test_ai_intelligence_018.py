"""AI-INTELLIGENCE-018: resolved-context answerability, trend routing, and
trend consistency corrections.

Covers item 11's checklist:
  - additive follow-up context (retain + add metric/dimension, context_applied,
    answerability-after-merge, no out-of-scope)
  - other follow-up phrasings
  - out-of-scope stays out-of-scope for genuinely unrelated questions, and the
    capability-aware response never advertises unsupported domains
  - insight routing (single-metric trend -> local, multi-metric -> remote,
    simple distribution -> deterministic)
  - trend semantics (monotonicity/consistency/endpoint/slope separation,
    partial-period exclusion, forbidden-phrase repair)
  - metadata (resolved_time_grain, routing_reason, context_applied)

No real LLM/network calls anywhere in this file.
"""

from datetime import date

import pytest

from app.agent.graph import route_by_intent
from app.agent.state import AgentState
from app.analytics.models import AnalyticsIntent, AnalyticsResult, DataShape
from app.analytics.trend_analysis import compute_trend_metrics
from app.application_models.intent import IntentResult, IntentType
from app.context.context_manager import ContextManager
from app.context.models import ResolutionResult
from app.database_intelligence.models import ViewMetadata
from app.insights.models import InsightConfidence, InsightNarrative
from app.insights.narrative_guard import (
    contains_forbidden_continuous_growth_phrase,
    repair_narrative,
)
from app.insights.output_validation import validate_and_repair
from app.insights.routing import InsightGenerationMode, InsightRouter
from app.insights.rules_engine import InsightRulesEngine
from app.planning.models import QueryPlan
from app.planning.planner import QueryPlanner
from app.services.answerability import AnswerabilityGuard, AnswerabilityInput
from app.services.query_analyzer import QueryAnalyzer

_TODAY = date(2026, 7, 22)
_VIEW = ViewMetadata(name="dbo.vw_RandevuRaporu", columns=[])


def _build_plan(question: str) -> QueryPlan:
    analysis = QueryAnalyzer(today=_TODAY).analyze(question)
    return QueryPlanner().build_plan(question, analysis, tables=[], views=[_VIEW])


def _intent(value: IntentType = IntentType.DATABASE_QUERY, confidence: float = 0.95):
    return IntentResult(intent=value, confidence=confidence, reason="test", matched_keywords=[])


# ── Additive context (item 1/3/11) ──────────────────────────────────────────


class TestAdditiveContext:
    def _turn1(self, manager: ContextManager, session_id: str):
        r1 = ResolutionResult(
            original_question="Şubelere göre randevu sayılarını karşılaştır.",
            resolved_question="Şubelere göre randevu sayılarını karşılaştır.",
        )
        plan1 = QueryPlan(
            question="Şubelere göre randevu sayılarını karşılaştır.",
            dimensions=["SubeAdi"],
            metrics=["appointment_count"],
            analysis_type="count",
        )
        manager.update(r1, session_id=session_id, query_plan=plan1)

    def test_retain_prior_metric_and_add_second_metric(self):
        manager = ContextManager()
        session_id = "test-018-additive-1"
        self._turn1(manager, session_id)
        r2 = manager.resolve("Bir de gerçekleşme oranını ekle.", session_id)
        assert "appointment_count" in r2.resolved_signals.metrics
        assert "completed_appointment_rate" in r2.resolved_signals.metrics

    def test_retain_branch_dimension(self):
        manager = ContextManager()
        session_id = "test-018-additive-2"
        self._turn1(manager, session_id)
        r2 = manager.resolve("Bir de gerçekleşme oranını ekle.", session_id)
        assert "branch" in r2.resolved_signals.dimensions

    def test_context_applied_true(self):
        manager = ContextManager()
        session_id = "test-018-additive-3"
        self._turn1(manager, session_id)
        r2 = manager.resolve("Bir de gerçekleşme oranını ekle.", session_id)
        assert r2.context_applied is True

    def test_answerability_after_context_merge(self):
        manager = ContextManager()
        session_id = "test-018-additive-4"
        self._turn1(manager, session_id)
        r2 = manager.resolve("Bir de gerçekleşme oranını ekle.", session_id)

        answerability_input = AnswerabilityInput(
            raw_question="Bir de gerçekleşme oranını ekle.",
            resolved_question=r2.resolved_question,
            has_valid_prior_context=r2.context_applied,
            resolved_metrics=r2.resolved_signals.metrics,
            resolved_dimensions=r2.resolved_signals.dimensions,
        )
        verdict = AnswerabilityGuard().assess(
            "Bir de gerçekleşme oranını ekle.", context=answerability_input
        )
        assert verdict.answerable is True
        assert verdict.reason == "resolved_context_detected"

    def test_sql_plan_executes_no_out_of_scope(self):
        manager = ContextManager()
        session_id = "test-018-additive-5"
        self._turn1(manager, session_id)
        r2 = manager.resolve("Bir de gerçekleşme oranını ekle.", session_id)

        plan = _build_plan(r2.resolved_question)
        assert "SubeAdi" in plan.dimensions
        assert "appointment_count" in plan.metrics
        assert "completed_appointment_rate" in plan.metrics

        state = AgentState(
            question=r2.resolved_question,
            intent=_intent(),
            answerable=True,
        )
        assert route_by_intent(state) == "database_query"


# ── Other follow-up phrasings (item 11) ─────────────────────────────────────


class TestOtherFollowUps:
    def _seed(self, manager: ContextManager, session_id: str):
        r1 = ResolutionResult(
            original_question="Şubelere göre randevu sayılarını karşılaştır.",
            resolved_question="Şubelere göre randevu sayılarını karşılaştır.",
        )
        plan1 = QueryPlan(
            question="Şubelere göre randevu sayılarını karşılaştır.",
            dimensions=["SubeAdi"],
            metrics=["appointment_count"],
            analysis_type="count",
        )
        manager.update(r1, session_id=session_id, query_plan=plan1)

    @pytest.mark.parametrize(
        "question,expected_metric",
        [
            ("Bir de farklı hasta sayısını ekle.", "unique_patient_count"),
            ("Gerçekleşme oranı da olsun.", "completed_appointment_rate"),
            ("Ortalama süreyi de ekle.", "appointment_duration_average"),
        ],
    )
    def test_additive_followups_extend_metrics(self, question, expected_metric):
        manager = ContextManager()
        session_id = f"test-018-other-{hash(question) & 0xffff}"
        self._seed(manager, session_id)
        r2 = manager.resolve(question, session_id)
        assert expected_metric in r2.resolved_signals.metrics
        assert "appointment_count" in r2.resolved_signals.metrics
        assert r2.context_applied is True

    def test_doktor_bazinda_elliptical_followup(self):
        manager = ContextManager()
        session_id = "test-018-other-doktor"
        self._seed(manager, session_id)
        r2 = manager.resolve("Doktor bazında?", session_id)
        assert r2.context_applied is True
        assert "appointment_count" in r2.resolved_signals.metrics

    def test_year_only_followup_still_applies_context(self):
        manager = ContextManager()
        session_id = "test-018-other-year"
        self._seed(manager, session_id)
        r2 = manager.resolve("2024 yılının?", session_id)
        assert r2.context_applied is True


# ── Out-of-scope stays out-of-scope; no false unsupported claims ───────────


class TestOutOfScopeStillWorks:
    def test_unrelated_question_stays_out_of_scope(self):
        state = AgentState(question="Bitcoin fiyatı?", intent=_intent(), answerable=False)
        assert route_by_intent(state) == "out_of_scope"

    def test_supported_followup_never_forced_out_of_scope(self):
        manager = ContextManager()
        session_id = "test-018-oos-supported"
        r1 = ResolutionResult(
            original_question="Şubelere göre randevu sayılarını karşılaştır.",
            resolved_question="Şubelere göre randevu sayılarını karşılaştır.",
        )
        plan1 = QueryPlan(
            question="Şubelere göre randevu sayılarını karşılaştır.",
            dimensions=["SubeAdi"],
            metrics=["appointment_count"],
        )
        manager.update(r1, session_id=session_id, query_plan=plan1)
        r2 = manager.resolve("Bir de gerçekleşme oranını ekle.", session_id)
        answerability_input = AnswerabilityInput(
            raw_question="Bir de gerçekleşme oranını ekle.",
            resolved_question=r2.resolved_question,
            has_valid_prior_context=r2.context_applied,
            resolved_metrics=r2.resolved_signals.metrics,
            resolved_dimensions=r2.resolved_signals.dimensions,
        )
        verdict = AnswerabilityGuard().assess(
            "Bir de gerçekleşme oranını ekle.", context=answerability_input
        )
        state = AgentState(
            question=r2.resolved_question, intent=_intent(), answerable=verdict.answerable
        )
        assert route_by_intent(state) == "database_query"

    def test_unavailable_capabilities_not_advertised(self):
        from app.agent.nodes.generate_out_of_scope import _build_capability_markdown

        markdown = _build_capability_markdown()
        for unsupported in ("reçete", "fatura", "laboratuvar", "yatış", "tanı"):
            assert unsupported not in markdown.lower()


# ── Routing (item 5/11) ─────────────────────────────────────────────────────


class TestRouting:
    def test_single_metric_monthly_trend_routes_local(self):
        analytics = AnalyticsResult(
            analytics_type="trend",
            intents=[AnalyticsIntent.TREND],
            data_shape=DataShape.TIME_SERIES,
            metrics={
                "count": 6,
                "total": 81.0,
                "average": 13.5,
                "growth_rate": 58.33,
                "trend_direction": "upward",
            },
            row_count=6,
        )
        rules = InsightRulesEngine().evaluate(analytics)
        router = InsightRouter(remote_available=True)
        decision = router.decide(analytics, rules, InsightConfidence.MEDIUM)
        assert decision.mode == InsightGenerationMode.LOCAL_LLM
        assert decision.selected_provider == "ollama"
        assert decision.complexity_score < 3

    def test_three_metric_branch_comparison_routes_remote(self):
        from app.analytics.models import MetricSummary

        analytics = AnalyticsResult(
            analytics_type="general",
            intents=[AnalyticsIntent.TREND, AnalyticsIntent.COMPARISON, AnalyticsIntent.RANKING],
            data_shape=DataShape.TABULAR,
            metrics={"count": 15, "total": 3000.0, "average": 200.0},
            metric_summaries={
                "appointment_count": MetricSummary(metric_id="appointment_count", total=100),
                "completed_appointment_rate": MetricSummary(
                    metric_id="completed_appointment_rate", average=80.0
                ),
                "appointment_duration_average": MetricSummary(
                    metric_id="appointment_duration_average", average=25.0
                ),
            },
            row_count=15,
        )
        rules = InsightRulesEngine().evaluate(analytics)
        router = InsightRouter(remote_available=True)
        decision = router.decide(analytics, rules, InsightConfidence.MEDIUM)
        assert decision.mode == InsightGenerationMode.REMOTE_LLM
        assert decision.selected_provider == "nvidia"
        assert decision.complexity_score >= 3

    def test_basic_distribution_routes_deterministic(self):
        analytics = AnalyticsResult(
            analytics_type="distribution",
            data_shape=DataShape.CATEGORICAL,
            metrics={
                "count": 4,
                "total": 100.0,
                "average": 25.0,
                "top_category": "X",
                "distribution": {"X": 40.0, "Y": 30.0, "Z": 30.0},
            },
            row_count=3,
        )
        rules = InsightRulesEngine().evaluate(analytics)
        router = InsightRouter(remote_available=True)
        decision = router.decide(analytics, rules, InsightConfidence.HIGH)
        assert decision.mode == InsightGenerationMode.DETERMINISTIC
        assert decision.selected_provider == "deterministic"

    def test_grounded_branch_count_deterministic_when_supported(self):
        analytics = AnalyticsResult(
            analytics_type="count",
            data_shape=DataShape.SINGLE_VALUE,
            metrics={"count": 42, "total": 42.0},
            row_count=1,
        )
        rules = InsightRulesEngine().evaluate(analytics)
        router = InsightRouter(remote_available=True)
        decision = router.decide(analytics, rules, InsightConfidence.HIGH)
        assert decision.mode == InsightGenerationMode.DETERMINISTIC


# ── Trend semantics (item 7/11) ─────────────────────────────────────────────


class TestTrendSemantics:
    def _labels(self, n: int) -> list[str]:
        return [f"2026-0{i + 1}-01" for i in range(n)]

    def test_fluctuating_series_is_non_monotonic_mixed_endpoint_upward(self):
        values = [12, 15, 9, 13, 13, 19]
        tm = compute_trend_metrics(self._labels(6), values, "month", date(2026, 8, 15))
        assert tm.monotonicity == "non_monotonic"
        assert tm.trend_consistency == "mixed_or_fluctuating"
        assert tm.endpoint_direction == "upward"

    def test_monotonic_up_series(self):
        tm = compute_trend_metrics(self._labels(4), [10, 11, 12, 13], "month", date(2026, 8, 15))
        assert tm.monotonicity == "monotonic_up"
        assert tm.trend_consistency == "consistent_upward"

    def test_monotonic_down_series(self):
        tm = compute_trend_metrics(self._labels(4), [13, 12, 11, 10], "month", date(2026, 8, 15))
        assert tm.monotonicity == "monotonic_down"
        assert tm.trend_consistency == "consistent_downward"

    def test_flat_series(self):
        tm = compute_trend_metrics(self._labels(3), [10, 10, 10], "month", date(2026, 8, 15))
        assert tm.monotonicity == "flat"
        assert tm.trend_consistency == "flat"

    def test_partial_final_period_excluded_before_classification(self):
        # today falls inside the last bucket's month -> excluded from comparison.
        labels = ["2026-05-01", "2026-06-01", "2026-07-01"]
        values = [10, 11, 999]
        tm = compute_trend_metrics(labels, values, "month", date(2026, 7, 15))
        assert tm.comparison_excluded_partial_period is True
        assert tm.comparable_period_count == 2
        assert tm.monotonicity == "monotonic_up"

    def test_forbidden_continuous_growth_phrase_detected(self):
        assert contains_forbidden_continuous_growth_phrase("Dönem boyunca sürekli arttı.")
        assert contains_forbidden_continuous_growth_phrase("Tutarlı bir yükseliş görüldü.")
        assert not contains_forbidden_continuous_growth_phrase("Dalgalanmalar görülmüştür.")

    def test_forbidden_phrase_repaired_when_non_monotonic(self):
        values = [12, 15, 9, 13, 13, 19]
        tm = compute_trend_metrics(self._labels(6), values, "month", date(2026, 8, 15))
        narrative = InsightNarrative(
            title="T",
            summary="Randevular dönem boyunca sürekli arttı.",
            highlights=["Her ay arttı ve tutarlı yükseliş görüldü."],
            observations=[],
            considerations=[],
        )
        repaired = repair_narrative(narrative, tm)
        assert not contains_forbidden_continuous_growth_phrase(repaired.summary)
        assert not contains_forbidden_continuous_growth_phrase(repaired.highlights[0])
        assert "Dalgalanmalara rağmen" in repaired.summary

    def test_forbidden_phrase_not_touched_when_monotonic(self):
        tm = compute_trend_metrics(
            self._labels(4), [10, 11, 12, 13], "month", date(2026, 8, 15)
        )
        narrative = InsightNarrative(
            title="T", summary="Dönem boyunca sürekli arttı.", highlights=[],
            observations=[], considerations=[],
        )
        repaired = repair_narrative(narrative, tm)
        assert repaired.summary == narrative.summary

    def test_validate_and_repair_integrates_narrative_guard(self):
        values = [12, 15, 9, 13, 13, 19]
        tm = compute_trend_metrics(self._labels(6), values, "month", date(2026, 8, 15))
        analytics = AnalyticsResult(
            analytics_type="trend",
            data_shape=DataShape.TIME_SERIES,
            metrics={"count": 6, "total": 81.0},
            row_count=6,
            trend_metrics=tm,
        )
        narrative = InsightNarrative(
            title="Randevu Eğilimi",
            summary="Randevular dönem boyunca sürekli arttı, kesintisiz yükseldi.",
            highlights=[],
            observations=[],
            considerations=[],
        )
        repaired, verdict = validate_and_repair(narrative, analytics, [])
        assert verdict.continuous_growth_phrase_repaired is True
        assert not contains_forbidden_continuous_growth_phrase(repaired.summary)

    def test_unsupported_causal_speculation_dropped(self):
        analytics = AnalyticsResult(
            analytics_type="count",
            data_shape=DataShape.SINGLE_VALUE,
            metrics={"count": 0, "total": 0.0},
            row_count=1,
        )
        narrative = InsightNarrative(
            title="T",
            summary="Sonuç sıfır.",
            highlights=[],
            observations=[],
            considerations=["Bu bir veri toplama sorunu olabilir."],
        )
        repaired, verdict = validate_and_repair(narrative, analytics, [])
        assert verdict.causal_certainty_dropped >= 1
        assert not any("veri toplama sorunu" in text for text in repaired.considerations)


# ── Metadata (item 6/11) ─────────────────────────────────────────────────────


class TestMetadata:
    def test_resolved_time_grain_month_from_plan(self):
        from app.context.analytical_signals import granularity_to_time_grain

        assert granularity_to_time_grain("month") == "month"
        assert granularity_to_time_grain(None) is None

    def test_planner_resolves_month_grain_for_trend_question(self):
        plan = _build_plan("Son 6 aydaki randevu eğilimini özetle.")
        assert plan.grouping_granularity == "month"

    def test_routing_reason_exposed(self):
        analytics = AnalyticsResult(
            analytics_type="trend",
            data_shape=DataShape.TIME_SERIES,
            metrics={"count": 6, "total": 81.0, "growth_rate": 58.33},
            row_count=6,
        )
        rules = InsightRulesEngine().evaluate(analytics)
        decision = InsightRouter(remote_available=True).decide(
            analytics, rules, InsightConfidence.MEDIUM
        )
        assert decision.routing_reason
        assert isinstance(decision.complexity_factors, list)

    def test_context_applied_false_for_independent_question(self):
        manager = ContextManager()
        session_id = "test-018-independent"
        r1 = ResolutionResult(
            original_question="Şubelere göre randevu sayılarını karşılaştır.",
            resolved_question="Şubelere göre randevu sayılarını karşılaştır.",
        )
        plan1 = QueryPlan(
            question="Şubelere göre randevu sayılarını karşılaştır.",
            dimensions=["SubeAdi"],
            metrics=["appointment_count"],
        )
        manager.update(r1, session_id=session_id, query_plan=plan1)
        # Long, fully self-contained question with its own explicit dimension
        # AND metric — too many content tokens to be elliptical, and states
        # everything itself, so nothing is actually inherited from context.
        r2 = manager.resolve(
            "Kardiyoloji bölümündeki doktorların toplam randevu sayısını göster.", session_id
        )
        assert r2.context_applied is False
