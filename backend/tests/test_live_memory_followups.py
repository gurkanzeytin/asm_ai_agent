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
from app.planning.compliance import PlanComplianceValidator
from app.planning.models import QueryPlan
from app.planning.planner import QueryPlanner
from app.planning.value_resolver import extract_candidate_phrases, resolve_value
from app.services.deterministic_sql_builder import (
    DeterministicSQL,
    DeterministicSQLBuilder,
)
from app.services.query_analyzer import QueryAnalyzer


class _GroundedResolver:
    async def resolve(self, field_name: str, phrase: str):
        candidates_by_field = {
            "gender": ["E", "K", "D"],
            "department": [
                "Kardiyoloji",
                "Radyoloji",
                "Nöroloji",
                "Ortopedi",
                "Çocuk Sağlığı",
            ],
        }
        candidates = candidates_by_field.get(field_name, [])
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


@pytest.mark.asyncio
async def test_appointments_per_patient_average_survives_department_ranking_followup():
    chain = _Chain()

    first, _ = await chain.turn("2025 hasta basina ortalama randevu adedi nedir")
    assert first.analysis_type == "repeat_behavior"
    assert first.metrics == ["appointments_per_patient"]

    first_sql = DeterministicSQLBuilder().build(first)
    assert isinstance(first_sql, DeterministicSQL)
    assert "AS appointments_per_patient" in first_sql.sql

    second, _ = await chain.turn(
        "Bu ortalamayi bolumlere gore en yuksek 10 bolum olarak listele."
    )

    assert second.metrics == ["appointments_per_patient"]
    assert second.dimensions == ["GenelRandevuBolumAdi"]
    assert second.limit == 10
    assert _date(second) == ("2025-01-01", "2025-12-31")

    second_sql = DeterministicSQLBuilder().build(second)
    assert isinstance(second_sql, DeterministicSQL)
    assert "AS appointments_per_patient" in second_sql.sql
    assert "CROSS APPLY" in second_sql.sql
    assert "dept_atomic.value" in second_sql.sql
    assert "COUNT(*) AS appointment_count" not in second_sql.sql


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


@pytest.mark.parametrize(
    ("question", "operator", "value"),
    [
        # Turkish thousands separator: normalization turns "1.000" into "1 000",
        # which used to be read as 0 (only the trailing "000" was captured);
        # and a bare "2024 500" must not be merged into 2024500 (robustness
        # probe round 7, 2026-07-29).
        ("2024 bolum bazinda 1.000 den fazla randevusu olan bolumler", ">", 1000),
        ("2024 bolum bazinda 10.000 den az randevusu olan bolumler", "<", 10000),
        ("2024 bolum bazinda 1.000.000 den fazla randevusu olan bolumler", ">", 1000000),
        ("2024 en az 2.500 randevusu olan doktorlar", ">=", 2500),
        ("2024 bolum bazinda 500 den fazla randevu", ">", 500),
    ],
)
def test_aggregate_threshold_handles_thousands_separator(question, operator, value):
    view = ViewMetadata(name="dbo.vw_RandevuRaporu", columns=[])
    plan = QueryPlanner().build_plan(question, QueryAnalyzer().analyze(question), [], views=[view])
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
async def test_ayni_veriyi_followup_keeps_date_scope_and_takes_new_dimension():
    """'2024 randevuları bölüme kır' then 'Aynı veriyi doktor bazında kırılım
    olarak getir': "aynı veriyi" is a reference to the previous answer, so the
    2024 scope must survive while the NEW dimension (doctor) replaces the old
    one. Before this, the phrase was not a follow-up signal at all, the date
    filter was dropped, and the answer covered ALL time (1.683.876 rows in the
    UI instead of 2024's) — and the corruption then cascaded to every later
    turn in the session (Codex live UI testing, 2026-07-31)."""
    chain = _Chain()
    first, _ = await chain.turn("2024 randevularini bolume kir")
    assert first.dimensions == ["GenelRandevuBolumAdi"]
    assert _date(first) == ("2024-01-01", "2024-12-31")

    second, resolution = await chain.turn(
        "Ayni veriyi doktor bazinda kirilim olarak getir"
    )
    assert resolution.follow_up_detected is True
    assert second.dimensions == ["DoktorId"]
    assert _date(second) == ("2024-01-01", "2024-12-31")

    # The scope keeps surviving further breakdown edits in the same session.
    third, third_resolution = await chain.turn("Sube bazinda kirilimi da ekle")
    assert third_resolution.follow_up_detected is True
    assert _date(third) == ("2024-01-01", "2024-12-31")


