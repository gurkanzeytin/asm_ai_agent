"""AI-INTELLIGENCE-008 tests: implicit intent resolution, assumption policy,
query strategy, adaptive fallback, result reasoning, and the RW blind
real-world evaluation set. Deterministic — no LLM, no database.
"""

from datetime import UTC, datetime

import pytest

from app.agent.nodes.execute_sql import ADAPTIVE_EMPTY_RESULT_PREFIX, ExecuteSQLNode
from app.agent.state import AgentState
from app.analytics.result_reasoning import ResultReasoner
from app.application_models.workflow_models import QueryResult
from app.database_intelligence.models import ViewMetadata
from app.planning.models import DateFilterPlan, QueryPlan
from app.planning.planner import QueryPlanner, format_plan_for_prompt
from app.semantics import examples, reasoning
from app.semantics.view_mapping import fold
from app.services.query_analyzer import QueryAnalyzer

VIEW = ViewMetadata(name="dbo.vw_RandevuRaporu", columns=[])


@pytest.fixture(scope="module")
def analyzer():
    return QueryAnalyzer()


@pytest.fixture(scope="module")
def planner():
    return QueryPlanner()


def plan_for(planner, analyzer, question):
    return planner.build_plan(question, analyzer.analyze(question), tables=[], views=[VIEW])


def _result(columns, rows):
    return QueryResult(
        columns=columns,
        rows=rows,
        row_count=len(rows),
        execution_time_ms=1.0,
        success=True,
        executed_at=datetime.now(UTC),
        database_provider="mssql",
    )


# ══════════════════════ Implicit intent -> strategy ══════════════════════


@pytest.mark.parametrize(
    "question,expected_type",
    [
        ("gelmeme oranı patlamış galiba", "anomaly_comparison"),
        ("işler nasıl gidiyor", "multi_metric_performance"),
        ("son dakika alanlar geliyor mu", "cohort_analysis"),
        ("şubeler arasında çok fark var mı", "variance_analysis"),
        ("bu aralar durum ne", "adaptive_time_comparison"),
        ("geçen seneye kıyasla randevu sayısı", "baseline_comparison"),
    ],
)
def test_implicit_intent_resolves_strategy(question, expected_type):
    strategy = reasoning.resolve_strategy(fold(question), [], [])
    assert strategy is not None
    assert strategy.analysis_type == expected_type


def test_plain_question_produces_no_strategy():
    assert reasoning.resolve_strategy(fold("bugün kaç randevu var"), [], []) is None


def test_anomaly_strategy_carries_baseline_and_sample_size():
    strategy = reasoning.resolve_strategy(fold("gelmeme sayıları patlamış"), [], ["SubeAdi"])
    assert strategy.current_period == "last_30_days"
    assert strategy.baseline_period == "previous_30_days"
    assert strategy.minimum_sample_size == reasoning.DEFAULT_MINIMUM_SAMPLE_SIZE
    assert "no_show_rate" in strategy.metrics
    assert "cancelled" not in " ".join(strategy.metrics)
    assert strategy.dimensions == ["SubeAdi"]


def test_every_strategy_states_its_assumptions():
    for question in (
        "randevular patlamış",
        "işler nasıl gidiyor",
        "son dakika alanların durumu",
        "doktorlar arasında fark var mı",
        "bu aralar nasıl",
    ):
        strategy = reasoning.resolve_strategy(fold(question), [], [])
        assert strategy is not None, question
        assert strategy.assumptions, question


def test_assumption_policy_wording():
    assert "son 30 gün" in reasoning.ASSUMPTION_POLICY["bu_aralar"]
    assert "24 saat" in reasoning.ASSUMPTION_POLICY["son_dakika"]
    assert "önceki eşit 30 gün" in reasoning.ASSUMPTION_POLICY["onceki_donem"]


# ══════════════════════ Strategy flows into the QueryPlan ═════════════════


def test_plan_carries_strategy_fields(planner, analyzer):
    plan = plan_for(planner, analyzer, "Bu aralar hangi şubede gelmeme oranı artmış?")
    assert plan.analysis_type == "anomaly_comparison"
    assert plan.question_goal
    assert plan.current_period == "last_30_days"
    assert plan.baseline_period == "previous_30_days"
    assert plan.minimum_sample_size == 20
    assert plan.assumptions
    assert plan.comparisons  # baseline registered as a comparison


