"""AI-INTELLIGENCE-015 — generic-scope phrase and date-resolution bug fix.

Observed bug: "Bugünkü hasta istatistiklerini tüm aile sağlığı merkezleri için
göster." produced SQL that (1) treated "tüm aile sağlığı merkezleri" as a
literal SubeAdi LIKE filter, and (2) resolved "bugünkü" to a 90-day lookback
window instead of the current day.

Root cause: `QueryAnalyzer`/`ContextExtractor`/`AnalyticalSignals` already
correctly resolve "bugünkü" to a single-day range and never fabricate a
branch filter — but (a) `QueryPlan` had no `scope`/`branch_filters` fields to
carry "this is organization-wide, not a specific branch" forward, (b)
`format_plan_for_prompt` rendered a single-day date filter as a naive
DATETIME `=` equality (which reads as "almost never matches" and plausibly
nudged the LLM fallback toward inventing a wider window), and (c)
`PlanComplianceValidator` never rejected an ungrounded SubeAdi predicate or a
DATEADD lookback offset contradicting an explicit single day.

No real network/LLM calls anywhere in this file — pure planner/analyzer/
compliance/context unit tests.
"""

from datetime import date

import pytest

from app.context.analytical_signals import from_query_plan, from_raw_text
from app.context.context_manager import ContextManager
from app.context.session_store import SessionStore
from app.database_intelligence.models import ViewMetadata
from app.planning.compliance import PlanComplianceValidator
from app.planning.models import QueryPlan
from app.planning.planner import QueryPlanner, format_plan_for_prompt
from app.services.deterministic_sql_builder import DeterministicSQLBuilder
from app.services.query_analyzer import QueryAnalyzer

_TODAY = date(2026, 7, 22)
VIEW = ViewMetadata(name="dbo.vw_RandevuRaporu", columns=[])


def _analyze(question: str):
    return QueryAnalyzer(today=_TODAY).analyze(question)


def _plan(question: str) -> QueryPlan:
    return QueryPlanner().build_plan(question, _analyze(question), tables=[], views=[VIEW])


class FakeClock:
    def __init__(self) -> None:
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture()
def manager() -> ContextManager:
    return ContextManager(store=SessionStore(now_fn=FakeClock()))


def ask(manager: ContextManager, question: str, session: str = "s1"):
    resolution = manager.resolve(question, session)
    manager.update(resolution, session)
    return resolution


# ─────────────────────────────────────────────
# 1. Date resolution / precedence
# ─────────────────────────────────────────────


class TestDateResolution:
    def test_bugun_resolves_to_current_day_half_open_range(self):
        analysis = _analyze("Bugün kaç randevu var?")
        assert len(analysis.detected_dates) == 1
        span = analysis.detected_dates[0]
        assert span.start_date == _TODAY
        assert span.end_date == _TODAY

    def test_bugunku_resolves_to_current_day_half_open_range(self):
        analysis = _analyze("Bugünkü hasta istatistiklerini göster.")
        assert len(analysis.detected_dates) == 1
        span = analysis.detected_dates[0]
        assert span.start_date == _TODAY
        assert span.end_date == _TODAY

    def test_bugun_never_resolves_to_a_90_day_window(self):
        analysis = _analyze("Bugünkü randevuları göster.")
        span = analysis.detected_dates[0]
        assert (span.end_date - span.start_date).days == 0

    def test_plan_date_filter_matches_today_not_a_lookback_window(self):
        plan = _plan("Bugünkü hasta istatistiklerini tüm aile sağlığı merkezleri için göster.")
        assert len(plan.date_filters) == 1
        date_filter = plan.date_filters[0]
        assert date_filter.start_date == _TODAY.isoformat()
        assert date_filter.end_date == _TODAY.isoformat()

    def test_prompt_renders_today_as_half_open_range_not_equality_or_lookback(self):
        plan = _plan("Bugünkü randevuları göster.")
        rendered = format_plan_for_prompt(plan)
        assert f"BaslangicTarihi >= '{_TODAY.isoformat()}'" in rendered
        assert f"DATEADD(day, 1, '{_TODAY.isoformat()}')" in rendered
        assert f"BaslangicTarihi = '{_TODAY.isoformat()}'" not in rendered
        assert "DATEADD(day, -" not in rendered

    def test_explicit_today_overrides_inherited_90_day_style_default(self, manager):
        ask(manager, "Son 90 gündeki randevu istatistiklerini göster.")
        resolution = ask(manager, "Bugünkü hasta istatistiklerini göster.")
        assert "date" not in resolution.inherited
        assert "son 90" not in resolution.resolved_question.lower()

    def test_inherited_date_does_not_override_explicit_current_turn_today(self, manager):
        ask(manager, "Geçen ay kaç randevu vardı?")
        resolution = ask(manager, "Bugünkü randevuları göster.")
        assert "date" not in resolution.inherited
        assert "gecen ay" not in resolution.resolved_question.lower()
        assert resolution.resolved_question == "Bugünkü randevuları göster."


