"""AI-INTELLIGENCE-016: grounded analytical value-resolution layer.

Covers: pure matching (resolve_value), phrase extraction, the async
ValueResolver/ValueCatalog integration (with a fake catalog — no real DB),
QueryPlan.resolved_filters, PlanComplianceValidator guards for the new
fields, and conversation-memory integration (grounded-only persistence,
generic-scope clearing an inherited branch filter).
"""

from datetime import date

import pytest

from app.context.analytical_signals import AnalyticalSignals, from_query_plan
from app.context.context_manager import ContextManager
from app.context.models import ResolutionResult
from app.database_intelligence.models import ViewMetadata
from app.database_intelligence.value_catalog import FIELD_COLUMNS, ValueCatalog
from app.planning.compliance import PlanComplianceValidator
from app.planning.models import QueryPlan, ResolvedFilterPlan
from app.planning.planner import QueryPlanner
from app.planning.value_resolver import (
    ValueResolver,
    build_clarification_message,
    extract_candidate_phrases,
    normalize,
    resolve_value,
)
from app.services.query_analyzer import QueryAnalyzer


def _plan(**overrides) -> QueryPlan:
    defaults = dict(question="test")
    defaults.update(overrides)
    return QueryPlan(**defaults)


# ── resolve_value (pure matcher) ────────────────────────────────────────────


class TestResolveValueExact:
    def test_exact_branch_match(self):
        result = resolve_value("branch", "TEST ASM Gebze", ["TEST ASM Gebze", "ASM Gebze Merkez"])
        assert result.match_type == "exact"
        assert result.matched_value == "TEST ASM Gebze"
        assert result.grounded is True
        assert result.confidence == 1.0
        assert result.clarification_required is False

    def test_normalized_turkish_match(self):
        # 'ı'/'İ' folding + case-insensitivity: "gebze şubesi" -> "Gebze Şubesi".
        result = resolve_value("branch", "gebze şubesi", ["Gebze Şubesi"])
        assert result.match_type == "normalized_exact"
        assert result.matched_value == "Gebze Şubesi"
        assert result.grounded is True

    def test_prefix_match_single_candidate(self):
        result = resolve_value("branch", "Gebz", ["Gebze Şubesi", "Kadıköy Şubesi"])
        assert result.match_type == "prefix"
        assert result.matched_value == "Gebze Şubesi"
        assert result.grounded is True


class TestResolveValueAmbiguous:
    def test_multiple_matches_trigger_clarification(self):
        candidates = ["Gebze Şubesi", "Gebze Merkez Şubesi", "Gebze 2 Nolu Şube"]
        result = resolve_value("branch", "Gebze", candidates)
        assert result.match_type == "ambiguous"
        assert result.grounded is False
        assert result.clarification_required is True
        assert len(result.alternatives) >= 2
        message = build_clarification_message(result)
        assert "Gebze" in message
        assert "?" in message

    def test_ambiguous_never_returns_a_matched_value(self):
        result = resolve_value("branch", "Gebze", ["Gebze A", "Gebze B"])
        assert result.matched_value is None


class TestResolveValueUnknown:
    def test_unknown_branch_no_match(self):
        result = resolve_value("branch", "Marslılar Şubesi", ["TEST ASM Gebze", "Kadıköy Şubesi"])
        assert result.match_type == "no_match"
        assert result.grounded is False
        assert result.matched_value is None
        assert result.clarification_required is True

    def test_no_candidates_at_all_is_no_match(self):
        result = resolve_value("branch", "Herhangi Bir Şey", [])
        assert result.match_type == "no_match"
        assert result.grounded is False


class TestResolveValueDepartmentServiceSource:
    def test_grounded_department_filter(self):
        result = resolve_value(
            "department", "Kardiyoloji", ["Kardiyoloji", "Nöroloji", "Ortopedi"]
        )
        assert result.grounded is True
        assert result.matched_value == "Kardiyoloji"

    def test_grounded_service_filter(self):
        result = resolve_value("service", "MR Çekimi", ["MR Çekimi", "Tomografi"])
        assert result.grounded is True
        assert result.matched_value == "MR Çekimi"

    def test_grounded_source_filter(self):
        result = resolve_value(
            "appointment_source", "Çağrı Merkezi", ["Çağrı Merkezi", "Web Sitesi"]
        )
        assert result.grounded is True
        assert result.matched_value == "Çağrı Merkezi"


