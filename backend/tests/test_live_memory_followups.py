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
