"""Live-style conversational memory regressions from UI testing.

No LLM or database is used. These tests exercise the same context resolver
and planner merge path that the UI hits through a stable session_id.
"""

from unittest.mock import AsyncMock

import pytest

from app.agent.nodes.resolve_filter_values import ResolveFilterValuesNode
from app.agent.nodes.retrieve_context import RetrieveContextNode
from app.agent.state import AgentState
from app.context import ContextManager
from app.context.models import ConversationContext
from app.context.resolver import ContextResolver
from app.context.session_store import SessionStore
from app.database_intelligence.models import DatabaseContext, ViewMetadata
from app.planning.models import QueryPlan
from app.services.query_analyzer import QueryAnalyzer
from app.planning.planner import QueryPlanner
from app.planning.value_resolver import resolve_value
from app.services.deterministic_sql_builder import (
    DeterministicSQL,
    DeterministicSQLBuilder,
)
from app.planning.compliance import PlanComplianceValidator
from app.planning.value_resolver import extract_candidate_phrases


class _GroundedResolver:
    async def resolve(self, field_name: str, phrase: str):
        candidates = ["E", "K", "D"] if field_name == "gender" else []
        return resolve_value(field_name, phrase, candidates)


class _Chain:
    def __init__(self) -> None:
        self.manager = ContextManager(store=SessionStore())
        prompt_service = AsyncMock()
        prompt_service.retrieve_schema_context.return_value = DatabaseContext(
            tables=[], views=[ViewMetadata(name="dbo.vw_RandevuRaporu", columns=[])]
        )
        self.retrieve = RetrieveContextNode(prompt_service)
        self.resolve_filters = ResolveFilterValuesNode(_GroundedResolver())
        self.session_id = "live-memory"

    async def turn(self, question: str) -> tuple[QueryPlan, object]:
        resolution = self.manager.resolve(question, self.session_id)
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
        state = await self.retrieve.execute(state)
        state = await self.resolve_filters.execute(state)
        assert state.query_plan is not None
        assert self.manager.update(
            resolution, self.session_id, query_plan=state.query_plan
        )
        return state.query_plan, resolution


def _date(plan: QueryPlan) -> tuple[str, str] | None:
    if not plan.date_filters:
        return None
    value = plan.date_filters[0]
    return value.start_date, value.end_date


def test_bare_bunu_with_analytical_change_is_a_followup():
    context = ConversationContext(
        session_id="s1",
        entity_types=["Appointment"],
        metrics=["appointment_count"],
        dimensions=["status"],
        analysis_type="distribution",
        last_question="2025 ocak ayinda randevu durumlarina gore dagilimi goster",
        query_plan_snapshot={"dimensions": ["RandevuDurumu"], "metrics": ["appointment_count"]},
    )

    result = ContextResolver().resolve(
        "Bunu 2025 yili boyunca aylik trend olarak goster, tum durumlar dahil.",
        context,
    )

    assert result.follow_up_detected is True
    assert "pronoun_reference" in result.follow_up_signals
    assert result.context_applied is True


def test_bu_kapsamda_and_bu_sonuc_are_context_references():
    context = ConversationContext(
        session_id="s1",
        entity_types=["Appointment"],
        metrics=["appointment_count"],
        dimensions=["gender"],
        analysis_type="distribution",
        last_question="2025 ocak ayinda randevulari kadin erkek olarak bol",
        query_plan_snapshot={
            "dimensions": ["CinsiyetId"],
            "metrics": ["appointment_count"],
        },
    )

    scoped = ContextResolver().resolve("Bu kapsamda gerceklesme oranini ekle.", context)
    assert scoped.follow_up_detected is True
    assert "pronoun_reference" in scoped.follow_up_signals
    assert scoped.context_applied is True

    sql = ContextResolver().resolve("Bu sonucun SQL sorgusunu da goster.", context)
    assert sql.follow_up_detected is True
    assert "output_action_followup" in sql.follow_up_signals
    assert "2025 ocak ayinda" in sql.resolved_question