@pytest.mark.asyncio
async def test_ay_kiriliminda_followup_buckets_by_month():
    """'Bunu ay kırılımında göster' must bucket by month and drop the previous
    categorical dimension. "<birim> kırılımı" was matched for no granularity at
    all, so the answer silently repeated the earlier randevu-tipi breakdown
    (Codex live UI testing, 2026-07-31)."""
    chain = _Chain()
    await chain.turn("2024 randevularini bolume kir")
    await chain.turn("Randevu tipine gore dagilimi goster")

    plan, resolution = await chain.turn("Bunu ay kiriliminda goster")
    assert resolution.follow_up_detected is True
    assert plan.grouping_granularity == "month"
    assert plan.dimensions == []
    assert _date(plan) == ("2024-01-01", "2024-12-31")


def test_same_day_wording_is_not_a_context_reference():
    """Guard for the fix above: 'aynı gün' is a DOMAIN term (same-day
    appointments), not a reference to the previous turn — it must never pull a
    stale date scope into an independent question."""
    from app.context.extractor import ContextExtractor

    signals = ContextExtractor().extract("ayni gun randevusu olan hastalar")
    assert signals.pronouns == []


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
    # A per-department view compared against another period stays per-department:
    # the inherited GenelRandevuBolumAdi dimension survives into the comparison,
    # so the answer is a per-department May-vs-June breakdown rather than a
    # single two-period total (2026-07-29, live UI month-comparison findings).
    assert second.dimensions == ["GenelRandevuBolumAdi"]
    assert second.ranking is None
    assert second.order is None
    assert len(second.periods) == 2

    built = DeterministicSQLBuilder().build(second)
    assert isinstance(built, DeterministicSQL)
    compliance = PlanComplianceValidator().check(
        built.sql, second, built.expected_aliases, deterministic=True
    )
    assert compliance.compliant is True
    # Grouped breakdown: one row per department with both period counts and the
    # signed difference, ordered by |difference|.
    assert "current_period_count" in built.sql
    assert "baseline_period_count" in built.sql
    assert "absolute_change" in built.sql
    assert "GROUP BY" in built.sql
    # Both periods still live in the WHERE (parenthesized disjunction), and the
    # baseline window is never AND-ed onto the current one.
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
async def test_ranking_chain_preserves_dimension_through_resort_replay_and_format():
    """A department ranking must survive a re-sort ("Şimdi en düşük ... göre
    sırala"), a same-analysis replay for a new year ("Aynı analizi 2024 için
    yap"), and a format switch ("Tablo olarak göster") — none of these may
    collapse the breakdown into a single KPI or drop it as out-of-scope
    (2026-07-29, live UI multi-turn follow-up findings)."""
    chain = _Chain()
    first, _ = await chain.turn(
        "2025 bolum bazinda gelmeme oranina gore en yuksek 10 bolumu goster"
    )
    assert first.dimensions == ["GenelRandevuBolumAdi"]
    assert first.limit == 10

    second, r2 = await chain.turn("Ilk 5 ile sinirla")
    assert r2.follow_up_detected is True
    assert second.dimensions == ["GenelRandevuBolumAdi"]
    assert second.limit == 5

    # Re-sort by a NEW metric with no dimension named — the breakdown continues.
    third, r3 = await chain.turn("Simdi en dusuk gerceklesme oranina gore sirala")
    assert r3.follow_up_detected is True
    assert "resort_continuation" in r3.follow_up_signals
    assert third.dimensions == ["GenelRandevuBolumAdi"]
    assert third.metrics == ["completed_appointment_rate"]
    assert third.limit == 5


    # Same analysis, new year — swaps the date, keeps dimension/metric/limit.
    fourth, r4 = await chain.turn("Ayni analizi 2024 icin yap")
    assert r4.follow_up_detected is True
    assert "same_analysis_replay" in r4.follow_up_signals
    assert fourth.dimensions == ["GenelRandevuBolumAdi"]
    assert fourth.metrics == ["completed_appointment_rate"]
    assert fourth.limit == 5
    assert _date(fourth) == ("2024-01-01", "2024-12-31")

    # Format-only follow-up must not drop the analysis.
    fifth, r5 = await chain.turn("Tablo olarak goster")
    assert r5.follow_up_detected is True
    assert fifth.dimensions == ["GenelRandevuBolumAdi"]
    assert fifth.metrics == ["completed_appointment_rate"]
    assert _date(fifth) == ("2024-01-01", "2024-12-31")