def test_strategy_renders_into_prompt(planner, analyzer):
    plan = plan_for(planner, analyzer, "Bu aralar hangi şubede gelmeme oranı artmış?")
    rendered = format_plan_for_prompt(plan)
    assert "Goal:" in rendered
    assert "Baseline period: previous_30_days" in rendered
    assert "NEVER raw detail rows" in rendered


def test_cohort_strategy_requires_lead_time_columns(planner, analyzer):
    plan = plan_for(planner, analyzer, "Randevusunu son dakika alanların gelme durumu nasıl?")
    assert plan.cohort and "24" in plan.cohort
    assert "CreatedDate" in plan.required_columns
    assert "BaslangicTarihi" in plan.required_columns


# ══════════════════════ Adaptive fallback ═════════════════════════════════


class _StubWorkflowService:
    async def execute_query(self, sql):  # pragma: no cover - not reached in these tests
        raise AssertionError("not used")


def _state_with(plan, retry_count=0):
    return AgentState(
        question="test",
        query_plan=plan,
        sql_retry_count=retry_count,
    )


def test_adaptive_feedback_on_empty_result_with_date_filter():
    plan = QueryPlan(
        question="q",
        date_filters=[
            DateFilterPlan(expression="bu ay", start_date="2026-07-01", end_date="2026-07-31")
        ],
    )
    node = ExecuteSQLNode(_StubWorkflowService())
    feedback = node._adaptive_feedback(_state_with(plan), _result(["a"], []))
    assert feedback is not None
    assert feedback.startswith(ADAPTIVE_EMPTY_RESULT_PREFIX)
    assert "widen" in feedback


def test_adaptive_feedback_mentions_status_mapping():
    plan = QueryPlan(question="q", extra_filters=["RandevuDurumu = 'İptal'"])
    node = ExecuteSQLNode(_StubWorkflowService())
    feedback = node._adaptive_feedback(_state_with(plan), _result(["a"], []))
    assert feedback is not None
    assert "RandevuDurumu" in feedback


def test_adaptive_feedback_fires_only_once():
    plan = QueryPlan(
        question="q",
        date_filters=[
            DateFilterPlan(expression="bu ay", start_date="2026-07-01", end_date="2026-07-31")
        ],
    )
    node = ExecuteSQLNode(_StubWorkflowService())
    assert node._adaptive_feedback(_state_with(plan, retry_count=1), _result(["a"], [])) is None


def test_no_adaptive_feedback_on_nonempty_result():
    plan = QueryPlan(
        question="q",
        date_filters=[
            DateFilterPlan(expression="bu ay", start_date="2026-07-01", end_date="2026-07-31")
        ],
    )
    node = ExecuteSQLNode(_StubWorkflowService())
    assert node._adaptive_feedback(_state_with(plan), _result(["a"], [{"a": 1}])) is None


def test_no_adaptive_feedback_without_narrowing_constraints():
    node = ExecuteSQLNode(_StubWorkflowService())
    assert node._adaptive_feedback(_state_with(QueryPlan(question="q")), _result(["a"], [])) is None


# ══════════════════════ Result reasoning ══════════════════════════════════


def test_reasoner_flags_low_sample_groups():
    plan = QueryPlan(question="q", minimum_sample_size=20)
    result = _result(
        ["SubeAdi", "randevu_sayisi"],
        [{"SubeAdi": "Merkez", "randevu_sayisi": 120}, {"SubeAdi": "Ada", "randevu_sayisi": 4}],
    )
    outcome = ResultReasoner().reason(result, plan)
    assert "Ada" in outcome.low_sample_groups
    assert any("Düşük örneklem" in finding for finding in outcome.findings)


def test_reasoner_computes_baseline_delta():
    plan = QueryPlan(question="q", baseline_period="previous_30_days")
    result = _result(["bu_donem", "onceki_donem"], [{"bu_donem": 130, "onceki_donem": 100}])
    outcome = ResultReasoner().reason(result, plan)
    assert outcome.baseline_delta == 30.0
    assert any("%30" in finding for finding in outcome.findings)


def test_reasoner_limits_findings_to_three():
    plan = QueryPlan(question="q", minimum_sample_size=20, baseline_period="previous")
    rows = [{"grup": f"G{i}", "oran": float(i)} for i in range(30)]
    outcome = ResultReasoner().reason(_result(["grup", "oran"], rows), plan)
    assert len(outcome.findings) <= 3
    assert outcome.summarized


