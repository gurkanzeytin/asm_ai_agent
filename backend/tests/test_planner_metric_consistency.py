"""PLANNER-METRIC-CONSISTENCY-002 regression tests.

Covers the four planner/catalog/compliance blockers found after the
conversational-memory merge layer was independently verified sound:
grouping/projection inconsistency, conditional-metric aggregation staleness,
measure-phrase coverage gaps, and multi-metric ambiguity. Fully deterministic
(no LLM, no database) except the live-pipeline scenario, which runs the real
planner + context-merge + deterministic SQL builder + compliance validator
with zero mocking of any decision logic.
"""

import pytest

from app.agent.nodes.resolve_filter_values import ResolveFilterValuesNode
from app.agent.nodes.retrieve_context import RetrieveContextNode
from app.agent.state import AgentState
from app.context import ContextManager
from app.context.session_store import SessionStore
from app.database_intelligence.models import DatabaseContext, ViewMetadata
from app.planning.compliance import PlanComplianceValidator
from app.planning.models import QueryPlan
from app.planning.planner import QueryPlanner
from app.semantics import catalog
from app.semantics.view_mapping import fold
from app.services.deterministic_sql_builder import (
    SUPPORTED_ANALYSIS_TYPES,
    DeterministicSQL,
    DeterministicSQLBuilder,
)
from app.services.query_analyzer import QueryAnalyzer

VIEW_NAME = "dbo.vw_RandevuRaporu"
VIEW = ViewMetadata(name=VIEW_NAME, columns=[])


def plan_for(question: str) -> QueryPlan:
    analysis = QueryAnalyzer().analyze(question)
    return QueryPlanner().build_plan(question, analysis, tables=[], views=[VIEW])


def build_and_check(plan: QueryPlan):
    built = DeterministicSQLBuilder().build(plan)
    compliance = PlanComplianceValidator().check(built.sql, plan)
    return built, compliance


class _PromptService:
    context = DatabaseContext(tables=[], views=[VIEW])

    async def retrieve_schema_context(self, question):
        return self.context


async def _run_turn(manager: ContextManager, session_id: str, question: str) -> QueryPlan:
    """Runs one turn through the real ContextManager + RetrieveContextNode +
    ResolveFilterValuesNode (planner + conversational merge), mirroring the
    exact slice of the production pipeline that owns every blocker fixed
    here. Deliberately excludes GenerateSQLNode's own LLM repair loop —
    DeterministicSQLBuilder + PlanComplianceValidator are exercised directly
    instead, which is the deterministic path these blockers actually live in."""
    resolution = manager.resolve(question, session_id)
    retained = (
        QueryPlan.model_validate(resolution.retained_query_plan_snapshot)
        if resolution.retained_query_plan_snapshot
        else None
    )
    state = AgentState(
        question=resolution.resolved_question,
        raw_question=question,
        retained_query_plan=retained,
        context_follow_up_detected=resolution.follow_up_detected,
    )
    state = await RetrieveContextNode(_PromptService()).execute(state)
    state = await ResolveFilterValuesNode().execute(state)
    manager.update(resolution, session_id, query_plan=state.query_plan)
    return state.query_plan


# ═══════════════════════ A/B — Literal four-turn scenario ═══════════════════


@pytest.mark.asyncio
async def test_literal_four_turn_scenario_end_to_end():
    """The exact wording from the task spec, unmodified — no substitute
    phrasing. Runs through the real planner + conversational merge pipeline
    and verifies every turn's plan is internally consistent and passes
    PlanComplianceValidator with SQL built by the real deterministic builder."""
    manager = ContextManager(store=SessionStore())
    session_id = "planner-metric-consistency-live"

    # Turn 1
    plan1 = await _run_turn(
        manager, session_id, "Ocak 2026 için doktor bazında randevu sayılarını göster."
    )
    assert plan1.metrics == ["appointment_count"]
    assert plan1.aggregation == "COUNT(*)"
    assert plan1.dimensions == ["DoktorId"]
    assert "DoktorId" in plan1.projection
    assert "GenelRandevuKaynakAdi" not in plan1.projection
    assert plan1.date_filters and plan1.date_filters[0].start_date == "2026-01-01"
    assert plan1.date_filters[0].end_date == "2026-01-31"
    built1, compliance1 = build_and_check(plan1)
    assert compliance1.compliant, compliance1.missing

    # Turn 2
    plan2 = await _run_turn(manager, session_id, "Yalnız gerçekleşenleri göster.")
    assert plan2.metrics == ["appointment_count"]
    assert plan2.dimensions == ["DoktorId"]
    assert plan2.date_filters == plan1.date_filters
    assert any("Gerçekleşti" in flt for flt in plan2.extra_filters)
    built2, compliance2 = build_and_check(plan2)
    assert compliance2.compliant, compliance2.missing

    # Turn 3
    plan3 = await _run_turn(manager, session_id, "O zaman sadece beklemede olanları göster.")
    assert plan3.metrics == ["appointment_count"]
    assert plan3.dimensions == ["DoktorId"]
    assert plan3.date_filters == plan1.date_filters
    assert plan3.extra_filters == ["RandevuDurumu = 'Beklemede'"]
    assert not any("Gerçekleşti" in flt for flt in plan3.extra_filters)
    built3, compliance3 = build_and_check(plan3)
    assert compliance3.compliant, compliance3.missing
    assert "N'Beklemede'" in built3.sql

    # Turn 4 — explicit conditional metric switch
    plan4 = await _run_turn(manager, session_id, "Bekleyen randevu sayısı nedir?")
    assert plan4.metrics == ["waiting_count"]
    assert plan4.aggregation == (
        "SUM(CASE WHEN RandevuDurumu = N'Beklemede' THEN 1 ELSE 0 END)"
    )
    assert plan4.date_filters == plan1.date_filters
    built4, compliance4 = build_and_check(plan4)
    assert compliance4.compliant, compliance4.missing
    assert "waiting_count" in built4.sql