@pytest.mark.asyncio
async def test_ascending_resort_followup_keeps_grouping_threshold_and_date():
    chain = _Chain()
    first, _ = await chain.turn(
        "2025 Mayis ayinda bolum bazinda randevu sayisini goster."
    )
    assert first.dimensions == ["GenelRandevuBolumAdi"]
    assert _date(first) == ("2025-05-01", "2025-05-31")

    second, r2 = await chain.turn("200'den az olanlari goster.")
    assert r2.follow_up_detected is True
    assert second.aggregate_threshold is not None
    assert second.aggregate_threshold.operator == "<"
    assert second.aggregate_threshold.value == 200

    third, r3 = await chain.turn("En dusukten yuksege sirala.")
    assert r3.follow_up_detected is True
    assert third.dimensions == ["GenelRandevuBolumAdi"]
    assert _date(third) == ("2025-05-01", "2025-05-31")
    assert third.aggregate_threshold is not None
    assert third.ranking == "ASC"
    assert third.order == "ASC"

    built = DeterministicSQLBuilder().build(third)
    assert isinstance(built, DeterministicSQL)
    assert "HAVING COUNT(*) < 200" in built.sql
    assert "ORDER BY appointment_count ASC" in built.sql


@pytest.mark.asyncio
async def test_department_exclusion_followup_is_not_saved_as_positive_department():
    chain = _Chain()
    await chain.turn("2025 Mayis ayinda bolum bazinda randevu sayisini goster.")
    await chain.turn("En dusukten yuksege sirala.")

    excluded, r3 = await chain.turn("Kardiyoloji haric tut.")
    assert r3.follow_up_detected is True
    assert excluded.department_filter is None
    assert excluded.excluded_departments == ["Kardiyoloji"]

    branch, r4 = await chain.turn("Ayni sonucu sube bazinda kir.")
    assert r4.follow_up_detected is True
    assert branch.department_filter is None
    assert branch.excluded_departments == ["Kardiyoloji"]
    assert branch.dimensions == ["SubeAdi"]

    built = DeterministicSQLBuilder().build(branch)
    assert isinstance(built, DeterministicSQL)
    assert "NOT (" in built.sql and "Kardiyoloji" in built.sql
    assert "value = N'Kardiyoloji'" not in built.sql


@pytest.mark.asyncio
async def test_department_filter_followup_preserves_period_comparison_scope():
    chain = _Chain()
    first, _ = await chain.turn(
        "2025 ve 2026 toplam randevu sayilarini karsilastir; farki ve yuzde degisimi de hesapla."
    )
    assert len(first.date_filters) == 2

    second, resolution = await chain.turn(
        "Bu karsilastirmayi sadece Kardiyoloji bolumu icin yap."
    )

    assert resolution.follow_up_detected is True
    assert second.department_filter == "Kardiyoloji"
    assert len(second.date_filters) == 2
    built = DeterministicSQLBuilder().build(second)
    assert isinstance(built, DeterministicSQL)
    assert "Kardiyoloji" in built.sql
    assert "NULLIF" in built.sql


@pytest.mark.asyncio
async def test_month_ranking_followup_keeps_department_and_limits_top_five():
    chain = _Chain()
    await chain.turn(
        "2025 ve 2026 toplam randevu sayilarini karsilastir; farki ve yuzde degisimi de hesapla."
    )
    await chain.turn("Bu karsilastirmayi sadece Kardiyoloji bolumu icin yap.")

    third, resolution = await chain.turn(
        "Son cevaptaki Kardiyoloji filtresini koru; 2025 aylarini en yuksekten "
        "dusuge sirala ve sadece ilk 5 ayi goster."
    )

    assert resolution.follow_up_detected is True
    assert third.department_filter == "Kardiyoloji"
    assert third.grouping_granularity == "month"
    assert third.ranking == "DESC"
    assert third.limit == 5
    assert _date(third) == ("2025-01-01", "2025-12-31")
    built = DeterministicSQLBuilder().build(third)
    assert isinstance(built, DeterministicSQL)
    assert "TOP (5)" in built.sql
    assert "DATEFROMPARTS(YEAR(BaslangicTarihi), MONTH(BaslangicTarihi), 1)" in built.sql
    assert "Kardiyoloji" in built.sql