def test_reasoner_echoes_plan_assumptions():
    plan = QueryPlan(question="q", assumptions=["'Bu aralar' son 30 gün olarak yorumlandı."])
    outcome = ResultReasoner().reason(_result(["a"], [{"a": 1}]), plan)
    assert outcome.assumptions == plan.assumptions


def test_reasoner_never_raises_on_weird_input():
    outcome = ResultReasoner().reason(_result([], []), None)
    assert outcome.findings  # empty-result note


# ══════════════════════ RW blind real-world evaluation ════════════════════


@pytest.fixture(scope="module")
def rw_examples():
    dataset = examples.load_golden_dataset()
    rw = {e.id: e for e in dataset.questions if e.id.startswith("RW-")}
    assert len(rw) == 6
    return rw


def test_rw_examples_are_blind_and_never_retrieved(rw_examples):
    for example in rw_examples.values():
        assert example.blind
    retrieved = examples.retrieve_examples(
        "Bu aralar hangi şubede iptaller patlamış?",
        "anomaly_comparison",
        ["cancelled_appointment_rate"],
        ["SubeAdi"],
    )
    assert not any(e.id.startswith("RW-") for e in retrieved)


def test_rw001_cancel_is_controlled_limitation(planner, analyzer, rw_examples):
    example = rw_examples["RW-001"]
    assert example.expected_plan.answerable is False
    plan = plan_for(planner, analyzer, example.question)
    assert plan.answerable is False
    assert "İptal" in (plan.answerability_reason or "") or "iptal" in (plan.answerability_reason or "").lower()
    assert not plan.metrics or "cancelled" not in " ".join(plan.metrics)


def test_rw002_no_show_anomaly(planner, analyzer, rw_examples):
    example = rw_examples["RW-002"]
    plan = plan_for(planner, analyzer, example.question)
    assert plan.analysis_type == example.analysis_type
    assert set(example.must_produce_metrics) <= set(plan.metrics)
    assert set(example.must_use_columns) <= set(plan.required_columns)
    assert plan.baseline_period == example.expected_baseline
    assert plan.dimensions == ["SubeAdi"]
    assert plan.minimum_sample_size == 20
    assert plan.assumptions  # forbidden: silent defaults
    rendered = format_plan_for_prompt(plan)
    assert "NEVER raw detail rows" in rendered  # forbidden: detail_rows


def test_rw003_multi_metric_performance(planner, analyzer, rw_examples):
    example = rw_examples["RW-003"]
    plan = plan_for(planner, analyzer, example.question)
    assert plan.analysis_type == example.analysis_type
    assert set(example.must_produce_metrics) <= set(plan.metrics)
    assert plan.baseline_period == "same_period_previous_year"
    assert set(example.must_use_columns) <= set(plan.required_columns)
    assert plan.assumptions


def test_rw004_ambiguous_dimension_requires_clarification(analyzer, rw_examples):
    example = rw_examples["RW-004"]
    assert example.expected_plan.clarification_required
    ambiguity = analyzer.detect_ambiguity(example.question)
    assert ambiguity is not None  # forbidden: guessing a dimension
    assert ambiguity.matched_phrase == example.ambiguous_phrase
    assert ambiguity.options


def test_rw005_lead_time_cohort(planner, analyzer, rw_examples):
    example = rw_examples["RW-005"]
    plan = plan_for(planner, analyzer, example.question)
    assert plan.analysis_type == "cohort_analysis"
    assert set(example.must_produce_metrics) <= set(plan.metrics)
    assert set(example.must_use_columns) <= set(plan.required_columns)
    assert plan.cohort and "lead_time" in plan.cohort.lower().replace(" ", "_")
    rendered = format_plan_for_prompt(plan)
    assert "Cohort filter" in rendered
    assert "NEVER raw detail rows" in rendered


def test_rw006_variance(planner, analyzer, rw_examples):
    example = rw_examples["RW-006"]
    plan = plan_for(planner, analyzer, example.question)
    assert plan.analysis_type == "variance_analysis"
    assert set(example.must_produce_metrics) <= set(plan.metrics)
    # doctor resolves to DoktorId or the descriptive source-name column
    assert set(plan.dimensions) & set(example.dimensions)
    assert plan.assumptions