def test_ayni_kapsami_is_a_context_reference():
    context = ConversationContext(
        session_id="s1",
        entity_types=["Appointment"],
        metrics=["appointment_count"],
        dimensions=[],
        analysis_type="time_trend",
        date_expression="2025 ilk ceyrekte",
        last_question="2025 ilk ceyrekte aylik randevu trendini grafik olarak goster",
        query_plan_snapshot={
            "dimensions": [],
            "metrics": ["monthly_appointment_count"],
            "grouping_granularity": "month",
        },
    )

    result = ContextResolver().resolve(
        "Simdi ayni kapsami kadin erkek olarak kir.",
        context,
    )

    assert result.follow_up_detected is True
    assert "pronoun_reference" in result.follow_up_signals
    assert result.context_applied is True
    assert result.inherited["date"] == "2025 ilk ceyrekte"


def test_month_year_comparison_followup_replays_previous_analysis():
    context = ConversationContext(
        session_id="s1",
        entity_types=["Appointment"],
        metrics=["appointment_count"],
        dimensions=["department"],
        analysis_type="distribution",
        last_question="2025 mayis ayinda bolumlere gore toplam randevu sayisini goster",
        query_plan_snapshot={
            "dimensions": ["GenelRandevuBolumAdi"],
            "metrics": ["appointment_count"],
        },
    )

    result = ContextResolver().resolve("Haziran 2025 ile kiyasla.", context)

    assert result.follow_up_detected is True
    assert "comparison_followup" in result.follow_up_signals
    assert result.context_applied is True
    assert "2025 mayis ayinda" in result.resolved_question
    assert "haziran 2025 ile kiyasla" in result.resolved_question.lower()


def test_query_analyzer_resolves_year_quarter_before_bare_year():
    analysis = QueryAnalyzer().analyze(
        "2025 ilk ceyrekte aylik randevu trendini grafik olarak goster"
    )

    assert len(analysis.detected_dates) == 1
    detected = analysis.detected_dates[0]
    assert detected.start_date.isoformat() == "2025-01-01"
    assert detected.end_date.isoformat() == "2025-03-31"
    assert detected.granularity == "quarter"


def test_query_analyzer_resolves_possessive_quarter_form():
    """'yilinin ilk ceyreginde' consonant-mutates ceyrek -> ceyreg (k->g
    softening before a vowel-initial suffix, live UI 2026-07-28: this
    phrasing silently fell back to a full-year range, no quarter filter at
    all)."""
    analysis = QueryAnalyzer().analyze(
        "2025 yilinin ilk ceyreginde bolum bazinda randevu sayilarini tablo olarak goster"
    )

    assert len(analysis.detected_dates) == 1
    detected = analysis.detected_dates[0]
    assert detected.start_date.isoformat() == "2025-01-01"
    assert detected.end_date.isoformat() == "2025-03-31"
    assert detected.granularity == "quarter"


def test_planner_extracts_aggregate_threshold_variants():
    """Numeric aggregate thresholds ('200'den az', '500'den fazla', 'en az
    1000', '100'ün altında') are captured as a HAVING-style bound, not
    silently dropped (live UI 2026-07-28: '200'den az' returned all 62
    departments, the threshold never applied)."""
    analyzer = QueryAnalyzer()
    planner = QueryPlanner()
    view = ViewMetadata(name="dbo.vw_RandevuRaporu", columns=[])

    cases = {
        "2025 mayis ayinda bolum bazinda 200 den az randevusu olan bolumler": ("<", 200),
        "2025 mayis ayinda bolum bazinda 500 den fazla randevusu olan bolumler": (">", 500),
        "2025 mayis ayinda en az 1000 randevusu olan bolumler": (">=", 1000),
        "2025 mayis ayinda en fazla 300 randevusu olan bolumler": ("<=", 300),
        "2025 mayis ayinda 100 un altinda randevusu olan bolumler": ("<", 100),
        "2025 mayis ayinda 800 in uzerinde randevusu olan bolumler": (">", 800),
    }
    for question, (operator, value) in cases.items():
        analysis = analyzer.analyze(question)
        plan = planner.build_plan(question, analysis, [], views=[view])
        assert plan.aggregate_threshold is not None, question
        assert plan.aggregate_threshold.operator == operator, question
        assert plan.aggregate_threshold.value == value, question