@pytest.mark.asyncio
async def test_share_of_total_followup_renders_percentage_column():
    chain = _Chain()
    first, _ = await chain.turn(
        "2025 yilinda bolumlere gore randevu sayilarini en yuksek 10 bolum olarak listele."
    )
    assert first.dimensions == ["GenelRandevuBolumAdi"]
    assert first.limit == 10

    second, resolution = await chain.turn(
        "Bu ilk 10 bolumun 2025 toplam randevu icindeki pay yuzdesini de ekle."
    )

    assert resolution.follow_up_detected is True
    assert second.dimensions == ["GenelRandevuBolumAdi"]
    assert second.limit == 10
    assert second.analysis_type == "distribution"
    assert "share_of_total: appointment_count" in second.derived_calculations
    built = DeterministicSQLBuilder().build(second)
    assert isinstance(built, DeterministicSQL)
    assert "pay_yuzdesi" in built.sql
    assert "NULLIF" in built.sql


def test_three_named_month_comparison_builds_multi_period_breakdown():
    analyzer = QueryAnalyzer()
    planner = QueryPlanner()
    view = ViewMetadata(name="dbo.vw_RandevuRaporu", columns=[])
    question = "2025 yilinda Ocak, Subat ve Mart aylarini toplam randevu acisindan karsilastir."

    plan = planner.build_plan(question, analyzer.analyze(question), [], views=[view])

    assert len(plan.date_filters) == 3
    assert plan.analysis_type == "period_comparison"
    built = DeterministicSQLBuilder().build(plan)
    assert isinstance(built, DeterministicSQL)
    assert "period_label" in built.sql
    assert "UNION ALL" in built.sql
    assert "2025-01-01" in built.sql
    assert "2025-02-01" in built.sql
    assert "2025-03-01" in built.sql
    compliance = PlanComplianceValidator().check(
        built.sql, plan, built.expected_aliases, deterministic=True
    )
    assert compliance.compliant is True


@pytest.mark.asyncio
async def test_pasta_grafiginde_goster_is_a_chart_followup_not_out_of_scope():
    """A chart-type presentation follow-up in any Turkish locative form
    ("Pasta grafiğinde göster", not just "grafikte") re-renders the prior
    result instead of falling through to OUT_OF_SCOPE (2026-07-29, live UI on
    an age-group breakdown)."""
    chain = _Chain()
    first, _ = await chain.turn("2025 yas grubuna gore randevu dagilimini goster")
    assert first.dimensions  # a real breakdown was produced

    second, resolution = await chain.turn("Pasta grafiginde goster")
    assert resolution.follow_up_detected is True
    assert "output_action_followup" in resolution.follow_up_signals
    # The prior analysis is preserved, not collapsed or dropped.
    assert second.dimensions == first.dimensions
    assert second.answerable is not False


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


@pytest.mark.asyncio
async def test_relationship_metric_survives_breakdown_followup():
    chain = _Chain()

    first, _ = await chain.turn(
        "2024 yilinda ayni gun icinde ayni hasta birden fazla hizmet almis mi?"
    )
    assert first.analysis_type == "repeat_behavior"
    assert first.metrics == ["same_day_multi_service_patient_count"]
    assert first.dimensions == []

    second, resolution = await chain.turn("Bunu subelere gore kir.")

    assert resolution.follow_up_detected is True
    assert second.analysis_type == "repeat_behavior"
    assert second.metrics == ["same_day_multi_service_patient_count"]
    assert second.dimensions == ["SubeAdi"]
    assert second.projection == []
    built = DeterministicSQLBuilder().build(second)
    assert isinstance(built, DeterministicSQL)
    assert "patient_day_services AS" in built.sql
    assert "JOIN qualifying_patient_days" in built.sql
    assert "GROUP BY SubeAdi" in built.sql
    compliance = PlanComplianceValidator().check(
        built.sql, second, built.expected_aliases, deterministic=True
    )
    assert compliance.compliant is True


@pytest.mark.asyncio
async def test_cross_branch_relationship_can_be_broken_down_by_service_in_session():
    chain = _Chain()

    first, _ = await chain.turn(
        "2024 yilinda hangi hastalar farkli subelerde tekrar tekrar islem gormus?"
    )
    assert first.analysis_type == "repeat_behavior"
    assert first.metrics == ["cross_branch_repeat_patient_count"]
    assert first.dimensions == []

    second, resolution = await chain.turn("Bunu hizmetlere gore dagit.")

    assert resolution.follow_up_detected is True
    assert second.analysis_type == "repeat_behavior"
    assert second.metrics == ["cross_branch_repeat_patient_count"]
    assert second.dimensions == ["HizmetAdi"]
    assert second.projection == []
    built = DeterministicSQLBuilder().build(second)
    assert isinstance(built, DeterministicSQL)
    assert "JOIN cross_branch_patients" in built.sql
    assert "GROUP BY v.HizmetAdi" in built.sql
    compliance = PlanComplianceValidator().check(
        built.sql, second, built.expected_aliases, deterministic=True
    )
    assert compliance.compliant is True