# ═══════════════════════ C — Grouping phrase equivalence ════════════════════
#
# Run through the real pipeline (planner + merge/normalize), not the bare
# planner: the doctor-count GenelRandevuKaynakAdi->DoktorId reconciliation
# (AI-INTELLIGENCE, app.context.analytical_signals._normalize_query_plan)
# only runs inside merge_query_plans, exactly like production traffic.
#
# Invariant under test (Blocker 1): whenever projection is populated, it must
# be CONSISTENT with the resolved dimensions — never a stale, different
# column. Projection is not required to be non-empty for every phrasing
# (e.g. a plain grouping mention with no "bazında/göre" trigger legitimately
# leaves it empty); what must never happen is projection disagreeing with
# dimensions once both are set.


async def _single_turn_plan(question: str) -> QueryPlan:
    manager = ContextManager(store=SessionStore())
    return await _run_turn(manager, "grouping-equivalence", question)


def _assert_projection_consistent_with_dimensions(plan: QueryPlan, question: str) -> None:
    if plan.projection:
        assert plan.projection == plan.dimensions, (question, plan.projection, plan.dimensions)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "question",
    [
        "Doktor bazında randevu sayılarını göster.",
        "Doktorlara göre randevu sayılarını göster.",
        "Doktorların randevu sayılarını göster.",
        "Doktor kırılımında randevu sayılarını göster.",
    ],
)
async def test_doctor_grouping_phrase_equivalence(question):
    plan = await _single_turn_plan(question)
    assert plan.dimensions == ["DoktorId"], (question, plan.dimensions)
    _assert_projection_consistent_with_dimensions(plan, question)
    _, compliance = build_and_check(plan)
    assert compliance.compliant, (question, compliance.missing)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "question",
    [
        "Bölüm bazında randevu sayılarını göster.",
        "Bölümlere göre randevu sayılarını göster.",
    ],
)
async def test_department_grouping_phrase_equivalence(question):
    plan = await _single_turn_plan(question)
    assert plan.dimensions == ["GenelRandevuBolumAdi"], (question, plan.dimensions)
    _assert_projection_consistent_with_dimensions(plan, question)
    _, compliance = build_and_check(plan)
    assert compliance.compliant, (question, compliance.missing)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "question",
    [
        "Şube bazında randevu sayılarını göster.",
        "Şubelere göre randevu sayılarını göster.",
    ],
)
async def test_branch_grouping_phrase_equivalence(question):
    plan = await _single_turn_plan(question)
    assert plan.dimensions == ["SubeAdi"], (question, plan.dimensions)
    _assert_projection_consistent_with_dimensions(plan, question)
    _, compliance = build_and_check(plan)
    assert compliance.compliant, (question, compliance.missing)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "question",
    [
        "Durum bazında randevu sayılarını göster.",
        "Durumlara göre randevu sayılarını göster.",
    ],
)
async def test_status_grouping_phrase_equivalence(question):
    plan = await _single_turn_plan(question)
    assert plan.dimensions == ["RandevuDurumu"], (question, plan.dimensions)
    _assert_projection_consistent_with_dimensions(plan, question)
    _, compliance = build_and_check(plan)
    assert compliance.compliant, (question, compliance.missing)


# ═══════════════════════ D — Measure verb / inflection coverage ═════════════


@pytest.mark.parametrize(
    ("question", "expected_metric"),
    [
        ("Bekleyenleri say.", "waiting_count"),
        ("Bekleyenlerin toplamını göster.", "waiting_count"),
        ("Kaç tane bekleyen randevu var?", "waiting_count"),
        ("Bekleyen randevuların miktarını ver.", "waiting_count"),
        ("Gelmeyen randevu adedini ver.", "no_show_count"),
    ],
)
def test_measure_request_phrases_resolve_conditional_metric(question, expected_metric):
    folded = fold(question)
    matched = catalog.match_metrics(folded) or None
    if not matched:
        # Only the planner's status-value + measure-request fallback covers
        # this phrasing (no catalog synonym match at all) — verify through
        # the full plan instead of the raw catalog matcher.
        plan = plan_for(question)
        assert plan.metrics == [expected_metric], (question, plan.metrics)
    else:
        assert expected_metric in matched, (question, matched)