# ─────────────────────────────────────────────
# 2. Generic scope phrase handling
# ─────────────────────────────────────────────


class TestGenericScope:
    @pytest.mark.parametrize(
        "question",
        [
            "Bugünkü hasta istatistiklerini tüm aile sağlığı merkezleri için göster.",
            "Bütün merkezler için randevu sayısını göster.",
            "Kurum genelinde hasta sayısını göster.",
            "Tüm şubeler için randevu sayısını göster.",
        ],
    )
    def test_generic_scope_phrase_sets_scope_all_with_no_branch_filter(self, question):
        plan = _plan(question)
        assert plan.scope == "all"
        assert plan.branch_filters == []
        assert plan.generic_scope_phrase_detected

    def test_branch_dimension_wording_does_not_imply_scope_all(self):
        plan = _plan("Şubelere göre randevu sayılarını göster.")
        assert "SubeAdi" in plan.dimensions
        assert plan.branch_filters == []

    def test_grounded_branch_question_does_not_set_generic_scope(self):
        plan = _plan("Gebze şubesi için randevu sayısını göster.")
        assert plan.generic_scope_phrase_detected is None


# ─────────────────────────────────────────────
# 3. Grounded branch value requirement
# ─────────────────────────────────────────────


class TestGroundedBranch:
    def test_no_grounded_value_catalog_never_fabricates_a_branch_filter(self):
        # No grounded branch-name value list exists in this codebase (see
        # AnalyticalSignals module docstring) — branch_filters must always
        # stay empty, for any wording, generic or specific.
        for question in (
            "Gebze şubesi için göster.",
            "Merkez şubede kaç randevu var?",
            "Tüm aile sağlığı merkezleri için göster.",
        ):
            plan = _plan(question)
            assert plan.branch_filters == []

    def test_analytical_signals_never_populates_branch_filters_from_raw_text(self):
        signals = from_raw_text("Tüm aile sağlığı merkezleri için hasta sayısını göster.")
        assert signals.branch_filters == []

    def test_analytical_signals_never_populates_branch_filters_from_query_plan(self):
        plan = _plan("Gebze şubesi için randevu sayısını göster.")
        signals = from_query_plan(plan)
        assert signals.branch_filters == []


# ─────────────────────────────────────────────
# 4. PlanComplianceValidator: reject ungrounded/lookback SQL
# ─────────────────────────────────────────────

_BAD_SQL = """SELECT TOP (100)
    GenelRandevuBolumAdi AS [BolumAdi],
    COUNT(DISTINCT HastaId) AS [FarkliHastaSayisi],
    COUNT(*) AS [RandevuSayisi]
FROM dbo.vw_RandevuRaporu
WHERE BaslangicTarihi >= DATEADD(DAY, -90, '2026-07-22')
    AND BaslangicTarihi < '2026-07-22'
    AND SubeAdi LIKE '%Aile Sagligi Merkezi%'
GROUP BY GenelRandevuBolumAdi
ORDER BY GenelRandevuBolumAdi;"""

_GOOD_SQL = """SELECT TOP (100)
    GenelRandevuBolumAdi AS [BolumAdi],
    COUNT(DISTINCT HastaId) AS [FarkliHastaSayisi],
    COUNT(*) AS [RandevuSayisi]
FROM dbo.vw_RandevuRaporu
WHERE BaslangicTarihi >= '2026-07-22'
    AND BaslangicTarihi < DATEADD(DAY, 1, '2026-07-22')
GROUP BY GenelRandevuBolumAdi
ORDER BY GenelRandevuBolumAdi;"""