@pytest.mark.asyncio
async def test_same_day_multi_service_breakdown_uses_aggregated_patient_day_cte():
    chain = _Chain()

    first, _ = await chain.turn(
        "2023 yilinda ayni gun icinde ayni hasta birden fazla hizmet almis mi?"
    )
    assert first.analysis_type == "repeat_behavior"
    assert first.metrics == ["same_day_multi_service_patient_count"]
    assert first.dimensions == []

    second, resolution = await chain.turn("Bunu hizmetlere gore dagit.")

    assert resolution.follow_up_detected is True
    assert second.analysis_type == "repeat_behavior"
    assert second.metrics == ["same_day_multi_service_patient_count"]
    assert second.dimensions == ["HizmetAdi"]
    assert second.projection == []
    assert _date(second) == ("2023-01-01", "2023-12-31")
    built = DeterministicSQLBuilder().build(second)
    assert isinstance(built, DeterministicSQL)
    assert "patient_day_services AS" in built.sql
    assert "qualified_services AS" in built.sql
    assert "COUNT(*) OVER (PARTITION BY HastaId, service_day) AS value_count" in built.sql
    assert "JOIN qualifying_patient_days" not in built.sql
    assert "FROM dbo.vw_RandevuRaporu v" not in built.sql
    assert "COUNT(DISTINCT CONCAT" not in built.sql
    assert "GROUP BY HizmetAdi" in built.sql
    compliance = PlanComplianceValidator().check(
        built.sql, second, built.expected_aliases, deterministic=True
    )
    assert compliance.compliant is True


@pytest.mark.asyncio
async def test_same_day_multi_doctor_relationship_survives_branch_followup():
    chain = _Chain()

    first, _ = await chain.turn(
        "2024 yilinda ayni gun ayni hasta birden fazla doktorla islem gormus mu?"
    )
    assert first.analysis_type == "repeat_behavior"
    assert first.metrics == ["same_day_multi_doctor_patient_count"]
    assert first.dimensions == []

    second, resolution = await chain.turn("Bunu subelere gore kir.")

    assert resolution.follow_up_detected is True
    assert second.analysis_type == "repeat_behavior"
    assert second.metrics == ["same_day_multi_doctor_patient_count"]
    assert second.dimensions == ["SubeAdi"]
    assert second.projection == []
    assert _date(second) == ("2024-01-01", "2024-12-31")
    built = DeterministicSQLBuilder().build(second)
    assert isinstance(built, DeterministicSQL)
    assert "patient_day_doctors AS" in built.sql
    assert "COUNT(DISTINCT DoktorId) > 1" in built.sql
    assert "GROUP BY SubeAdi" in built.sql
    compliance = PlanComplianceValidator().check(
        built.sql, second, built.expected_aliases, deterministic=True
    )
    assert compliance.compliant is True


@pytest.mark.asyncio
async def test_patient_span_followups_keep_year_scope_and_top_patient_shape():
    chain = _Chain()

    first, _ = await chain.turn(
        "2024 yilinda bir hastanin ilk ve son randevusu arasinda kac gun gecmis?"
    )
    assert first.analysis_type == "repeat_behavior"
    assert first.metrics == ["patient_appointment_span_days"]
    assert _date(first) == ("2024-01-01", "2024-12-31")

    second, resolution = await chain.turn("Ortalama gun farkini goster.")
    assert resolution.follow_up_detected is True
    assert second.metrics == ["patient_appointment_span_days"]
    assert _date(second) == ("2024-01-01", "2024-12-31")

    third, resolution = await chain.turn("En yuksek farki olan 10 hastayi listele.")
    assert resolution.follow_up_detected is True
    assert "patient_span_ranking_followup" in resolution.follow_up_signals
    assert third.metrics == ["patient_appointment_span_days"]
    assert third.limit == 10
    assert _date(third) == ("2024-01-01", "2024-12-31")

    built = DeterministicSQLBuilder().build(third)
    assert isinstance(built, DeterministicSQL)
    assert "SELECT TOP (10) HastaId AS HastaId" in built.sql
    assert "BaslangicTarihi >= '2024-01-01'" in built.sql