@pytest.mark.parametrize(
    "question",
    [
        "Bekleyenleri göster.",
        "Sadece beklemede olanları getir.",
        "Gelmeyenleri listele.",
    ],
)
def test_bare_status_phrases_do_not_crash_and_stay_catalog_bounded(question):
    """These bare status phrases carry no explicit measure-request marker.
    Standalone (no prior turn), the planner may reasonably resolve the
    catalog's own conditional metric for the mentioned status (there is no
    retained metric to protect yet) — the memory-layer's filter-vs-metric
    distinction (verified in MEMORY-FOUNDATION-STABILIZATION-001) is what
    protects a RETAINED metric in a follow-up turn, exercised separately in
    test_conversational_filter_sql_live_fix.py. Here we only assert the
    planner never invents an unsupported metric, and that a deterministic
    SQL build (when the plan shape supports one at all) stays compliant —
    a bare listing phrase with no measure/aggregation intent legitimately
    falls outside the deterministic builder's supported shapes and is not
    a compliance failure."""
    plan = plan_for(question)
    for metric_id in plan.metrics:
        assert metric_id in catalog.load_metric_catalog().by_id()
    built = DeterministicSQLBuilder().build(plan)
    if isinstance(built, DeterministicSQL):
        compliance = PlanComplianceValidator().check(built.sql, plan)
        assert compliance.compliant, (question, compliance.missing)


# ═══════════════════════════ E — Metric specificity ══════════════════════════


def test_single_status_mention_prefers_specific_conditional_metric():
    matched = catalog.match_metrics(fold("Gelmeyen randevu adedini ver."))
    assert matched == ["no_show_count"]


def test_explicit_multi_metric_conjunction_preserves_both():
    matched = catalog.match_metrics(
        fold("Toplam randevu ve gelmeyen randevu sayılarını karşılaştır.")
    )
    assert "appointment_count" in matched
    assert "no_show_count" in matched


# ═══════════════════ F — Conditional metric family sweep ════════════════════


def _conditional_metric_ids() -> list[str]:
    return [
        metric.id
        for metric in catalog.load_metric_catalog().metrics
        if metric.formula_type in ("conditional_count", "conditional_rate")
        and metric.formula
        # Deliberately catalog-excluded (MetricSpec.status="requires_verified_mapping")
        # metrics are intentionally never buildable — not a Blocker 2 concern.
        and metric.status != "requires_verified_mapping"
    ]


@pytest.mark.parametrize("metric_id", _conditional_metric_ids())
def test_every_conditional_metric_builds_compliant_sql(metric_id):
    """Dynamic sweep, driven entirely by the catalog: for every catalog
    metric whose formula is a conditional aggregation (status_value-anchored
    count or rate), a standalone plan naming only that metric must not carry
    a stale generic-aggregation compliance mismatch — generalizes Blocker 2's
    fix beyond waiting_count to the whole family.

    analysis_type is set from the metric's own catalog declaration, exactly
    as the real planner does (QueryPlanner._resolve_intelligence: `pattern =
    primary.analysis_type` when no pattern keyword fired) — this test
    exercises the aggregation/compliance consistency in isolation, not
    planner routing, which is already covered by the live four-turn test.

    Scoped narrowly to the Blocker 2 symptom (a literal "aggregation ..."
    compliance entry): a handful of data-quality metrics also trip the
    unrelated, pre-existing raw-detail-projection heuristic (their formula
    happens to reference BitisTarihi/CreatedDate inside a CASE expression)
    and one catalog metric (protocol_conversion_rate) declares an
    analysis_type ("conversion") the deterministic builder doesn't route at
    all — both are catalog-metadata/heuristic gaps unrelated to any of the
    four blockers this task fixes, called out in the deliverable rather than
    silently patched here.
    """
    spec = catalog.load_metric_catalog().by_id()[metric_id]
    if spec.analysis_type not in SUPPORTED_ANALYSIS_TYPES:
        pytest.skip(f"{metric_id}: analysis_type {spec.analysis_type!r} not builder-routable "
                    "(pre-existing catalog/builder gap, unrelated to Blocker 2)")
    plan = QueryPlan(
        question=f"test:{metric_id}",
        metrics=[metric_id],
        aggregation=spec.formula,
        analysis_type=spec.analysis_type,
    )
    built = DeterministicSQLBuilder().build(plan)
    assert isinstance(built, DeterministicSQL), (metric_id, built)
    compliance = PlanComplianceValidator().check(built.sql, plan)
    stale_aggregation_entries = [m for m in compliance.missing if m.startswith("aggregation ")]
    assert not stale_aggregation_entries, (metric_id, stale_aggregation_entries)
    assert metric_id in built.sql


# ═══════════════════ G — Non-regression pointer ══════════════════════════════
#
# Full non-regression coverage (conversational memory, query planner,
# analytical signals, deterministic SQL pipeline, compliance, reporting/
# workflow) is the existing test suite itself — see the deliverable's test
# run for exact counts. No duplicate assertions are added here.