class TestResolveValueStatus:
    _STATUS_VALUES = ["Beklemede", "Gelmedi", "Gerçekleşti", "Giriş Yapılmış", "İşlem Sürmekte"]

    def test_status_exact_matching(self):
        result = resolve_value("appointment_status", "Gerçekleşti", self._STATUS_VALUES)
        assert result.match_type == "exact"
        assert result.grounded is True

    def test_unsupported_status_clarification(self):
        result = resolve_value("appointment_status", "İptal", self._STATUS_VALUES)
        assert result.grounded is False
        assert result.clarification_required is True
        assert result.match_type == "no_match"


class TestResolveValueGender:
    def test_gender_alias_erkek_maps_to_code(self):
        result = resolve_value("gender", "erkek", ["E", "K", "D"])
        assert result.match_type == "alias"
        assert result.matched_value == "E"
        assert result.grounded is True

    def test_gender_alias_kadin_maps_to_code(self):
        result = resolve_value("gender", "Kadın", ["E", "K", "D"])
        assert result.matched_value == "K"


class TestNormalize:
    def test_turkish_i_dotless_and_punctuation(self):
        assert normalize("TEST ASM Gebze, şubesi!") == normalize("test asm gebze subesi")

    def test_whitespace_collapsed(self):
        assert normalize("Gebze   Şubesi") == normalize("Gebze Şubesi")


# ── extract_candidate_phrases ───────────────────────────────────────────────


class TestExtractCandidatePhrases:
    def test_branch_via_icin_fallback(self):
        candidates = extract_candidate_phrases("Gebze için göster.")
        assert candidates.get("branch") == ["Gebze"]

    def test_multi_token_branch_via_icin_fallback(self):
        candidates = extract_candidate_phrases(
            "TEST ASM Gebze için son 30 günlük randevu sayılarını göster."
        )
        assert candidates.get("branch") == ["TEST ASM Gebze"]

    def test_branch_via_cue_word(self):
        candidates = extract_candidate_phrases("TEST ASM Gebze şubesi için randevuları göster.")
        assert candidates.get("branch") == ["TEST ASM Gebze"]

    def test_generic_scope_phrase_yields_no_branch_candidate(self):
        candidates = extract_candidate_phrases(
            "Bugünkü hasta istatistiklerini tüm aile sağlığı merkezleri için göster."
        )
        assert "branch" not in candidates

    def test_department_cue_word(self):
        candidates = extract_candidate_phrases("Kardiyoloji bölümündeki randevuları göster.")
        assert candidates.get("department") == ["Kardiyoloji"]

    def test_no_candidate_when_nothing_capitalized(self):
        candidates = extract_candidate_phrases("şubelere göre randevu sayılarını göster.")
        assert "branch" not in candidates


# ── ValueResolver (async, DB-free via a fake catalog) ───────────────────────


class _FakeCatalog(ValueCatalog):
    def __init__(
        self,
        distinct: dict[str, list[str]] | None = None,
        search: list[str] | None = None,
    ):
        self._distinct = distinct or {}
        self._search = search or []

    async def get_distinct_values(self, field_name: str) -> list[str]:
        return self._distinct.get(field_name, [])

    async def search_candidates(self, field_name: str, prefix: str, limit: int = 10) -> list[str]:
        return self._search


@pytest.mark.asyncio
class TestValueResolverAsync:
    async def test_resolve_grounded_branch(self):
        catalog = _FakeCatalog(distinct={"branch": ["TEST ASM Gebze", "Kadıköy Şubesi"]})
        resolver = ValueResolver(catalog=catalog)
        resolved = await resolver.resolve("branch", "TEST ASM Gebze")
        assert resolved.grounded is True
        assert resolved.matched_value == "TEST ASM Gebze"

    async def test_resolve_unknown_field_is_no_match(self):
        resolver = ValueResolver(catalog=_FakeCatalog())
        resolved = await resolver.resolve("not_a_real_field", "anything")
        assert resolved.grounded is False
        assert resolved.match_type == "no_match"

    async def test_high_cardinality_field_uses_bounded_search(self):
        catalog = _FakeCatalog(search=["Dr. Ahmet Yılmaz"])
        resolver = ValueResolver(catalog=catalog)
        resolved = await resolver.resolve("doctor", "Dr. Ahmet Yılmaz")
        assert resolved.grounded is True
        assert resolved.matched_value == "Dr. Ahmet Yılmaz"