@pytest.mark.asyncio
async def test_patient_overlap_breakdown_followup_keeps_both_years():
    chain = _Chain()

    first, _ = await chain.turn("Hem 2023 hem 2024 icinde islem goren hastalari say.")
    assert first.analysis_type == "repeat_behavior"
    assert first.metrics == ["multi_period_patient_overlap_count"]
    assert len(first.date_filters) == 2

    second, resolution = await chain.turn("Bu hastalari subelere gore kir.")

    assert resolution.follow_up_detected is True
    assert second.analysis_type == "repeat_behavior"
    assert second.metrics == ["multi_period_patient_overlap_count"]
    assert second.dimensions == ["SubeAdi"]
    assert len(second.date_filters) == 2
    built = DeterministicSQLBuilder().build(second)
    assert isinstance(built, DeterministicSQL)
    assert "overlap_patients AS" in built.sql
    assert ") OR (" in built.sql
    assert "GROUP BY v.SubeAdi" in built.sql
    compliance = PlanComplianceValidator().check(
        built.sql, second, built.expected_aliases, deterministic=True
    )
    assert compliance.compliant is True


@pytest.mark.asyncio
async def test_full_same_day_relationship_question_does_not_inherit_prior_breakdown():
    chain = _Chain()

    await chain.turn(
        "2024 yilinda hangi hastalar farkli subelerde tekrar tekrar islem gormus?"
    )
    prior_breakdown, _ = await chain.turn("Bunu hizmetlere gore dagit.")
    assert prior_breakdown.metrics == ["cross_branch_repeat_patient_count"]
    assert prior_breakdown.dimensions == ["HizmetAdi"]

    third, resolution = await chain.turn(
        "2024 yilinda ayni gun icinde ayni hasta birden fazla hizmet almis mi?"
    )

    assert "constraint_edit_followup" not in resolution.follow_up_signals
    assert resolution.context_applied is False
    assert third.analysis_type == "repeat_behavior"
    assert third.metrics == ["same_day_multi_service_patient_count"]
    assert third.dimensions == []
    built = DeterministicSQLBuilder().build(third)
    assert isinstance(built, DeterministicSQL)
    assert "JOIN qualifying_patient_days" not in built.sql
    assert "GROUP BY v.HizmetAdi" not in built.sql


@pytest.mark.asyncio
async def test_gender_value_filter_followup_preserves_analytical_shape():
    chain = _Chain()

    await chain.turn("2024 yilinda yas grubuna gore randevu sayisi nasil dagiliyor?")
    await chain.turn("Bunu cinsiyete gore kir.")
    await chain.turn("2023 icin ayni analizi yap.")

    fourth, resolution = await chain.turn("Kadin hastalar icin goster.")

    assert resolution.follow_up_detected is True
    assert "value_filter_followup" in resolution.follow_up_signals
    assert fourth.analysis_type != "list"
    assert fourth.metrics == ["appointment_count"]
    assert fourth.dimensions == ["CinsiyetId"]
    assert fourth.projection == ["CinsiyetId"]
    assert _date(fourth) == ("2023-01-01", "2023-12-31")
    assert fourth.resolved_filters["gender"].values == ["K"]
    built = DeterministicSQLBuilder().build(fourth)
    assert isinstance(built, DeterministicSQL)
    assert "SELECT Id" not in built.sql
    assert "CinsiyetId = N'K'" in built.sql
    compliance = PlanComplianceValidator().check(
        built.sql, fourth, built.expected_aliases, deterministic=True
    )
    assert compliance.compliant is True


@pytest.mark.asyncio
async def test_period_change_direction_followup_keeps_periods_and_dimension():
    chain = _Chain()

    first, _ = await chain.turn(
        "2024 Mayis-Haziran kapsaminda bolumlere gore randevu degisimini goster."
    )
    assert first.analysis_type == "period_comparison"
    assert first.dimensions == ["GenelRandevuBolumAdi"]
    assert len(first.periods) == 2

    second, resolution = await chain.turn("Azalanlari goster.")

    assert resolution.follow_up_detected is True
    assert second.analysis_type in {"period_comparison", "percentage_change"}
    assert second.dimensions == ["GenelRandevuBolumAdi"]
    assert len(second.periods) == 2
    assert "period_change_direction:decrease" in second.derived_calculations
    built = DeterministicSQLBuilder().build(second)
    assert isinstance(built, DeterministicSQL)
    assert "GROUP BY dept_atomic.value" in built.sql
    assert built.sql.rstrip().endswith("ASC;")