def test_en_az_threshold_does_not_double_as_a_row_limit():
    """'en az 500 randevusu olan doktorlar' means at-least-500 (a HAVING), not
    the TOP 500 rows — the same number must not become a spurious row limit
    (live UI 2026-07-28)."""
    analyzer = QueryAnalyzer()
    planner = QueryPlanner()
    view = ViewMetadata(name="dbo.vw_RandevuRaporu", columns=[])
    question = "2023 yilinda en az 500 randevusu olan doktorlari randevu sayisina gore sirala"
    analysis = analyzer.analyze(question)
    plan = planner.build_plan(question, analysis, [], views=[view])
    assert plan.aggregate_threshold is not None
    assert plan.aggregate_threshold.operator == ">="
    assert plan.aggregate_threshold.value == 500
    assert plan.limit is None
    built = DeterministicSQLBuilder().build(plan)
    assert isinstance(built, DeterministicSQL)
    assert "HAVING COUNT(*) >= 500" in built.sql
    assert "TOP (500)" not in built.sql


def test_daily_average_is_a_scalar_not_a_per_day_series():
    """'günlük ortalama randevu sayısı' averages over days in its own formula —
    it must NOT also GROUP BY day (which collapses each group to one date and
    turns the average into that day's raw count; live UI 2026-07-28)."""
    analyzer = QueryAnalyzer()
    planner = QueryPlanner()
    view = ViewMetadata(name="dbo.vw_RandevuRaporu", columns=[])
    question = "2024 yilinda gunluk ortalama randevu sayisi nedir"
    analysis = analyzer.analyze(question)
    plan = planner.build_plan(question, analysis, [], views=[view])
    assert plan.grouping_granularity is None
    built = DeterministicSQLBuilder().build(plan)
    assert isinstance(built, DeterministicSQL)
    assert "GROUP BY" not in built.sql.upper()
    # A genuine daily SERIES ("günlük randevu sayısı trendi") must still bucket.
    trend_q = "2024 yilinda gunluk randevu sayisi trendini goster"
    trend_plan = planner.build_plan(trend_q, analyzer.analyze(trend_q), [], views=[view])
    assert trend_plan.grouping_granularity == "day"


def test_query_analyzer_detects_half_year_and_month_ranges():
    """'ilk/ikinci/son yarı' and 'Ocak-Haziran arası' are real date ranges, not
    a whole year or a single month (live UI 2026-07-28)."""
    analyzer = QueryAnalyzer()
    cases = {
        "2024 Ocak-Haziran arasi aylik gelmeme orani trendini goster": ("2024-01-01", "2024-06-30"),
        "2024 yilinin ilk yarisinda toplam randevu": ("2024-01-01", "2024-06-30"),
        "2023 ikinci yarisinda toplam randevu": ("2023-07-01", "2023-12-31"),
        "2024 son yarisinda bolum bazinda randevu": ("2024-07-01", "2024-12-31"),
        "2024 Mart ile Agustos arasi randevu sayisi": ("2024-03-01", "2024-08-31"),
    }
    for question, (start, end) in cases.items():
        analysis = analyzer.analyze(question)
        assert len(analysis.detected_dates) == 1, question
        detected = analysis.detected_dates[0]
        assert detected.start_date.isoformat() == start, question
        assert detected.end_date.isoformat() == end, question


def test_aggregate_threshold_renders_as_having_on_the_group_aggregate():
    analyzer = QueryAnalyzer()
    planner = QueryPlanner()
    view = ViewMetadata(name="dbo.vw_RandevuRaporu", columns=[])
    question = "2025 mayis ayinda bolum bazinda 200 den az randevusu olan bolumler"
    analysis = analyzer.analyze(question)
    plan = planner.build_plan(question, analysis, [], views=[view])

    built = DeterministicSQLBuilder().build(plan)
    assert isinstance(built, DeterministicSQL)
    assert "HAVING COUNT(*) < 200" in built.sql
    # A row-level WHERE would compare the raw column, not the group total.
    assert "GROUP BY" in built.sql
    assert PlanComplianceValidator().check(built.sql, plan).compliant


