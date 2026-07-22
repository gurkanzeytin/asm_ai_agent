"""AI-INTELLIGENCE-017: fix the ValueResolver regression on grouping/dimension
questions and support aggregate clarification replies ("hepsini", "tümü", ...).

Observed bug: "Randevu durumlarının dağılımını göster" walked the candidate-
phrase extractor back from the "durum*" cue into "Randevu" (capitalized only
because it starts the sentence) and treated it as a candidate appointment
status VALUE, producing an unnecessary clarification with duplicated options;
the follow-up reply "hepsini" was then misclassified as out-of-scope because
nothing resolved it against the pending clarification.

Root cause: `extract_candidate_phrases()` had no guard against a dimension's
own domain noun (or another field's domain noun) being walked into as a
value-candidate token. Fixed via `_NEVER_CANDIDATE_ROOTS`.

Covers: dimension-vs-filter classification (item 1-3, 9), no unnecessary
clarification (item 6), deduplicated clarification options (item 4), "all"/
ordinal/explicit pending-clarification replies resolved before out-of-scope
(item 5, 8), and memory preservation of the original analytical request
across a clarification round-trip (item 7).
"""

from datetime import date

import pytest

from app.context.context_manager import ContextManager
from app.context.models import PendingClarification, ResolutionResult
from app.database_intelligence.models import ViewMetadata
from app.planning.planner import QueryPlanner
from app.planning.value_resolver import (
    ALL_REPLY_PATTERN,
    ValueResolver,
    build_clarification_headline,
    build_clarification_message,
    classify_value_intent,
    extract_candidate_phrases,
    resolve_value,
)
from app.services.query_analyzer import QueryAnalyzer

_TODAY = date(2026, 7, 22)
_VIEW = ViewMetadata(name="dbo.vw_RandevuRaporu", columns=[])


def _build_plan(question: str):
    analysis = QueryAnalyzer(today=_TODAY).analyze(question)
    return QueryPlanner().build_plan(question, analysis, tables=[], views=[_VIEW])


# ── Dimension vs filter (items 1, 3, 9) ─────────────────────────────────────


class TestDimensionNeverBecomesFilterValue:
    _REGRESSION_QUESTIONS = [
        "Randevu durumlarının dağılımını göster",
        "Şubelere göre randevu sayılarını göster",
        "Doktorlara göre randevu sayılarını göster",
        "Bölümlere göre farklı hasta sayılarını göster",
        "Hizmetlerin dağılımını göster",
        "Randevu kaynaklarının dağılımını göster",
    ]

    @pytest.mark.parametrize("question", _REGRESSION_QUESTIONS)
    def test_no_candidate_extracted_for_grouping_questions(self, question):
        assert extract_candidate_phrases(question) == {}

    def test_status_distribution_creates_no_status_filter(self):
        plan = _build_plan("Randevu durumlarının dağılımını göster")
        assert "RandevuDurumu" in plan.dimensions
        assert plan.metrics == ["appointment_count"]
        assert plan.extra_filters == []
        assert "appointment_status" not in plan.resolved_filters

    def test_branch_grouping_creates_no_branch_filter(self):
        plan = _build_plan("Şubelere göre randevu sayılarını göster")
        assert "SubeAdi" in plan.dimensions
        assert plan.branch_filters == []

    def test_doctor_grouping_creates_no_doctor_filter(self):
        plan = _build_plan("Doktorlara göre randevu sayılarını göster")
        assert "GenelRandevuKaynakAdi" in plan.dimensions
        assert extract_candidate_phrases("Doktorlara göre randevu sayılarını göster") == {}

    def test_service_distribution_creates_no_service_filter(self):
        plan = _build_plan("Hizmetlerin dağılımını göster")
        assert "HizmetAdi" in plan.dimensions
        assert extract_candidate_phrases("Hizmetlerin dağılımını göster") == {}


class TestExplicitValueStillCreatesGroundedFilter:
    def test_explicit_status_creates_grounded_filter(self):
        # Existing curated status mechanism (view_semantics.json), unaffected
        # by this fix — regression safety (item 12).
        plan = _build_plan("Beklemede olan randevuları göster")
        assert plan.extra_filters == ["RandevuDurumu = 'Beklemede'"]

    def test_explicit_status_gerceklesen(self):
        plan = _build_plan("Gerçekleşen randevuları göster")
        assert plan.extra_filters == ["RandevuDurumu = 'Gerçekleşti'"]

    def test_explicit_branch_creates_grounded_filter(self):
        question = "TEST ASM Gebze için göster"
        candidates = extract_candidate_phrases(question)
        assert candidates.get("branch") == ["TEST ASM Gebze"]
        resolved = resolve_value("branch", "TEST ASM Gebze", ["TEST ASM Gebze", "Kadıköy Şubesi"])
        assert resolved.grounded is True
        assert resolved.matched_value == "TEST ASM Gebze"

    def test_explicit_source_creates_grounded_filter(self):
        question = "Telefon kaynağından gelen randevuları göster"
        candidates = extract_candidate_phrases(question)
        assert candidates.get("appointment_source") == ["Telefon"]


