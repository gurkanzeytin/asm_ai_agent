"""SQL-only output mode + status-negation follow-up regressions (2026-07-24).

Two UI-observed bugs fixed here:
- "... SQL sorgusunu oluşturur musun" never triggered SQL-only mode because
  the marker regex required the EXACT word "olustur", not its conjugated
  form "olusturur" (a `\\b...\\b` boundary mismatch).
- "gerçekleşmeyenler ?" as a bare follow-up fell to OUT_OF_SCOPE: it carries
  no entity/date of its own, so nothing signalled it as a genuine follow-up,
  and even once recognized, a retained CONDITIONAL metric tied to the
  opposite status (completed_appointment_count/Gerçekleşti) would silently
  combine with the new WHERE filter to compute a nonsensical zero.

No LLM or database is used.
"""

from unittest.mock import AsyncMock

import pytest

from app.agent.nodes.resolve_filter_values import ResolveFilterValuesNode
from app.agent.nodes.retrieve_context import RetrieveContextNode
from app.agent.state import AgentState
from app.context import ContextManager
from app.context.analytical_signals import from_raw_text
from app.context.session_store import SessionStore
from app.database_intelligence.models import DatabaseContext, ViewMetadata
from app.planning.compliance import PlanComplianceValidator
from app.planning.models import QueryPlan
from app.reporting.output_policy import determine_requested_response_mode
from app.semantics.view_mapping import resolve_negated_status_values
from app.services.deterministic_sql_builder import DeterministicSQLBuilder


# ── SQL-only response mode detection ────────────────────────────────────────


class TestSQLOnlyModeDetection:
    def test_conjugated_verb_triggers_sql_only(self):
        question = (
            "2025 ocak ayında randevu sayılarını verecek SQL sorgusunu "
            "oluşturur musun"
        )
        assert determine_requested_response_mode(question) == "sql"

    def test_original_imperative_forms_still_work(self):
        assert determine_requested_response_mode("sadece sql yaz") == "sql"
        assert determine_requested_response_mode("sql sorgusunu göster") == "sql"

    def test_table_follow_up_after_sql_only_is_data_mode(self):
        assert determine_requested_response_mode("tabloyu getir") == "data"

    def test_data_wording_is_never_shadowed_by_sql_only(self):
        # Regression guard: broadening "olustur"/"goster" to "\\w*" must not
        # make a genuine data request ("verilerini göster") register as
        # SQL-only just because "ver\\w*" now matches "verilerini".
        question = "sql tablosundan hasta verilerini göster"
        assert determine_requested_response_mode(question) == "data"


# ── status negation vocabulary ───────────────────────────────────────────────


class TestNegatedStatusValues:
    def test_gerceklesmeyen_returns_the_four_other_statuses(self):
        values = resolve_negated_status_values("gerceklesmeyenler")
        assert values is not None
        assert set(values) == {"Beklemede", "Gelmedi", "Giriş Yapılmış", "İşlem Sürmekte"}
        assert "Gerçekleşti" not in values

    def test_unrelated_text_returns_none(self):
        assert resolve_negated_status_values("kac randevu var") is None

    def test_positive_status_term_does_not_collide_with_negation(self):
        # "gerceklesen" must not accidentally substring-match inside
        # "gerceklesmeyen" (or vice versa) — they mean opposite things.
        assert resolve_negated_status_values("gerceklesen randevu sayisi") is None


class TestFromRawTextNegation:
    def test_bare_negation_phrase_is_not_empty(self):
        # Without this, "gerçekleşmeyenler ?" has no entity/date/metric of its
        # own and ContextResolver never recognizes it as a follow-up at all.
        signals = from_raw_text("gerçekleşmeyenler ?")
        assert not signals.is_empty()
        assert set(signals.status_filters) == {
            "Beklemede", "Gelmedi", "Giriş Yapılmış", "İşlem Sürmekte",
        }

    def test_positive_status_phrase_still_single_valued(self):
        signals = from_raw_text("Sadece bekleyenleri göster")
        assert signals.status_filters == ["Beklemede"]


# ── full conversational chain (no LLM/DB) ───────────────────────────────────


class _GroundedResolver:
    async def resolve(self, field_name: str, phrase: str):
        from app.planning.value_resolver import resolve_value

        return resolve_value(field_name, phrase, [])


class _Chain:
    def __init__(self) -> None:
        self.manager = ContextManager(store=SessionStore())
        prompt_service = AsyncMock()
        prompt_service.retrieve_schema_context.return_value = DatabaseContext(
            tables=[], views=[ViewMetadata(name="dbo.vw_RandevuRaporu", columns=[])]
        )
        self.retrieve = RetrieveContextNode(prompt_service)
        self.resolve_filters = ResolveFilterValuesNode(_GroundedResolver())
        self.session_id = "status-negation-chain"

    async def turn(self, question: str):
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
        assert self.manager.update(resolution, self.session_id, query_plan=state.query_plan)
        return state.query_plan, resolution


@pytest.mark.asyncio
async def test_negation_follow_up_after_completed_status_metric():
    chain = _Chain()

    first, _ = await chain.turn("2025 Ocak ayında randevu sayılarını göster")
    assert first.metrics == ["appointment_count"]

    second, _ = await chain.turn("Gerçekleşen randevu sayısı nedir")
    assert second.metrics == ["completed_appointment_count"]
    assert any("Gerçekleşti" in f for f in second.extra_filters)

    third, resolution = await chain.turn("Gerçekleşmeyenler ?")
    assert resolution.follow_up_detected
    # The contradicted conditional metric must fall back to the base count —
    # otherwise SUM(CASE WHEN RandevuDurumu='Gerçekleşti'...) combined with
    # the new WHERE (which EXCLUDES Gerçekleşti) always evaluates to zero.
    assert third.metrics == ["appointment_count"]
    assert third.aggregation == "COUNT(*)"
    assert any("IN (" in f or "RandevuDurumu" in f for f in third.extra_filters)
    rendered_filters = " ".join(third.extra_filters)
    assert "Gerçekleşti" not in rendered_filters
    for status in ("Beklemede", "Gelmedi", "Giriş Yapılmış", "İşlem Sürmekte"):
        assert status in rendered_filters
    # The date range from turn 1 must survive untouched.
    assert third.date_filters == first.date_filters

    built = DeterministicSQLBuilder().build(third)
    assert hasattr(built, "sql"), getattr(built, "reason", "")
    check = PlanComplianceValidator().check(
        built.sql, third, expected_aliases=built.expected_aliases, deterministic=True
    )
    assert check.compliant, check.missing
    assert "SUM(CASE" not in built.sql
    assert "COUNT(*)" in built.sql


@pytest.mark.asyncio
async def test_bare_negation_with_no_prior_context_is_not_a_followup():
    # No anchor exists for what to count — this must NOT silently become a
    # standalone answerable question (AnswerabilityGuard should route it to
    # OUT_OF_SCOPE), matching the observed correct behavior in production.
    chain = _Chain()
    _, resolution = await chain.turn("Gerçekleşmeyenler ?")
    assert not resolution.follow_up_detected