# ── No patient-level identifiers in the catalog ─────────────────────────────


class TestNoPatientLevelValues:
    def test_patient_columns_never_in_field_columns(self):
        columns = {column for column, _tier in FIELD_COLUMNS.values()}
        for forbidden in ("HastaAdi", "HastaSoyadi", "HastaId", "DogumTarihi", "HastaId2"):
            assert forbidden not in columns

    def test_supported_field_set_matches_spec(self):
        expected = {
            "branch", "doctor", "department", "service", "category",
            "appointment_source", "appointment_status", "appointment_type",
            "nationality", "gender",
        }
        assert set(FIELD_COLUMNS.keys()) == expected


# ── PlanComplianceValidator: SQL contains only grounded values ─────────────


class TestComplianceGuards:
    def test_ungrounded_service_filter_rejected(self):
        plan = _plan(question="Hangi hizmet için?")
        sql = "SELECT COUNT(*) AS c FROM dbo.vw_RandevuRaporu WHERE HizmetAdi = 'MR Çekimi'"
        result = PlanComplianceValidator().check(sql, plan)
        assert not result.compliant
        assert any("ungrounded HizmetAdi" in item for item in result.missing)

    def test_grounded_service_filter_accepted(self):
        plan = _plan(
            question="MR Çekimi hizmeti için göster.",
            resolved_filters={
                "service": ResolvedFilterPlan(
                    field="service", values=["MR Çekimi"], grounded=True, match_type="exact"
                )
            },
        )
        sql = "SELECT COUNT(*) AS c FROM dbo.vw_RandevuRaporu WHERE HizmetAdi = 'MR Çekimi'"
        result = PlanComplianceValidator().check(sql, plan)
        assert not any("HizmetAdi" in item for item in result.missing)

    def test_ungrounded_gender_filter_rejected(self):
        plan = _plan(question="Erkek hastalar?")
        sql = "SELECT COUNT(*) AS c FROM dbo.vw_RandevuRaporu WHERE CinsiyetId = 'E'"
        result = PlanComplianceValidator().check(sql, plan)
        assert any("ungrounded CinsiyetId" in item for item in result.missing)

    def test_appointment_status_predicate_not_flagged_by_new_guard(self):
        # RandevuDurumu keeps its own pre-existing curated mechanism
        # (view_semantics.json status_filters) — unrelated to the new guard.
        plan = _plan(question="Gerçekleşen randevular")
        sql = "SELECT COUNT(*) AS c FROM dbo.vw_RandevuRaporu WHERE RandevuDurumu = 'Gerçekleşti'"
        result = PlanComplianceValidator().check(sql, plan)
        assert not any("RandevuDurumu" in item for item in result.missing)

    def test_branch_group_by_not_flagged_as_ungrounded_filter(self):
        plan = _plan(question="Şubelere göre randevu sayısı", dimensions=["SubeAdi"])
        sql = (
            "SELECT SubeAdi, COUNT(*) AS c FROM dbo.vw_RandevuRaporu "
            "GROUP BY SubeAdi"
        )
        result = PlanComplianceValidator().check(sql, plan)
        assert not any("SubeAdi" in item for item in result.missing)


# ── Memory integration ──────────────────────────────────────────────────────


class TestMemoryIntegration:
    def test_from_query_plan_only_persists_grounded_branch(self):
        plan = _plan(question="TEST ASM Gebze için göster.", branch_filters=["TEST ASM Gebze"])
        signals = from_query_plan(plan)
        assert signals.branch_filters == ["TEST ASM Gebze"]

    def test_from_query_plan_never_persists_ungrounded_service(self):
        plan = _plan(
            question="hizmet?",
            resolved_filters={
                "service": ResolvedFilterPlan(
                    field="service", values=[], grounded=False, match_type="ambiguous",
                    clarification_required=True, alternatives=["MR Çekimi", "Tomografi"],
                )
            },
        )
        signals = from_query_plan(plan)
        assert signals.service_filters == []

    def test_from_query_plan_persists_grounded_source(self):
        plan = _plan(
            question="Çağrı merkezi kaynağı için göster.",
            resolved_filters={
                "appointment_source": ResolvedFilterPlan(
                    field="appointment_source", values=["Çağrı Merkezi"], grounded=True,
                    match_type="exact",
                )
            },
        )
        signals = from_query_plan(plan)
        assert signals.source_filters == ["Çağrı Merkezi"]

    def test_ambiguous_value_does_not_corrupt_memory(self):
        empty = AnalyticalSignals()
        ambiguous_plan_signals = AnalyticalSignals(branch_filters=[])  # unresolved -> nothing set
        assert ambiguous_plan_signals.branch_filters == empty.branch_filters