@pytest.mark.asyncio
async def test_period_direction_followup_after_top_increase_branch_reverses_direction():
    chain = _Chain()

    first, _ = await chain.turn(
        "2024 Mayis-Haziran kapsaminda en cok artan 5 sube hangisi?"
    )
    assert first.analysis_type == "period_comparison"
    assert first.dimensions == ["SubeAdi"]
    assert len(first.periods) == 2
    assert "period_change_direction:increase" in first.derived_calculations

    second, resolution = await chain.turn("Azalanlari goster.")

    assert "period_direction_followup" in resolution.follow_up_signals
    assert second.analysis_type == "period_comparison"
    assert second.dimensions == ["SubeAdi"]
    assert len(second.periods) == 2
    assert "period_change_direction:increase" not in second.derived_calculations
    assert "period_change_direction:decrease" in second.derived_calculations
    assert second.ranking == "ASC"
    assert second.order == "ASC"
    built = DeterministicSQLBuilder().build(second)
    assert isinstance(built, DeterministicSQL)
    compliance = PlanComplianceValidator().check(
        built.sql,
        second,
        built.expected_aliases,
        deterministic=True,
    )
    assert compliance.compliant is True, compliance.missing
    assert "GROUP BY SubeAdi" in built.sql
    assert built.sql.rstrip().endswith("ASC;")


@pytest.mark.asyncio
async def test_followup_phrasing_variants_are_consistent():
    """Robustness probe round 5 (2026-07-29): additive/output follow-up
    phrasings must behave the same as their already-working siblings.

    - "buna ... ekle" ADDS a metric (like "... da ekle" / "bir de ..."),
      it must not REPLACE — and "gerçekleşen" (which contains the substring
      'ekle') must NOT be mistaken for an additive marker.
    - "... de kır" ADDS a dimension (like "... da ayır" / "bir de ...").
    - "görsel olarak göster" is an output-change follow-up (like "grafik
      olarak göster"), inheriting the prior metric/dimension/date.
    """
    base = "2024 yilinda bolum bazinda randevu sayisi"

    chain = _Chain()
    await chain.turn(base)
    added, res = await chain.turn("buna gelmeme oranini ekle")
    assert res.follow_up_detected is True
    assert added.metrics == ["appointment_count", "no_show_rate"]

    chain = _Chain()
    await chain.turn(base)
    dim_added, _ = await chain.turn("cinsiyete gore de kir")
    assert set(dim_added.dimensions) == {"GenelRandevuBolumAdi", "CinsiyetId"}

    chain = _Chain()
    await chain.turn(base)
    visual, res = await chain.turn("gorsel olarak goster")
    assert res.follow_up_detected is True
    assert visual.metrics == ["appointment_count"]
    assert visual.dimensions == ["GenelRandevuBolumAdi"]


@pytest.mark.asyncio
async def test_gerceklesen_is_not_treated_as_additive_ekle_marker():
    """Regression guard: "gerçekleşen randevu sayısı" REPLACES the metric with
    completed_appointment_count — the 'ekle' substring inside 'gerçekleşen'
    must not make it additive."""
    chain = _Chain()
    await chain.turn("2025 ocak randevu sayisi")
    second, _ = await chain.turn("Gerceklesen randevu sayisi nedir")
    assert second.metrics == ["completed_appointment_count"]


def test_entity_ranking_over_first_months_has_no_spurious_month_grain():
    """'2025 ilk 6 ayında en yoğun 5 şube' ranks BRANCHES by their total, not
    by (month, branch): the 'ay' token belongs to the date scope ("first 6
    months"), not a request to bucket by month. Live UI 2026-07-30 returned
    top-5 (month, branch) rows all dominated by one branch."""
    analyzer = QueryAnalyzer()
    planner = QueryPlanner()
    view = ViewMetadata(name="dbo.vw_RandevuRaporu", columns=[])
    q = "2025 yilinin ilk 6 ayinda en yogun 5 subeyi randevu sayisina gore goster"
    plan = planner.build_plan(q, analyzer.analyze(q), [], views=[view])
    assert plan.grouping_granularity is None
    assert plan.dimensions  # ranks a real branch dimension
    assert plan.limit == 5
    # A genuine "rank the months themselves" question still buckets by month.
    months_q = "2024 yilinda en cok randevu alan ilk 3 ayi goster"
    months_plan = planner.build_plan(months_q, analyzer.analyze(months_q), [], views=[view])
    assert months_plan.grouping_granularity == "month"