class TestComplianceGuards:
    def test_ungrounded_subeadi_like_filter_is_rejected(self):
        plan = _plan("Bugünkü hasta istatistiklerini tüm aile sağlığı merkezleri için göster.")
        result = PlanComplianceValidator().check(_BAD_SQL, plan)
        assert not result.compliant
        assert any("SubeAdi" in item for item in result.missing)

    def test_explicit_single_day_rendered_as_lookback_offset_is_rejected(self):
        plan = _plan("Bugünkü hasta istatistiklerini tüm aile sağlığı merkezleri için göster.")
        result = PlanComplianceValidator().check(_BAD_SQL, plan)
        assert not result.compliant
        assert any("DATEADD" in item for item in result.missing)

    def test_corrected_sql_with_today_range_and_no_branch_filter_passes_those_guards(self):
        plan = _plan("Bugünkü hasta istatistiklerini tüm aile sağlığı merkezleri için göster.")
        result = PlanComplianceValidator().check(_GOOD_SQL, plan)
        assert not any("SubeAdi" in item for item in result.missing)
        assert not any("DATEADD" in item and "lookback" in item for item in result.missing)

    def test_grounded_branch_filter_is_accepted(self):
        plan = QueryPlan(
            question="q",
            branch_filters=["Gebze Aile Sağlığı Merkezi"],
        )
        sql = (
            "SELECT COUNT(*) FROM dbo.vw_RandevuRaporu "
            "WHERE SubeAdi = N'Gebze Aile Sağlığı Merkezi';"
        )
        result = PlanComplianceValidator().check(sql, plan)
        assert not any("ungrounded" in item for item in result.missing)

    def test_grouping_by_branch_is_never_flagged_as_a_filter(self):
        plan = QueryPlan(question="q", dimensions=["SubeAdi"])
        sql = "SELECT SubeAdi, COUNT(*) FROM dbo.vw_RandevuRaporu GROUP BY SubeAdi;"
        result = PlanComplianceValidator().check(sql, plan)
        assert not any("ungrounded" in item for item in result.missing)


# ─────────────────────────────────────────────
# 5. Deterministic SQL builder: no ungrounded filter, correct today range
# ─────────────────────────────────────────────


class TestDeterministicSql:
    def test_today_range_for_a_supported_plan(self):
        plan = _plan("Bugün kaç randevu var?")
        result = DeterministicSQLBuilder().build(plan)
        assert not hasattr(result, "reason"), getattr(result, "reason", None)
        assert f"BaslangicTarihi >= '{_TODAY.isoformat()}'" in result.sql
        assert f"DATEADD(day, 1, '{_TODAY.isoformat()}')" in result.sql
        assert "DATEADD(day, -" not in result.sql

    def test_no_ungrounded_subeadi_filter_in_deterministic_output(self):
        plan = _plan("Tüm şubeler için bugün kaç randevu var?")
        result = DeterministicSQLBuilder().build(plan)
        assert not hasattr(result, "reason"), getattr(result, "reason", None)
        assert "subeadi like" not in result.sql.lower()
        assert "subeadi =" not in result.sql.lower()

    def test_allowed_view_only(self):
        plan = _plan("Bugün kaç randevu var?")
        result = DeterministicSQLBuilder().build(plan)
        assert "dbo.vw_RandevuRaporu" in result.sql


# ─────────────────────────────────────────────
# 6. Memory / follow-up precedence
# ─────────────────────────────────────────────


class TestMemoryPrecedence:
    def test_generic_all_scope_phrase_does_not_inherit_a_stale_department_filter(self, manager):
        ask(manager, "Kardiyoloji bölümü için randevu sayısını göster.")
        resolution = ask(manager, "Tüm şubeler için randevu sayısını göster.")
        # A full, independent question (not elliptical) must not silently carry
        # forward the previous turn's department filter.
        assert "department" not in resolution.inherited

    def test_explicit_grounded_department_replaces_inherited_department(self, manager):
        ask(manager, "Kardiyoloji bölümü için randevu sayısını göster.")
        resolution = ask(manager, "Üroloji bölümü için randevu sayısını göster.")
        assert "department" not in resolution.inherited
        assert "Kardiyoloji" not in resolution.resolved_question

    def test_unrelated_full_question_inherits_no_stale_branch_dimension(self, manager):
        ask(manager, "Şubelere göre randevu sayılarını göster.")
        resolution = ask(manager, "Doktorları listele.")
        # A full, independent follow-up must not silently inherit the
        # previous turn's branch dimension — and no branch VALUE filter ever
        # existed to leak forward either way.
        assert "SubeAdi" not in resolution.resolved_question
        plan = _plan("Doktorları listele.")
        assert plan.branch_filters == []