def test_aggregate_threshold_ignored_without_a_group_by():
    """A threshold phrase with no dimension has no aggregate to bound — it must
    not leak a HAVING into an ungrouped scalar count."""
    analyzer = QueryAnalyzer()
    planner = QueryPlanner()
    view = ViewMetadata(name="dbo.vw_RandevuRaporu", columns=[])
    question = "2025 mayis ayinda 200 den az randevu"
    analysis = analyzer.analyze(question)
    plan = planner.build_plan(question, analysis, [], views=[view])
    built = DeterministicSQLBuilder().build(plan)
    if isinstance(built, DeterministicSQL):
        assert "HAVING" not in built.sql.upper()


@pytest.mark.asyncio
async def test_threshold_followup_reattaches_to_prior_grouped_table():
    """The Chain-A live scenario: a grouped department table, then a chart
    follow-up, then 'tabloda 200'den az randevusu olan bölümleri göster'. The
    threshold must reattach to the inherited GROUP BY as a HAVING and keep the
    prior date scope, not return every group (live UI 2026-07-28)."""
    chain = _Chain()
    first, _ = await chain.turn(
        "2025 yilinin ilk ceyreginde bolum bazinda randevu sayilarini tablo olarak goster"
    )
    assert first.dimensions == ["GenelRandevuBolumAdi"]
    assert _date(first) == ("2025-01-01", "2025-03-31")

    await chain.turn("bunu grafik olarak goster")

    third, resolution = await chain.turn(
        "tabloda 200 den az randevusu olan bolumleri goster"
    )
    assert resolution.follow_up_detected is True
    assert third.aggregate_threshold is not None
    assert third.aggregate_threshold.operator == "<"
    assert third.aggregate_threshold.value == 200
    # Prior Q1 scope survives the intervening chart turn.
    assert _date(third) == ("2025-01-01", "2025-03-31")

    built = DeterministicSQLBuilder().build(third)
    assert isinstance(built, DeterministicSQL)
    assert "HAVING COUNT(*) < 200" in built.sql


@pytest.mark.asyncio
async def test_bunu_monthly_trend_after_status_distribution_clears_status_dimension():
    chain = _Chain()
    first, _ = await chain.turn(
        "Ayni Ocak 2025 kapsaminda tum randevu durumlarina gore dagilimi goster."
    )
    assert first.dimensions == ["RandevuDurumu"]
    assert first.metrics == ["appointment_count"]
    assert _date(first) == ("2025-01-01", "2025-01-31")

    second, resolution = await chain.turn(
        "Bunu 2025 yili boyunca aylik trend olarak goster, tum durumlar dahil."
    )

    assert resolution.follow_up_detected is True
    assert second.grouping_granularity == "month"
    assert second.dimensions == []
    assert second.metrics
    assert _date(second) == ("2025-01-01", "2025-12-31")

    built = DeterministicSQLBuilder().build(second)
    assert isinstance(built, DeterministicSQL)
    assert "GROUP BY RandevuDurumu" not in built.sql
    assert "DATEFROMPARTS(YEAR(BaslangicTarihi), MONTH(BaslangicTarihi), 1)" in built.sql


@pytest.mark.asyncio
async def test_metric_addition_preserves_monthly_trend_bucket():
    chain = _Chain()
    first, _ = await chain.turn(
        "2025 ilk ceyrekte aylik randevu trendini grafik olarak goster."
    )
    assert first.analysis_type == "time_trend"
    assert first.grouping_granularity == "month"
    assert _date(first) == ("2025-01-01", "2025-03-31")

    second, resolution = await chain.turn("Buna gerceklesme oranini da ekle.")

    assert resolution.follow_up_detected is True
    assert second.grouping_granularity == "month"
    assert second.metrics == ["monthly_appointment_count", "completed_appointment_rate"]

    built = DeterministicSQLBuilder().build(second)
    assert isinstance(built, DeterministicSQL)
    assert "period_start" in built.sql
    assert "completed_appointment_rate" in built.sql
    assert "GROUP BY DATEFROMPARTS(YEAR(BaslangicTarihi), MONTH(BaslangicTarihi), 1)" in built.sql