@pytest.mark.asyncio
async def test_monthly_grain_dropped_when_followup_regroups_by_new_dimension():
    """After "aylara göre kır" (monthly), a NEW-topic department-ranking turn
    must group by department TOTALS — the inherited month grain must not leak
    a DÖNEM column + monthly_appointment_count. Live UI 2026-07-30 Bug A."""
    chain = _Chain()
    await chain.turn("2024 yilinda toplam kac randevu olusturuldu")
    monthly, _ = await chain.turn("Bunu aylara gore kir")
    assert monthly.grouping_granularity == "month"

    dept, _ = await chain.turn("2023 yilinda en cok randevu alan ilk 10 bolumu listele")
    assert dept.dimensions == ["GenelRandevuBolumAdi"]
    assert dept.grouping_granularity is None
    assert "monthly_appointment_count" not in dept.metrics
    assert _date(dept) == ("2023-01-01", "2023-12-31")


@pytest.mark.asyncio
async def test_explicit_ay_ay_degil_correction_drops_inherited_month_grain():
    """The explicit "ay ay değil ... bölüm başına toplam" correction must drop
    the inherited monthly grain instead of re-rendering the same monthly table.
    Live UI 2026-07-30 Bug A: the scope-reuse path ignored the negation."""
    chain = _Chain()
    await chain.turn("2024 yilinda toplam kac randevu olusturuldu")
    await chain.turn("Bunu aylara gore kir")
    corrected, _ = await chain.turn(
        "Hayir, ay ay degil. 2023 yilinin tamami icin bolum basina toplam "
        "randevu sayisini ver, en yuksek 10 bolum."
    )
    assert corrected.dimensions == ["GenelRandevuBolumAdi"]
    assert corrected.grouping_granularity is None
    assert "monthly_appointment_count" not in corrected.metrics


def test_multi_status_metrics_do_not_apply_a_global_status_where_filter():
    """'toplam, gerçekleşen ve gelmeyen randevu' asks for three status-
    differentiated counts, each its own SUM(CASE ...). The 'gerçekleşen' word
    must NOT also add a global RandevuDurumu='Gerçekleşti' WHERE filter — that
    excluded the rows the total/no-show columns need, making gerçekleşen ==
    toplam and gelmeyen == 0 for every department (live UI 2026-07-30)."""
    analyzer = QueryAnalyzer()
    planner = QueryPlanner()
    view = ViewMetadata(name="dbo.vw_RandevuRaporu", columns=[])
    q = (
        "2024 yilinda bolum bazinda toplam randevu, gerceklesen randevu ve "
        "gelmeyen randevu sayilarini goster"
    )
    plan = planner.build_plan(q, analyzer.analyze(q), [], views=[view])
    assert "completed_appointment_count" in plan.metrics
    assert "appointment_count" in plan.metrics
    assert "no_show_count" in plan.metrics

    built = DeterministicSQLBuilder().build(plan)
    assert isinstance(built, DeterministicSQL)
    where = built.sql.split("WHERE", 1)[1].split("GROUP BY")[0]
    assert "RandevuDurumu =" not in where  # status lives only in per-metric CASE
    assert built.sql.count("SUM(CASE WHEN RandevuDurumu") >= 2
    assert "COUNT(*) AS appointment_count" in built.sql


def test_single_status_metric_still_scopes_via_where():
    """Guard boundary: a lone 'gerçekleşen randevu' count (no other metric)
    still scopes the whole query via the WHERE filter — the multi-metric
    carve-out must not disarm the ordinary single-status case."""
    analyzer = QueryAnalyzer()
    planner = QueryPlanner()
    view = ViewMetadata(name="dbo.vw_RandevuRaporu", columns=[])
    q = "2024 yilinda gerceklesen randevu sayisini bolume gore goster"
    plan = planner.build_plan(q, analyzer.analyze(q), [], views=[view])
    assert plan.metrics == ["completed_appointment_count"]
    built = DeterministicSQLBuilder().build(plan)
    assert isinstance(built, DeterministicSQL)
    where = built.sql.split("WHERE", 1)[1].split("GROUP BY")[0]
    assert "RandevuDurumu = N'Gerçekleşti'" in where