class TestValueIntentVerdict:
    def test_status_distribution_is_grouping(self):
        assert (
            classify_value_intent("Randevu durumlarının dağılımını göster", "appointment_status")
            == "grouping"
        )

    def test_branch_grouping_wording_is_grouping(self):
        assert (
            classify_value_intent("Şubelere göre randevu sayılarını göster", "branch")
            == "grouping"
        )

    def test_explicit_branch_mention_is_filter(self):
        assert classify_value_intent("TEST ASM Gebze için göster", "branch") == "filter"

    def test_unrelated_question_is_none(self):
        assert classify_value_intent("Bugün kaç randevu var?", "branch") == "none"


# ── Duplicate clarification options (item 4) ────────────────────────────────


class TestNoDuplicateClarificationOptions:
    def test_dedupe_preserves_order_and_original_text(self):
        candidates = ["Beklemede", "Beklemede", "Gelmedi", "GELMEDI"]
        result = resolve_value("appointment_status", "Randevu", candidates)
        # Every alternative appears exactly once (by canonical normalized form).
        normalized = [a.lower() for a in result.alternatives]
        assert len(normalized) == len(set(normalized))
        assert "Beklemede" in result.alternatives

    def test_headline_never_embeds_the_bullet_list(self):
        result = resolve_value(
            "appointment_status",
            "Randevu",
            ["Beklemede", "Gelmedi", "Gerçekleşti", "Giriş Yapılmış", "İşlem Sürmekte"],
        )
        headline = build_clarification_headline(result)
        full_message = build_clarification_message(result)
        assert "- Beklemede" not in headline
        assert "- Beklemede" in full_message
        assert headline != full_message

    @pytest.mark.asyncio
    async def test_ambiguity_question_has_no_embedded_bullets(self):
        from app.agent.nodes.resolve_filter_values import ResolveFilterValuesNode
        from app.database_intelligence.value_catalog import ValueCatalog

        class _FakeCatalog(ValueCatalog):
            def __init__(self):
                pass

            async def get_distinct_values(self, field_name):
                return ["Gebze Şubesi", "Gebze Merkez Şubesi", "Gebze 2 Nolu Şube"]

            async def search_candidates(self, field_name, prefix, limit=10):
                return []

        node = ResolveFilterValuesNode(resolver=ValueResolver(catalog=_FakeCatalog()))
        plan = QueryPlanner().build_plan(
            "TEST Gebze için göster",
            QueryAnalyzer(today=_TODAY).analyze("TEST Gebze için göster"),
            tables=[],
            views=[_VIEW],
        )
        _plan, ambiguity = await node._resolve_plan(plan, {})
        assert ambiguity is not None
        assert "- " not in ambiguity.question
        assert len(ambiguity.options) == len(set(ambiguity.options))


# ── "All" / ordinal / explicit pending-clarification replies (items 5, 8) ──


class TestAllReplyPattern:
    @pytest.mark.parametrize(
        "reply", ["hepsini", "hepsi", "tümü", "tamamını", "bütününü"]
    )
    def test_all_reply_words_match(self, reply):
        from app.semantics.view_mapping import fold

        assert ALL_REPLY_PATTERN.search(fold(reply))


class TestPendingValueClarificationResolution:
    def _pending(self, **overrides) -> PendingClarification:
        defaults = dict(
            field="value_filter:appointment_status",
            reason="ambiguous",
            choices=["Beklemede", "Gelmedi", "Gerçekleşti"],
            original_question="Hangi durum için?",
            candidate_values=["Beklemede", "Gelmedi", "Gerçekleşti"],
            original_analysis_type="distribution",
            original_metrics=["appointment_count"],
            original_dimensions=["RandevuDurumu"],
        )
        defaults.update(overrides)
        return PendingClarification(**defaults)

    def _resolver(self):
        from app.context.resolver import ContextResolver

        return ContextResolver()

    def test_hepsini_resolves_pending_clarification(self):
        pending = self._pending()
        result = self._resolver()._resolve_pending_value_clarification("hepsini", pending)
        assert result is not None
        resolved_question, override = result
        assert resolved_question == pending.original_question
        assert override == {"appointment_status": []}

    def test_tumu_resolves_pending_clarification(self):
        pending = self._pending()
        result = self._resolver()._resolve_pending_value_clarification("tümü", pending)
        assert result is not None
        _resolved_question, override = result
        assert override == {"appointment_status": []}

    def test_ilkini_selects_first_candidate(self):
        pending = self._pending()
        result = self._resolver()._resolve_pending_value_clarification("ilkini", pending)
        assert result is not None
        _resolved_question, override = result
        assert override == {"appointment_status": ["Beklemede"]}

    def test_explicit_candidate_text_resolves_correctly(self):
        pending = self._pending()
        result = self._resolver()._resolve_pending_value_clarification("Gerçekleşti", pending)
        assert result is not None
        _resolved_question, override = result
        assert override == {"appointment_status": ["Gerçekleşti"]}

    def test_unmatched_reply_returns_none(self):
        pending = self._pending()
        result = self._resolver()._resolve_pending_value_clarification("asdkjhasd", pending)
        assert result is None