class TestGenericScopeClearsInheritedBranch:
    def test_generic_scope_clears_inherited_branch_on_followup(self):
        manager = ContextManager()
        session_id = "test-value-resolver-scope-clear"

        # Turn 1: grounded branch filter is recorded.
        resolution_1 = ResolutionResult(
            original_question="TEST ASM Gebze için göster.",
            resolved_question="TEST ASM Gebze için göster.",
            follow_up_detected=False,
        )
        plan_1 = _plan(
            question="TEST ASM Gebze için göster.",
            branch_filters=["TEST ASM Gebze"],
        )
        manager.update(resolution_1, session_id=session_id, query_plan=plan_1)
        context = manager._store.get(session_id)
        assert context.branch_filters == ["TEST ASM Gebze"]

        # Turn 2: a follow-up using a generic organization-wide scope phrase
        # must clear the inherited branch filter, not re-inherit it.
        resolution_2 = ResolutionResult(
            original_question="Peki tüm şubeler için göster.",
            resolved_question="Peki tüm şubeler için göster.",
            follow_up_detected=True,
        )
        plan_2 = _plan(
            question="Peki tüm şubeler için göster.",
            scope="all",
            branch_filters=[],
            generic_scope_phrase_detected="tum subeler",
        )
        manager.update(resolution_2, session_id=session_id, query_plan=plan_2)
        context = manager._store.get(session_id)
        assert context.branch_filters == []


# ── Live scenarios (item 12) ────────────────────────────────────────────────

_TODAY = date(2026, 7, 22)
_VIEW = ViewMetadata(name="dbo.vw_RandevuRaporu", columns=[])


def _build_plan(question: str) -> QueryPlan:
    analysis = QueryAnalyzer(today=_TODAY).analyze(question)
    return QueryPlanner().build_plan(question, analysis, tables=[], views=[_VIEW])


class TestLiveScenarios:
    def test_scenario_a_grounded_branch_candidate_extracted(self):
        question = "TEST ASM Gebze için son 30 günlük randevu sayılarını göster."
        plan = _build_plan(question)
        assert plan.scope == "filtered"
        candidates = extract_candidate_phrases(question)
        assert candidates.get("branch") == ["TEST ASM Gebze"]
        resolved = resolve_value("branch", "TEST ASM Gebze", ["TEST ASM Gebze", "Kadıköy Şubesi"])
        assert resolved.grounded is True
        assert resolved.matched_value == "TEST ASM Gebze"

    def test_scenario_b_generic_scope_no_branch_value_filter(self):
        question = "Tüm şubelere göre randevu sayılarını göster."
        plan = _build_plan(question)
        assert plan.scope == "all"
        assert plan.branch_filters == []
        candidates = extract_candidate_phrases(question)
        assert "branch" not in candidates

    def test_scenario_c_ambiguous_branch_needs_clarification(self):
        question = "Gebze için göster."
        candidates = extract_candidate_phrases(question)
        assert candidates.get("branch") == ["Gebze"]
        result = resolve_value(
            "branch", "Gebze", ["Gebze Şubesi", "Gebze Merkez Şubesi", "Gebze 2 Nolu Şube"]
        )
        assert result.match_type == "ambiguous"
        assert result.grounded is False
        assert result.clarification_required is True

    def test_scenario_c_unique_branch_match_resolves(self):
        result = resolve_value("branch", "Gebze", ["Gebze Şubesi", "Kadıköy Şubesi"])
        assert result.match_type in ("prefix", "normalized_exact", "fuzzy")
        assert result.grounded is True
        assert result.matched_value == "Gebze Şubesi"

    def test_scenario_d_today_range_preserved_no_branch_filter(self):
        question = "Bugünkü hasta istatistiklerini tüm aile sağlığı merkezleri için göster."
        plan = _build_plan(question)
        assert plan.scope == "all"
        assert plan.branch_filters == []
        assert plan.date_filters
        assert plan.date_filters[0].start_date == plan.date_filters[0].end_date == "2026-07-22"
        candidates = extract_candidate_phrases(question)
        assert "branch" not in candidates