@pytest.mark.asyncio
async def test_numeric_threshold_followup_keeps_previous_date_scope():
    """"Toplam randevu sayısının 50'den küçük olanları" has no pronoun, no
    "peki", and is too many content tokens to be elliptical - it fell
    through every follow-up signal and answered as a fully independent,
    UNSCOPED question, dropping the previous turn's "2025 ilk çeyrek" date
    filter entirely (2026-07-27, live UI testing). There is no grouped
    breakdown to apply the "<50" threshold to (the previous turn was a
    scalar total), so the accepted behavior is to at least keep the
    inherited date scope rather than silently fall back to an all-time
    total."""
    chain = _Chain()
    first, _ = await chain.turn(
        "2025 yilinin ilk uc ayinin toplam randevu sayisi kactir"
    )
    assert _date(first) == ("2025-01-01", "2025-03-31")

    second, resolution = await chain.turn(
        "Toplam randevu sayisinin 50 den kucuk olanlari"
    )
    assert resolution.follow_up_detected is True
    assert _date(second) == ("2025-01-01", "2025-03-31")


@pytest.mark.asyncio
async def test_month_year_comparison_followup_builds_period_comparison_plan():
    chain = _Chain()
    first, _ = await chain.turn(
        "2025 Mayis ayinda bolumlere gore toplam randevu sayisini goster."
    )
    assert first.dimensions == ["GenelRandevuBolumAdi"]
    assert _date(first) == ("2025-05-01", "2025-05-31")

    second, resolution = await chain.turn("Haziran 2025 ile kiyasla.")

    assert resolution.follow_up_detected is True
    assert second.analysis_type == "period_comparison"
    assert second.dimensions == []
    assert second.ranking is None
    assert second.order is None
    assert len(second.periods) == 2

    built = DeterministicSQLBuilder().build(second)
    assert isinstance(built, DeterministicSQL)
    compliance = PlanComplianceValidator().check(
        built.sql, second, built.expected_aliases, deterministic=True
    )
    assert compliance.compliant is True
    assert "percentage_change" in built.sql
    assert "WHERE (BaslangicTarihi >= '2025-06-01'" in built.sql
    assert "OR (BaslangicTarihi >= '2025-05-01'" in built.sql
    assert "AND BaslangicTarihi >= '2025-06-01'" not in built.sql


@pytest.mark.asyncio
async def test_yerine_replaces_retained_dimension_instead_of_adding_it():
    chain = _Chain()
    await chain.turn(
        "2025 Subat ayinda doktorlara gore en yuksek 10 randevu sayisini tablo olarak getir."
    )
    await chain.turn("Simdi ayni sorguyu sadece gelmeyen randevular icin uret.")

    third, resolution = await chain.turn("Sonucu doktor yerine hizmet bazinda grupla.")

    assert resolution.follow_up_detected is True
    assert third.dimensions == ["HizmetAdi"]
    assert third.metrics == ["appointment_count"]
    assert _date(third) == ("2025-02-01", "2025-02-28")


def test_sonucu_is_not_extracted_as_a_doctor_filter_candidate():
    assert extract_candidate_phrases("Sonucu doktor yerine hizmet bazinda grupla.") == {}


@pytest.mark.asyncio
async def test_bunlari_dimension_followup_keeps_session_context():
    chain = _Chain()
    first, _ = await chain.turn(
        "2025 yilinda randevu durumuna gore toplam randevu sayisini goster."
    )
    assert first.dimensions == ["RandevuDurumu"]
    assert _date(first) == ("2025-01-01", "2025-12-31")

    second, _ = await chain.turn("Sadece gerceklesenleri goster.")
    assert "RandevuDurumu = 'Gerçekleşti'" in second.extra_filters
    assert _date(second) == ("2025-01-01", "2025-12-31")

    third, resolution = await chain.turn(
        "Bunlari bolumlere gore ilk 5 olacak sekilde sirala."
    )

    assert resolution.follow_up_detected is True
    assert "pronoun_reference" in resolution.follow_up_signals
    assert third.dimensions == ["GenelRandevuBolumAdi"]
    assert third.metrics == ["appointment_count"]
    assert third.limit == 5
    assert "RandevuDurumu = 'Gerçekleşti'" in third.extra_filters
    assert _date(third) == ("2025-01-01", "2025-12-31")