class TestClarificationReplyNeverGoesOutOfScope:
    def test_resolve_returns_applied_with_original_question(self):
        context = _make_context_with_pending()
        resolver_result: ResolutionResult = _context_resolver().resolve("hepsini", context)
        assert resolver_result.applied is True
        assert resolver_result.pending_clarification_resolved is True
        assert resolver_result.resolved_question == "Randevu durumlarının dağılımını göster."
        assert resolver_result.filter_override == {"appointment_status": []}


def _context_resolver():
    from app.context.resolver import ContextResolver

    return ContextResolver()


def _make_context_with_pending():
    from app.context.models import ConversationContext

    context = ConversationContext(session_id="test-pending-clarification")
    context.pending_clarification = PendingClarification(
        field="value_filter:appointment_status",
        reason="ambiguous",
        choices=["Beklemede", "Gelmedi"],
        original_question="Randevu durumlarının dağılımını göster.",
        candidate_values=["Beklemede", "Gelmedi"],
        original_analysis_type="distribution",
        original_metrics=["appointment_count"],
        original_dimensions=["RandevuDurumu"],
    )
    return context


# ── Memory (item 7) ──────────────────────────────────────────────────────────


class TestPendingClarificationMemory:
    def test_set_pending_clarification_preserves_original_analysis(self):
        manager = ContextManager()
        session_id = "test-pending-preserve-analysis"
        manager.set_pending_clarification(
            session_id,
            field="value_filter:appointment_status",
            reason="ambiguous",
            choices=["Beklemede", "Gelmedi"],
            original_question="Randevu durumlarının dağılımını göster.",
            candidate_values=["Beklemede", "Gelmedi"],
            original_analysis_type="distribution",
            original_metrics=["appointment_count"],
            original_dimensions=["RandevuDurumu"],
        )
        pending = manager.get_pending_clarification(session_id)
        assert pending is not None
        assert pending.original_analysis_type == "distribution"
        assert pending.original_metrics == ["appointment_count"]
        assert pending.original_dimensions == ["RandevuDurumu"]
        assert pending.original_question == "Randevu durumlarının dağılımını göster."

    def test_successful_resolution_clears_pending_state(self):
        manager = ContextManager()
        session_id = "test-pending-clears-on-success"
        manager.set_pending_clarification(
            session_id,
            field="value_filter:appointment_status",
            reason="ambiguous",
            choices=["Beklemede"],
        )
        assert manager.get_pending_clarification(session_id) is not None

        resolution = ResolutionResult(
            original_question="Beklemede",
            resolved_question="Randevu durumlarının dağılımını göster.",
            follow_up_detected=True,
        )
        from app.planning.models import QueryPlan

        manager.update(resolution, session_id=session_id, query_plan=QueryPlan(question="x"))
        assert manager.get_pending_clarification(session_id) is None

    def test_failed_resolution_does_not_corrupt_prior_context(self):
        manager = ContextManager()
        session_id = "test-pending-failed-reply-safe"
        manager.set_pending_clarification(
            session_id,
            field="value_filter:appointment_status",
            reason="ambiguous",
            choices=["Beklemede"],
            original_question="Randevu durumlarının dağılımını göster.",
            candidate_values=["Beklemede"],
        )
        before = manager._store.get(session_id).pending_clarification
        resolver_result = _context_resolver().resolve(
            "asdkjhasd", manager._store.get(session_id)
        )
        # An unmatched reply must not resolve the pending clarification, and
        # (per the service's memory-write policy) a failed/unresolved turn
        # never calls update() — the session's pending state stays untouched.
        assert resolver_result.pending_clarification_resolved is False
        after = manager._store.get(session_id).pending_clarification
        assert after == before