@pytest.mark.asyncio
async def test_ayni_kapsami_dimension_followup_keeps_previous_date_scope():
    chain = _Chain()
    await chain.turn("2025 ilk ceyrekte aylik randevu trendini grafik olarak goster.")
    await chain.turn("Buna gerceklesme oranini da ekle.")

    third, resolution = await chain.turn("Simdi ayni kapsami kadin erkek olarak kir.")

    assert resolution.follow_up_detected is True
    assert "pronoun_reference" in resolution.follow_up_signals
    assert _date(third) == ("2025-01-01", "2025-03-31")
    assert third.dimensions == ["CinsiyetId"]


@pytest.mark.asyncio
async def test_ayni_tabloyu_status_filter_keeps_previous_table_shape_and_date():
    chain = _Chain()
    await chain.turn(
        "2025 Subat ayinda doktorlara gore en yuksek 10 randevu sayisini tablo olarak getir."
    )
    await chain.turn("Sonucu doktor yerine hizmet bazinda grupla.")

    third, resolution = await chain.turn("Sadece gelmeyen randevular icin ayni tabloyu goster.")

    assert resolution.follow_up_detected is True
    assert "pronoun_reference" in resolution.follow_up_signals
    assert len(third.date_filters) == 1
    assert _date(third) == ("2025-02-01", "2025-02-28")
    assert third.dimensions == ["HizmetAdi"]
    assert third.metrics == ["appointment_count"]
    assert "RandevuDurumu = 'Gelmedi'" in third.extra_filters

    built = DeterministicSQLBuilder().build(third)
    assert isinstance(built, DeterministicSQL)
    assert "GROUP BY HizmetAdi" in built.sql
    assert "BaslangicTarihi >= '2025-02-01'" in built.sql
    assert "RandevuDurumu = N'Gelmedi'" in built.sql
    assert "SELECT Id" not in built.sql


@pytest.mark.asyncio
async def test_dimension_followup_after_period_comparison_drops_fixed_comparison_shape():
    chain = _Chain()
    await chain.turn("2025 Mayis ayinda bolumlere gore toplam randevu sayisini goster.")
    await chain.turn("Haziran 2025 ile kiyasla.")

    third, resolution = await chain.turn("Simdi ayni kapsami sube bazinda kir.")

    assert resolution.follow_up_detected is True
    assert third.analysis_type not in {
        "period_comparison",
        "baseline_comparison",
        "adaptive_time_comparison",
        "percentage_change",
    }
    assert third.periods == []
    assert third.dimensions == ["SubeAdi"]
    assert len(third.date_filters) == 1
    assert _date(third) == ("2025-05-01", "2025-05-31")

    built = DeterministicSQLBuilder().build(third)
    assert isinstance(built, DeterministicSQL)
    compliance = PlanComplianceValidator().check(
        built.sql, third, built.expected_aliases, deterministic=True
    )
    assert compliance.compliant is True
    assert "SubeAdi AS SubeAdi" in built.sql


@pytest.mark.asyncio
async def test_sql_output_followup_after_period_comparison_keeps_comparison_plan():
    chain = _Chain()
    await chain.turn("2025 Mayis ayinda bolumlere gore toplam randevu sayisini goster.")
    await chain.turn("Haziran 2025 ile kiyasla.")
    await chain.turn("Bu farki yuzde olarak da ozetle.")

    fourth, resolution = await chain.turn("Bu sonucun SQL sorgusunu goster.")

    assert resolution.follow_up_detected is True
    assert "output_action_followup" in resolution.follow_up_signals
    assert fourth.analysis_type == "period_comparison"
    assert len(fourth.periods) == 2

    built = DeterministicSQLBuilder().build(fourth)
    assert isinstance(built, DeterministicSQL)
    compliance = PlanComplianceValidator().check(
        built.sql, fourth, built.expected_aliases, deterministic=True
    )
    assert compliance.compliant is True
