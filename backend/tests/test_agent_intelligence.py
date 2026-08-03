"""Agent Intelligence Foundation tests: catalogs, semantic matching, planning,
golden dataset integrity, few-shot retrieval, result validation, and planner
regression accuracy. Deterministic — no LLM, no database.
"""

from collections import Counter

import pytest

from app.analytics.result_validation import ResultValidator
from app.application_models.workflow_models import QueryResult
from app.database_intelligence.models import ViewMetadata
from app.planning.planner import QueryPlanner, format_plan_for_prompt
from app.semantics import catalog, examples
from app.semantics.view_mapping import fold
from app.services.query_analyzer import QueryAnalyzer

VIEW_NAME = "dbo.vw_RandevuRaporu"
VIEW = ViewMetadata(name=VIEW_NAME, columns=[])

# The 24-column view contract; TCKimlikNo/PasaportNo/HastaGSM were removed
# from dbo.vw_RandevuRaporu and must never reappear anywhere.
EXPECTED_COLUMNS = {
    "Id", "BaslangicTarihi", "BitisTarihi", "RandevuSuresi", "RandevuDurumu",
    "HastaId", "RandevuTipiAdi", "RandevuyuVeren", "HastaAdi", "HastaSoyadi",
    "DogumTarihi", "CinsiyetId",
    "HastaId2", "Uyruk", "BolumId", "DoktorId", "HizmetAdi",
    "ProtokolIslemState", "KategoriAdi", "GenelRandevuKaynakAdi",
    "GenelRandevuBolumAdi", "ProtokolAcilisTarihi", "SubeAdi", "CreatedDate",
}
REMOVED_COLUMNS = {"TCKimlikNo", "PasaportNo", "HastaGSM"}
PII_COLUMNS = {"HastaAdi", "HastaSoyadi"}


@pytest.fixture(scope="module")
def analyzer():
    return QueryAnalyzer()


@pytest.fixture(scope="module")
def planner():
    return QueryPlanner()


def plan_for(planner, analyzer, question):
    return planner.build_plan(question, analyzer.analyze(question), tables=[], views=[VIEW])


# ═══════════════════════════════ Catalog tests ═══════════════════════════════


def test_column_catalog_covers_exactly_the_24_view_columns():
    assert catalog.load_column_catalog().column_names() == EXPECTED_COLUMNS


def test_removed_columns_are_gone_everywhere():
    """TCKimlikNo/PasaportNo/HastaGSM must not appear in any catalog artifact."""
    assert not (catalog.load_column_catalog().column_names() & REMOVED_COLUMNS)
    for spec in catalog.load_column_catalog().columns:
        assert not (set(spec.related_columns) & REMOVED_COLUMNS), spec.column
    for metric in catalog.load_metric_catalog().metrics:
        assert not (set(metric.required_columns) & REMOVED_COLUMNS), metric.id
        assert not (set(metric.compatible_dimensions) & REMOVED_COLUMNS), metric.id
        assert not (REMOVED_COLUMNS & set((metric.formula or "").split())), metric.id
    for relation in catalog.load_relationship_catalog().relationships:
        assert not ((set(relation.columns) | set(relation.dimensions)) & REMOVED_COLUMNS)


def test_removed_metrics_are_gone():
    metric_ids = set(catalog.load_metric_catalog().by_id())
    assert not metric_ids & {
        "missing_phone_count", "phone_completeness_rate", "missing_identity_count"
    }


def test_every_column_has_role_and_synonyms():
    for spec in catalog.load_column_catalog().columns:
        assert spec.data_role, f"{spec.column} has no data_role"
        assert spec.synonyms, f"{spec.column} has no synonyms"


def test_pii_columns_are_flagged():
    for spec in catalog.load_column_catalog().columns:
        assert spec.pii == (spec.column in PII_COLUMNS), spec.column


def test_metric_required_columns_are_real():
    for metric in catalog.load_metric_catalog().metrics:
        unknown = set(metric.required_columns) - EXPECTED_COLUMNS
        assert not unknown, f"{metric.id}: {unknown}"


def test_metric_compatible_dimensions_are_real():
    for metric in catalog.load_metric_catalog().metrics:
        unknown = set(metric.compatible_dimensions) - EXPECTED_COLUMNS
        assert not unknown, f"{metric.id}: {unknown}"


def test_relationships_only_use_real_columns_and_metrics():
    metric_ids = set(catalog.load_metric_catalog().by_id())
    for relation in catalog.load_relationship_catalog().relationships:
        assert not (set(relation.columns) - EXPECTED_COLUMNS), relation.id
        assert not (set(relation.dimensions) - EXPECTED_COLUMNS), relation.id
        assert not (set(relation.metrics) - metric_ids), relation.id


def test_validate_all_catalogs_passes():
    catalog.validate_all_catalogs()


# ═══════════════ Removed-column answerability (24-column contract) ═══════════


@pytest.mark.parametrize(
    "question",
    [
        "Hastaların telefon numaralarını göster.",
        "Telefon bilgisi eksik kaç hasta var?",
        "T.C. kimlik numarası olmayan hastaları listele.",
        "Pasaport bilgisi bulunan hastaların oranı nedir?",
        "Hastaların iletişim bilgileri nelerdir?",
        "GSM bilgisi eksik kaç hasta var?",
        "Kimlik bilgisi doluluk oranı nedir?",
    ],
)
def test_removed_column_questions_are_unanswerable(planner, analyzer, question):
    plan = plan_for(planner, analyzer, question)
    assert plan.answerable is False, question
    assert plan.answerability_reason, question
    # no invented columns anywhere in the plan
    assert not (set(plan.required_columns) & REMOVED_COLUMNS)
    assert not (set(plan.projection) & REMOVED_COLUMNS)
    assert not plan.metrics or not (
        set(plan.metrics)
        & {"missing_phone_count", "phone_completeness_rate", "missing_identity_count"}
    )


def test_removed_column_questions_offer_alternative(analyzer):
    ambiguity = analyzer.detect_ambiguity("Hastaların telefon numaralarını göster.")
    assert ambiguity is not None
    assert "bulunmuyor" in ambiguity.question


@pytest.mark.parametrize(
    "question",
    [
        "Bu ay iptal oranı nedir?",
        "İptal sayısı en yüksek şube hangisi?",
        "Bu aralar hangi şubede iptaller patlamış?",
        "Bu aralar hangi şubede iptaller patlamamış?",
    ],
)
def test_cancel_questions_are_controlled_limitations(planner, analyzer, question):
    """The live view has no 'İptal' status: never build cancelled SQL or metrics."""
    plan = plan_for(planner, analyzer, question)
    assert plan.answerable is False, question
    assert "İptal" in (plan.answerability_reason or "")
    assert not any("cancelled" in m for m in plan.metrics)


def test_cancel_limitation_offers_no_show_alternative(analyzer):
    ambiguity = analyzer.detect_ambiguity("İptal oranı nedir?")
    assert ambiguity is not None
    assert "Gelmedi" in ambiguity.question or "gelmeme" in ambiguity.question


def test_phone_as_channel_still_answerable(planner, analyzer):
    # 'telefon' as an appointment SOURCE channel is not the removed GSM column.
    plan = plan_for(planner, analyzer, "Kaç randevu telefonla verilmiş?")
    assert plan.answerable is True


def test_fewshot_never_returns_removed_column_examples():
    for question, analysis_type, metrics in (
        ("Telefon doluluk oranı nedir?", "ratio", ["cancelled_appointment_rate"]),
        ("Veri kalitesi sorunları neler?", "data_quality", ["invalid_date_range_count"]),
    ):
        for example in examples.retrieve_examples(question, analysis_type, metrics, []):
            assert not (set(example.required_columns) & REMOVED_COLUMNS), example.id
            assert example.expected_plan.answerable


# ═══════════════════════════ Semantic matching tests ═════════════════════════


@pytest.mark.parametrize(
    "question,expected_metric",
    [
        ("kaç randevu var", "appointment_count"),
        ("tekil hasta sayısı", "unique_patient_count"),
        ("gelmeme oranı nedir", "no_show_rate"),
        ("ortalama randevu süresi", "appointment_duration_average"),
        ("hastalar kaç gün önceden randevu alıyor", "appointment_lead_time_average"),
        ("ortalama randevu alma öncesi süre nedir", "appointment_lead_time_average"),
    ],
)
def test_metric_matching(question, expected_metric):
    assert expected_metric in catalog.match_metrics(fold(question))


def test_lead_time_wins_over_duration_for_its_own_phrasing():
    """'appointment_duration_average' used to carry a bare, overly generic
    single-token synonym ("sureler") that trivially matched any question
    mentioning the word "süre" - including a genuine lead-time question
    ("randevu alma öncesi süre" = "the time before taking an appointment"),
    which has no synonym of its own that survives a contiguous-token match
    once "öncesi" sits between "alma" and "süre". Silently answered with
    the wrong metric (2026-07-27, live multi-turn testing) - worse than a
    crash. Regression guard: the WRONG metric must not even be a candidate,
    not just "not first"."""
    matched = catalog.match_metrics(fold("ortalama randevu alma öncesi süre nedir"))
    assert matched == ["appointment_lead_time_average"]
    assert "appointment_duration_average" not in matched


def test_passive_gelinmeyen_rate_maps_to_no_show_rate():
    """Passive voice "gelinmeyen ... oranı" (vs active "gelmeyen") must resolve
    to no_show_rate, not fall back to a plain count (robustness probe
    2026-07-28)."""
    matched = catalog.match_metrics(fold("2024 yılında gelinmeyen randevu oranı"))
    assert "no_show_rate" in matched


@pytest.mark.parametrize(
    ("question", "metric"),
    [
        ("2024 yılında kaç değişik doktor çalışmış", "unique_doctor_count"),
        ("2024 yılında kaç değişik hasta var", "unique_patient_count"),
    ],
)
def test_degisik_maps_to_distinct_count(question, metric):
    """"kaç DEĞİŞİK doktor/hasta" (a synonym of farklı/tekil) must resolve to
    the distinct-count metric, not a plain appointment count (robustness probe
    round 2, 2026-07-28)."""
    matched = catalog.match_metrics(fold(question))
    assert metric in matched
    assert "appointment_count" not in matched


@pytest.mark.parametrize(
    "question",
    [
        "kaç adet hasta var",
        "kaç tane hasta var",
    ],
)
def test_counting_unit_filler_does_not_break_the_patient_metric(question):
    """"adet"/"tane" mean nothing beyond "how many", but phrase matching is
    consecutive, so they split "kaç hasta" and the question fell back to
    appointment_count — answering with a randevu total (live UI testing,
    2026-08-03).

    A modifier between the two ("kaç adet TÜRK hasta var") genuinely leaves the
    catalog with nothing to match; the planner's patient-volume fallback covers
    that case instead — see test_planner_metric_consistency."""
    matched = catalog.match_metrics(fold(question))
    assert "unique_patient_count" in matched
    assert "appointment_count" not in matched


@pytest.mark.parametrize(
    "question",
    [
        "kaç adet randevu var",
        "randevu adedi nedir",
        "gelmeyen randevu adedini ver",
    ],
)
def test_counting_unit_filler_leaves_appointment_wording_alone(question):
    """A synonym that names the counting unit itself ("randevu adedi") must keep
    resolving exactly as before — the filler is skipped only BETWEEN term
    tokens, never as a phrase's own first token."""
    matched = catalog.match_metrics(fold(question))
    assert matched
    assert "unique_patient_count" not in matched


@pytest.mark.parametrize(
    ("question", "metric", "forbidden"),
    [
        # Passive "gelinmiyor"/"en çok gelinmiyor" (no-show) must not fall back
        # to a plain appointment count (robustness probe round 3, 2026-07-29).
        ("2024 hangi 5 bölümde en çok gelinmiyor", "no_show_count", "appointment_count"),
        # "yüzde kaçı protokole dönüştü" / "protokol açılan randevu oranı" ->
        # the conversion RATE, not a count or a plain appointment count.
        ("2024 randevuların yüzde kaçı protokole dönüştü", "protocol_conversion_rate", "appointment_count"),
        ("2024 protokol açılan randevu oranı", "protocol_conversion_rate", "protocol_created_count"),
    ],
)
def test_passive_noshow_and_conversion_phrasings(question, metric, forbidden):
    matched = catalog.match_metrics(fold(question))
    assert metric in matched
    assert forbidden not in matched


@pytest.mark.parametrize(
    ("question", "expected_dim"),
    [
        ("2024 bolm bazinda randevu sayisi", "GenelRandevuBolumAdi"),
        ("2024 doktr bazinda randevu sayisi", "GenelRandevuKaynakAdi"),
    ],
)
def test_single_char_typo_in_grouping_word_recovers_dimension(question, expected_dim):
    """A one-letter typo in the grouping word ("bolm/doktr bazında") must not
    silently collapse the breakdown to a scalar total — a one-insertion/
    deletion fuzzy match recovers the dimension (robustness probe round 4,
    2026-07-29)."""
    view = ViewMetadata(name="dbo.vw_RandevuRaporu", columns=[])
    plan = QueryPlanner().build_plan(question, QueryAnalyzer().analyze(question), tables=[], views=[view])
    assert expected_dim in plan.dimensions


def test_substitution_typo_does_not_false_match_a_dimension():
    """Substitutions are deliberately NOT tolerated — "süre bazında" must not
    fuzzy-match "şube" (SubeAdi)."""
    view = ViewMetadata(name="dbo.vw_RandevuRaporu", columns=[])
    plan = QueryPlanner().build_plan(
        "2024 sure bazinda randevu", QueryAnalyzer().analyze("2024 sure bazinda randevu"),
        tables=[], views=[view],
    )
    assert "SubeAdi" not in plan.dimensions


@pytest.mark.parametrize(
    ("question", "predicate"),
    [
        ("2024 yılında 40 yaş üstü hastaların randevu sayısı", "> 40"),
        ("2024 yılında 18 yaşından küçük hastaların randevu sayısı", "< 18"),
        ("2024 yılında 30-40 yaş arası hasta randevuları", "BETWEEN 30 AND 40"),
        ("2024 yılında 65 yaş ve üzeri hasta sayısı", ">= 65"),
    ],
)
def test_age_range_filter_is_a_where_predicate_not_a_breakdown(question, predicate):
    """"40 yaş üstü" filters (WHERE on derived age), it does NOT bucket by age
    decade. "yaş" is a DogumTarihi synonym so it otherwise became a GROUP BY
    dimension (#4 ileri filtreler, 2026-07-29)."""
    from app.database_intelligence.models import ViewMetadata
    from app.services.deterministic_sql_builder import DeterministicSQLBuilder

    view = ViewMetadata(name="dbo.vw_RandevuRaporu", columns=[])
    plan = QueryPlanner().build_plan(question, QueryAnalyzer().analyze(question), [], views=[view])
    assert "DogumTarihi" not in plan.dimensions
    built = DeterministicSQLBuilder().build(plan)
    assert hasattr(built, "sql"), getattr(built, "reason", None)
    assert f"DATEDIFF(year, DogumTarihi, GETDATE()) {predicate}" in built.sql
    # A genuine age-group breakdown must still bucket by decade.
    grp = "2024 yılında yaş gruplarına göre randevu dağılımı"
    grp_plan = QueryPlanner().build_plan(grp, QueryAnalyzer().analyze(grp), [], views=[view])
    assert "DogumTarihi" in grp_plan.dimensions


def test_her_ay_triggers_monthly_granularity():
    """"her ay kaç randevu" is a monthly breakdown, not a single scalar count
    (robustness probe 2026-07-28)."""
    assert catalog.match_granularity(fold("2024 yılında her ay kaç randevu olmuş")) == "month"


@pytest.mark.parametrize(
    "question",
    [
        "randevu tarihi ile oluşturulma tarihi arasındaki ortalama gün farkı nedir",
        "randevu ile oluşturulma arasında kaç gün geçiyor",
        "oluşturulma tarihi arasındaki ortalama süre",
    ],
)
def test_two_date_day_difference_maps_to_lead_time(question):
    """"İki tarih arasındaki gün farkı" phrasings (randevu tarihi vs oluşturulma
    tarihi) must resolve to appointment_lead_time_average — previously matched
    nothing and fell back to COUNT(*) (live 2026-07-28)."""
    matched = catalog.match_metrics(fold(question))
    assert "appointment_lead_time_average" in matched
    assert "appointment_count" not in matched


@pytest.mark.parametrize(
    "question,expected_dimension",
    [
        ("şube bazında dağılım", "SubeAdi"),
        ("bölümlere göre sayılar", "GenelRandevuBolumAdi"),
        ("kaynaklara göre randevular", "GenelRandevuKaynakAdi"),
        ("doktor bazında randevu sayısı", "DoktorId"),
    ],
)
def test_dimension_matching(question, expected_dimension):
    assert expected_dimension in catalog.match_dimensions(fold(question))


def test_period_comparison_pattern():
    assert catalog.match_pattern(fold("bu ay ile geçen ay karşılaştır"), 2) == "period_comparison"


def test_previous_month_phrase_detects_comparison():
    comparisons = catalog.detect_period_comparison(fold("geçen aya göre arttı mı"), 1)
    assert comparisons == ["current_period_vs_previous_period"]


def test_ranking_directions():
    assert catalog.ranking_direction(fold("en yüksek şube")) == "DESC"
    assert catalog.ranking_direction(fold("en düşük şube")) == "ASC"


def test_suffix_tolerant_matching():
    # plural/possessive suffixes must not break matching
    assert "no_show_rate" in catalog.match_metrics(fold("gelmeme oranları nedir"))
    assert "SubeAdi" in catalog.match_dimensions(fold("şubelerin randevuları"))


def test_verified_metric_display_names_are_directly_matchable():
    """The public catalog name is itself valid user vocabulary."""
    for metric in catalog.load_metric_catalog().metrics:
        if metric.status == "requires_verified_mapping":
            continue
        matched = catalog.match_metrics(fold(metric.name))
        if (
            metric.formula_type == "count_rows_grouped"
            and metric.formula == "COUNT(*)"
            and metric.fixed_dimension
        ):
            assert metric.id in matched or "appointment_count" in matched
        else:
            assert metric.id in matched, metric.id


@pytest.mark.parametrize(
    "question",
    [
        "Protokol durumuna göre tamamlanma nedir?",
        "Hasta kimliği uyuşmayan kayıt sayısı kaç?",
        "Protokol durum tutarsızlığını göster.",
    ],
)
def test_unverified_metric_mapping_requests_clarification(question):
    ambiguity = QueryAnalyzer().detect_ambiguity(question)

    assert ambiguity is not None
    assert ambiguity.matched_phrase == "unverified_metric_mapping"


@pytest.mark.parametrize(
    "question",
    [
        "En fazla randevusu olan bölüm hangisi",
        "En fazla randevusu olan doktor kim",
        "2025 yılında 50'den fazla randevusu olan doktorları sırala",
    ],
)
def test_generic_fazla_phrasing_does_not_match_repeat_patient_count(question):
    """repeat_patient_count's synonym list used to include the bare, generic
    "fazla randevusu olan" (missing the "birden" qualifier that the real
    synonyms "birden fazla randevusu olan"/"birden çok randevusu olan" all
    have) - a substring of THREE unrelated constructs: the superlative
    ranking idiom "EN fazla randevusu olan X" (the single most common Turkish
    ranking phrase in this whole domain), a numeric threshold ("50'DEN fazla
    randevusu olan"), and the genuine repeat-patient concept ("BİRDEN fazla
    randevusu olan"). Silently corrupted metric resolution for the first two
    into the wrong metric entirely (2026-07-27, live UI testing: "En fazla
    randevusu olan bölüm hangisi" - the most common ranking question in this
    domain - resolved to repeat_patient_count instead of appointment_count)."""
    matched = catalog.match_metrics(fold(question))
    assert "repeat_patient_count" not in matched


def test_genuine_repeat_patient_phrasing_still_matches():
    """Regression guard: removing the overly-generic bare synonym must not
    affect the genuine "birden fazla" (more than one) repeat-patient
    phrasings that already carry their own qualifier."""
    for question in (
        "Birden fazla randevusu olan hastaları göster",
        "Birden fazla randevu alan hastalar kim",
        "Birden çok randevusu olan hastaları listele",
    ):
        assert "repeat_patient_count" in catalog.match_metrics(fold(question))


def test_specialized_cross_branch_repeat_suppresses_generic_repeat_metric():
    matched = catalog.match_metrics(
        fold("Şube adı bazında farklı şubelerde tekrar eden hasta sayısını göster")
    )

    assert matched == ["cross_branch_repeat_patient_count"]


# ═══════════════ Multi-metric preservation (match_metrics span-overlap) ══════


def test_independent_count_and_rate_both_survive():
    matched = catalog.match_metrics(fold("Randevu sayısı ve gerçekleşme oranını göster"))
    assert "appointment_count" in matched
    assert "completed_appointment_rate" in matched


def test_independent_count_and_no_show_rate_both_survive():
    matched = catalog.match_metrics(fold("Randevu sayısı ve gelmeme oranını göster"))
    assert "appointment_count" in matched
    assert "no_show_rate" in matched


def test_count_and_duration_both_survive():
    matched = catalog.match_metrics(fold("Randevu sayısı ve ortalama randevu süresini göster"))
    assert "appointment_count" in matched
    assert "appointment_duration_average" in matched


def test_rate_and_duration_both_survive():
    matched = catalog.match_metrics(
        fold("Gerçekleşme oranı ve ortalama randevu süresini karşılaştır")
    )
    assert "completed_appointment_rate" in matched
    assert "appointment_duration_average" in matched


def test_three_or_more_compatible_metrics_all_survive():
    matched = catalog.match_metrics(
        fold(
            "Şubelere göre randevu sayısı, gerçekleşme oranı ve ortalama randevu "
            "süresini karşılaştır"
        )
    )
    expected_metrics = {
        "appointment_count",
        "completed_appointment_rate",
        "appointment_duration_average",
    }
    assert expected_metrics <= set(matched)
    # No duplicate canonical count: appointments_per_branch (same COUNT(*)
    # measure, fixed_dimension=SubeAdi) must not co-exist with appointment_count.
    assert "appointments_per_branch" not in matched


# ══════════════════ Duplicate canonical count metric dedup ═══════════════════


def test_branch_count_request_produces_single_count_metric():
    matched = catalog.match_metrics(fold("Şubelere göre randevu sayısını göster"))
    assert matched == ["appointment_count"]


def test_doctor_count_request_produces_single_count_metric():
    matched = catalog.match_metrics(fold("Doktor bazında randevu sayısını göster"))
    assert matched == ["appointment_count"]


def test_department_count_request_produces_single_count_metric():
    matched = catalog.match_metrics(fold("Bölümlere göre randevu sayısını göster"))
    assert matched == ["appointment_count"]


def test_fixed_dimension_variant_alone_is_kept_when_appointment_count_not_matched():
    # A phrase that ONLY matches the fixed-dimension synonym (not "randevu
    # sayisi" itself) legitimately keeps that one metric — nothing to dedup
    # against.
    matched = catalog.match_metrics(fold("hastane bazinda randevu"))
    assert matched == ["appointments_per_branch"]


def test_grouped_dimension_request_never_produces_two_count_metric_ids(planner, analyzer):
    plan = plan_for(planner, analyzer, "Şubelere göre randevu sayısını karşılaştır.")
    count_variants = ("appointment_count", "appointments_per_branch")
    count_metrics = [m for m in plan.metrics if m in count_variants]
    assert count_metrics == ["appointment_count"]


def test_single_concept_still_collapses_to_status_metric():
    # Same mention ("gerçekleşen randevuların sayısı") — appointment_count must
    # still be suppressed in favor of the more specific conditional metric.
    matched = catalog.match_metrics(fold("Gerçekleşen randevuların sayısı kaç?"))
    assert "completed_appointment_count" in matched
    assert "appointment_count" not in matched


def test_single_concept_rate_and_count_collapse_when_same_mention():
    matched = catalog.match_metrics(fold("Gelmeyen randevu sayısı ve oranı nedir?"))
    # "gelmeyen randevu sayısı" and "oranı" refer to the same no-show concept —
    # this remains a single-metric collapse, not two independent metrics.
    assert "no_show_rate" in matched or "no_show_count" in matched


# ═══════════════════════ Planner: planned_metrics/dimensions ═════════════════


def test_planned_metrics_mirrors_metrics_list(planner, analyzer):
    plan = plan_for(
        planner,
        analyzer,
        "Şubelere göre randevu sayısı ve gerçekleşme oranını karşılaştır",
    )
    assert set(plan.metrics) == {m.metric_id for m in plan.planned_metrics}
    for planned in plan.planned_metrics:
        assert planned.aggregation_type
        assert planned.source_columns


def test_planned_dimensions_resolves_canonical_names(planner, analyzer):
    plan = plan_for(planner, analyzer, "Şubelere göre randevu sayısını göster")
    assert plan.planned_dimensions
    assert any(d.canonical_name == "branch" for d in plan.planned_dimensions)


def test_multi_metric_plan_keeps_all_three_metrics(planner, analyzer):
    plan = plan_for(
        planner,
        analyzer,
        "Şubelere göre randevu sayısı, gerçekleşme oranı ve ortalama randevu "
        "süresini karşılaştır",
    )
    expected_metrics = {
        "appointment_count",
        "completed_appointment_rate",
        "appointment_duration_average",
    }
    assert expected_metrics <= set(plan.metrics)
    assert plan.answerable


# ═══════════════════════════════ QueryPlan tests ═════════════════════════════


def test_count_question_produces_count_metric(planner, analyzer):
    plan = plan_for(planner, analyzer, "Bu ay kaç randevu var?")
    assert "appointment_count" in plan.metrics
    assert plan.answerable


def test_ratio_question_produces_numerator_and_denominator(planner, analyzer):
    plan = plan_for(planner, analyzer, "Şubelere göre gelmeme oranları nedir?")
    assert plan.numerator == "no_show_count"
    assert plan.denominator == "appointment_count"
    assert "SubeAdi" in plan.dimensions


def test_scalar_status_count_with_department_has_no_stale_projection(planner, analyzer):
    """'Kardiyoloji bölümünde kaç tanesi gerçekleşti?' is a single scalar
    count (one row, no GROUP BY) - the bare 'bölüm' mention used to leave a
    GenelRandevuBolumAdi display-concept column in plan.projection even
    though the deterministic SQL never selects it (nothing to GROUP BY it
    against), so PlanComplianceValidator rejected the SQL as missing that
    projection column and the whole answer silently failed
    ("Yanıt Oluşturulamadı", 2026-07-24 real UI bug report)."""
    plan = plan_for(planner, analyzer, "Kardiyoloji bölümünde kaç tanesi gerçekleşti?")
    assert plan.department_filter == "Kardiyoloji"
    assert plan.metrics == ["completed_appointment_count"]
    assert plan.dimensions == []
    assert plan.projection == []


@pytest.mark.parametrize(
    "question",
    [
        "Kadın erkek oranını hesapla",
        "Cinsiyet oranı nedir?",
    ],
)
def test_gender_ratio_with_no_matched_metric_falls_back_to_distribution(
    planner, analyzer, question
):
    """'X orani' text pattern-matches to analysis_type 'ratio' purely from the
    word 'orani', independent of whether a specific ratio metric (numerator/
    denominator) exists for it. There is no percent-of-total metric for a
    two-category demographic split like gender - previously this left
    plan.metrics empty (nothing to compute, unanswerable in practice) instead
    of falling back to a groupable distribution over CinsiyetId (2026-07-24)."""
    plan = plan_for(planner, analyzer, question)
    assert plan.answerable
    assert plan.analysis_type == "distribution"
    assert plan.metrics
    assert "CinsiyetId" in plan.dimensions


def test_ratio_with_no_dimension_falls_back_to_count(planner, analyzer):
    """A '<value>in payi/orani' phrasing with no grouping dimension resolved
    (e.g. a named channel/value rather than 'X'e gore') used to reach the SQL
    builder as analysis_type 'ratio' with only the generic appointment_count
    fallback metric and no numerator/denominator - PlanComplianceValidator
    then rejected the SQL for missing a NULLIF division-by-zero guard that
    was never generated, producing SAFE_ERROR (2026-07-24 live multi-turn
    testing: "Online randevularin toplam icindeki payi nedir"). With no
    dimension to group by either, this must degrade to a plain scalar count
    instead of distribution."""
    plan = plan_for(planner, analyzer, "Online randevuların toplam içindeki payı nedir")
    assert plan.analysis_type == "count"
    assert plan.metrics == ["appointment_count"]
    assert plan.dimensions == []


def test_percentage_plan_without_division_does_not_require_nullif(planner, analyzer):
    """A 'percentage' analysis type whose plan carries no numerator/denominator
    renders as a plain COUNT(*) — with no division in the SQL there is nothing
    for NULLIF to protect, so compliance must not reject it. This fired as
    "Yanıt Oluşturulamadı" on the follow-up "aradaki farkı yüzde ve adet olarak
    göster" (Codex live UI testing, 2026-07-31)."""
    from app.planning.compliance import PlanComplianceValidator

    plan = plan_for(planner, analyzer, "aradaki farkı yüzde ve adet olarak göster")
    assert plan.analysis_type == "percentage"
    assert not (plan.numerator and plan.denominator)

    sql = "SELECT COUNT(*) AS appointment_count\nFROM dbo.vw_RandevuRaporu;"
    result = PlanComplianceValidator().check(sql, plan)
    assert not any("NULLIF" in issue for issue in result.missing), result.missing


def test_ratio_sql_that_divides_still_requires_nullif(planner, analyzer):
    """The guard still protects a real division."""
    from app.planning.compliance import PlanComplianceValidator

    plan = plan_for(planner, analyzer, "Gerçekleşme oranı nedir?")
    unprotected = (
        "SELECT 100.0 * SUM(CASE WHEN RandevuDurumu = N'Gerçekleşti' THEN 1 ELSE 0 END) "
        "/ COUNT(*) AS completed_rate FROM dbo.vw_RandevuRaporu;"
    )
    result = PlanComplianceValidator().check(unprotected, plan)
    assert any("NULLIF" in issue for issue in result.missing)


def test_named_ratio_metric_is_unaffected_by_distribution_fallback(planner, analyzer):
    """A phrase that DOES match a specific ratio metric keeps analysis_type
    'ratio' with its numerator/denominator - only the empty-metric case
    downgrades to distribution."""
    plan = plan_for(planner, analyzer, "Gerçekleşme oranı nedir?")
    assert plan.analysis_type == "ratio"
    assert plan.numerator and plan.denominator


def test_group_question_produces_dimension(planner, analyzer):
    plan = plan_for(planner, analyzer, "Bölümlere göre randevu sayılarını göster")
    assert "GenelRandevuBolumAdi" in plan.dimensions


def test_trend_question_produces_time_granularity(planner, analyzer):
    plan = plan_for(planner, analyzer, "Aylık randevu trendini göster")
    assert plan.grouping_granularity == "month"


def test_comparison_question_plans_two_periods(planner, analyzer):
    plan = plan_for(planner, analyzer, "Geçen aya göre randevu sayısı arttı mı?")
    assert plan.comparisons == ["current_period_vs_previous_period"]


def test_duration_question_uses_duration_metric(planner, analyzer):
    plan = plan_for(planner, analyzer, "Ortalama randevu süresi kaç dakika?")
    assert "appointment_duration_average" in plan.metrics
    assert "RandevuSuresi" in plan.required_columns


def test_unanswerable_question_returns_false(planner, analyzer):
    plan = plan_for(planner, analyzer, "Hastaların tanıları nedir?")
    assert plan.answerable is False
    assert plan.answerability_reason


def test_doctor_name_question_does_not_invent_column(planner, analyzer):
    plan = plan_for(planner, analyzer, "Doktorların adları nelerdir?")
    assert plan.answerable is False
    assert "DoktorAdi" not in plan.required_columns
    assert "DoktorAdi" not in plan.projection


def test_ambiguous_question_requires_clarification(analyzer):
    ambiguity = analyzer.detect_ambiguity("En başarılı bölüm hangisi?")
    assert ambiguity is not None
    assert ambiguity.options


def test_age_group_question_derives_from_birth_date(planner, analyzer):
    plan = plan_for(planner, analyzer, "Yaş gruplarına göre hasta dağılımı nedir?")
    assert any("DogumTarihi" in derivation for derivation in plan.derived_calculations)
    assert "DogumTarihi" in plan.required_columns


def test_age_group_sql_buckets_by_decade_not_raw_birth_date(planner, analyzer):
    """The planner adds DogumTarihi to `dimensions` and a human-readable
    derivation note ("10'luk yaş grupları"), but nothing consumed that note
    - GROUP BY grouped the raw birth date itself, one row per distinct date
    (up to 1000) instead of one row per decade bucket (2026-07-27, live
    multi-turn testing)."""
    from app.planning.compliance import PlanComplianceValidator
    from app.services.deterministic_sql_builder import DeterministicSQLBuilder

    plan = plan_for(planner, analyzer, "2025'te yaş gruplarına göre randevu dağılımını göster")
    built = DeterministicSQLBuilder().build(plan)

    assert hasattr(built, "sql"), getattr(built, "reason", None)
    assert "GROUP BY (DATEDIFF(year, DogumTarihi, GETDATE()) / 10) * 10" in built.sql
    assert "AS age_group" in built.sql
    assert built.expected_aliases[0] == "age_group"
    compliance = PlanComplianceValidator().check(
        built.sql, plan, expected_aliases=built.expected_aliases, deterministic=True
    )
    assert compliance.compliant, (compliance.missing, compliance.missing_metrics)


def test_direct_birth_date_grouping_is_not_bucketed_by_age():
    """Regression guard: "doğum tarihine göre hasta dağılımı" genuinely asks
    to group by the raw birth date itself - no age-group derivation note is
    attached, so bucketing it too would answer a different question."""
    from app.services.deterministic_sql_builder import DeterministicSQLBuilder
    from app.services.query_analyzer import QueryAnalyzer as _Analyzer
    from app.planning.planner import QueryPlanner as _Planner
    from app.database_intelligence.models import ViewMetadata

    q = "doğum tarihine göre hasta dağılımı"
    view = ViewMetadata(name="dbo.vw_RandevuRaporu", columns=[])
    analysis = _Analyzer().analyze(q)
    plan = _Planner().build_plan(q, analysis, tables=[], views=[view])

    assert plan.derived_calculations == []
    built = DeterministicSQLBuilder().build(plan)
    assert hasattr(built, "sql"), getattr(built, "reason", None)
    assert "GROUP BY DogumTarihi" in built.sql
    assert "DATEDIFF(year," not in built.sql


def test_weekday_weekend_breakdown_derives_a_day_type_dimension(planner, analyzer):
    """"hafta içi ve hafta sonu ... karşılaştır" groups by a derived weekday/
    weekend dimension instead of returning a single total (live 2026-07-28:
    the day-type split was ignored)."""
    from app.services.deterministic_sql_builder import DeterministicSQLBuilder
    from app.planning.compliance import PlanComplianceValidator

    plan = plan_for(
        planner, analyzer, "2024 yılında hafta içi ve hafta sonu randevu sayısını karşılaştır"
    )
    assert "DayType" in plan.dimensions
    assert plan.metrics == ["appointment_count"]
    built = DeterministicSQLBuilder().build(plan)
    assert hasattr(built, "sql"), getattr(built, "reason", None)
    # DATEFIRST/locale-independent weekend test (Mon=0..Sun=6, >= 5 == weekend).
    assert "DATEDIFF(day, '19000101'" in built.sql
    assert "AS day_type" in built.sql
    assert "Hafta Sonu" in built.sql and "Hafta İçi" in built.sql
    compliance = PlanComplianceValidator().check(
        built.sql, plan, expected_aliases=built.expected_aliases, deterministic=True
    )
    assert compliance.compliant, (compliance.missing, compliance.missing_metrics)


def test_weekly_granularity_is_not_a_day_type_breakdown(planner, analyzer):
    """Regression guard: "haftalık randevu trendi" is a weekly time series, not
    a weekday/weekend split."""
    plan = plan_for(planner, analyzer, "2024 yılında haftalık randevu trendini göster")
    assert "DayType" not in plan.dimensions


def test_required_columns_are_always_real(planner, analyzer):
    plan = plan_for(planner, analyzer, "Şubelere göre iptal oranları nedir?")
    assert set(plan.required_columns) <= EXPECTED_COLUMNS


# ═══════════════════════════ Golden dataset tests ════════════════════════════


@pytest.fixture(scope="module")
def dataset():
    return examples.load_golden_dataset()


def test_dataset_has_at_least_250_questions(dataset):
    assert len(dataset.questions) >= 250


def test_dataset_ids_unique(dataset):
    ids = [example.id for example in dataset.questions]
    assert len(ids) == len(set(ids))


def test_dataset_category_distribution(dataset):
    counts = Counter(example.id.rsplit("-", 1)[0] for example in dataset.questions)
    minimums = {
        "COUNT": 30, "DIST": 25, "RANK": 25, "RATE": 33, "TREND": 30,
        "COMP": 30, "DUR": 25, "CROSS": 20, "REPEAT": 15, "DQ": 12,
        "UNANS": 15, "CLAR": 10,
    }
    for prefix, minimum in minimums.items():
        assert counts[prefix] >= minimum, f"{prefix}: {counts[prefix]} < {minimum}"


def test_dataset_uses_only_real_columns_and_metrics(dataset):
    metric_ids = set(catalog.load_metric_catalog().by_id())
    for example in dataset.questions:
        assert not (set(example.metrics) - metric_ids), example.id
        assert not (set(example.dimensions) - EXPECTED_COLUMNS), example.id
        assert not (set(example.required_columns) - EXPECTED_COLUMNS), example.id


def test_dataset_has_unanswerable_and_clarification_examples(dataset):
    unanswerable = [e for e in dataset.questions if not e.expected_plan.answerable]
    clarification = [e for e in dataset.questions if e.expected_plan.clarification_required]
    assert len(unanswerable) >= 15
    assert len(clarification) >= 10


def test_dataset_near_duplicate_rate_is_acceptable(dataset):
    from app.semantics.catalog import stem_text

    stems = [frozenset(stem_text(e.question).split()) for e in dataset.questions]
    duplicates = len(stems) - len(set(stems))
    assert duplicates / len(stems) <= 0.05, f"{duplicates} near-duplicate questions"


def test_dataset_answerable_questions_have_metrics(dataset):
    for example in dataset.questions:
        if example.expected_plan.answerable and not example.expected_plan.clarification_required:
            assert example.metrics, example.id
            assert example.required_columns, example.id


# ═══════════════════════════ Few-shot retrieval tests ════════════════════════


def test_ratio_question_retrieves_ratio_examples():
    retrieved = examples.retrieve_examples(
        "Bölümlere göre iptal oranı nedir?", "ratio", ["cancelled_appointment_rate"],
        ["GenelRandevuBolumAdi"], has_date_filter=False,
    )
    assert retrieved
    assert all(e.analysis_type in ("ratio", "percentage") for e in retrieved)


def test_trend_question_retrieves_trend_examples():
    retrieved = examples.retrieve_examples(
        "Aylık randevu trendi nasıl?", "time_trend", ["monthly_appointment_count"], [],
    )
    assert retrieved
    assert retrieved[0].analysis_type == "time_trend"


def test_retrieval_returns_at_most_three_unique_examples():
    retrieved = examples.retrieve_examples(
        "Şube bazında randevu sayısı", "count", ["appointment_count"], ["SubeAdi"],
    )
    ids = [e.id for e in retrieved]
    assert len(ids) <= examples.MAX_EXAMPLES
    assert len(ids) == len(set(ids))


def test_retrieval_is_deterministic():
    args = ("İptal oranını göster", "ratio", ["cancelled_appointment_rate"], [])
    first = [e.id for e in examples.retrieve_examples(*args)]
    second = [e.id for e in examples.retrieve_examples(*args)]
    assert first == second


def test_retrieval_never_returns_unanswerable_or_clarification():
    retrieved = examples.retrieve_examples(
        "Randevu sayısı nedir", "count", ["appointment_count"], [],
    )
    for example in retrieved:
        assert example.expected_plan.answerable
        assert not example.expected_plan.clarification_required


def test_examples_appear_in_prompt_section(planner, analyzer):
    plan = plan_for(planner, analyzer, "Şubelere göre gelmeme oranlarını göster")
    assert plan.matched_examples
    rendered = format_plan_for_prompt(plan)
    assert "Similar verified questions" in rendered


# ═══════════════════════════ Result validation tests ═════════════════════════


def _result(columns, rows):
    from datetime import UTC, datetime

    return QueryResult(
        columns=columns,
        rows=rows,
        row_count=len(rows),
        execution_time_ms=1.0,
        success=True,
        executed_at=datetime.now(UTC),
        database_provider="mssql",
    )


def test_percentage_out_of_range_is_flagged(planner, analyzer):
    plan = plan_for(planner, analyzer, "Gelmeme oranı nedir?")
    report = ResultValidator().validate(
        _result(["iptal_orani"], [{"iptal_orani": 140.0}]), plan=plan
    )
    assert any(f.check == "percentage_range" for f in report.findings)
    assert not report.valid


def test_negative_count_is_flagged():
    report = ResultValidator().validate(
        _result(["randevu_sayisi"], [{"randevu_sayisi": -3}])
    )
    assert any(f.check == "non_negative_count" for f in report.findings)


def test_empty_result_is_flagged():
    report = ResultValidator().validate(_result(["a"], []))
    assert any(f.check == "empty_result" for f in report.findings)
    assert report.valid  # warning only


def test_non_chronological_trend_is_flagged(planner, analyzer):
    plan = plan_for(planner, analyzer, "Aylık randevu trendini göster")
    report = ResultValidator().validate(
        _result(["ay", "adet"], [{"ay": "2026-03", "adet": 5}, {"ay": "2026-01", "adet": 9}]),
        plan=plan,
    )
    assert any(f.check == "chronological_order_for_trend" for f in report.findings)


def test_missing_division_protection_is_flagged(planner, analyzer):
    plan = plan_for(planner, analyzer, "Gelmeme oranı nedir?")
    report = ResultValidator().validate(
        _result(["oran"], [{"oran": 10.0}]),
        plan=plan,
        sql="SELECT 100.0 * a / b FROM dbo.vw_RandevuRaporu;",
    )
    assert any(f.check == "division_by_zero_protection" for f in report.findings)


def test_valid_result_produces_no_error_findings():
    report = ResultValidator().validate(
        _result(["SubeAdi", "adet"], [{"SubeAdi": "Merkez", "adet": 12}])
    )
    assert report.valid


# ═══════════════════════════ Regression accuracy ═════════════════════════════


def test_planner_regression_accuracy(planner, analyzer, dataset):
    """Runs the golden questions through the real planner and enforces accuracy targets."""
    analysis_hits = analysis_total = 0
    metric_hits = metric_total = 0
    dimension_hits = dimension_total = 0
    date_hits = date_total = 0
    answerability_hits = answerability_total = 0
    clarification_hits = clarification_total = 0

    # An expected analysis type accepts analytically equivalent resolutions:
    # the SQL shape is the same or the difference is presentational only.
    equivalent_analysis = {
        "count": {"count", "distinct_count"},
        "distinct_count": {"distinct_count", "count"},
        "ranking": {"ranking", "top_n", "bottom_n", "average", "duration_analysis"},
        "top_n": {"top_n", "ranking"},
        "bottom_n": {"bottom_n", "ranking"},
        "ratio": {"ratio", "percentage", "conversion"},
        "percentage": {"percentage", "ratio", "conversion"},
        "conversion": {"conversion", "ratio", "percentage"},
        "distribution": {"distribution", "count", "cross_analysis", "time_trend"},
        "cross_analysis": {
            "cross_analysis", "distribution", "ranking", "ratio",
            "time_trend", "duration_analysis", "count",
        },
        "period_comparison": {
            "period_comparison", "percentage_change", "comparison", "time_trend",
        },
        "percentage_change": {"percentage_change", "period_comparison", "comparison"},
        "duration_analysis": {
            "duration_analysis", "average", "minimum", "maximum",
            "lead_time_analysis", "count",
        },
        "average": {"average", "duration_analysis"},
        "minimum": {"minimum", "duration_analysis"},
        "maximum": {"maximum", "duration_analysis"},
        "time_trend": {"time_trend", "distribution", "trend", "ratio"},
        "lead_time_analysis": {"lead_time_analysis", "duration_analysis"},
        "repeat_behavior": {
            "repeat_behavior", "count", "distinct_count", "ranking", "top_n",
            "ratio", "average", "list", "time_trend",
        },
        "data_quality": {"data_quality", "count", "ratio", "duration_analysis"},
    }

    # Metrics in the same family answer the same business question at a
    # different granularity/orientation (count vs bucketed count vs per-X).
    metric_families: dict[str, str] = {}
    for volume_metric in (
        "appointment_count", "daily_appointment_count", "weekly_appointment_count",
        "monthly_appointment_count", "daily_average_appointment_count",
        "appointments_per_type", "appointments_per_source", "appointments_per_department",
        "appointments_per_branch", "appointments_per_doctor",
    ):
        metric_families[volume_metric] = "volume"
    for duration_metric in (
        "appointment_duration_average", "appointment_duration_minimum",
        "appointment_duration_maximum", "actual_duration_from_dates",
        "duration_difference", "duration_mismatch_count",
    ):
        metric_families[duration_metric] = "duration"
    for repeat_metric in ("appointments_per_patient", "repeat_patient_count"):
        metric_families[repeat_metric] = "repeat"
    for lead_metric in (
        "appointment_lead_time_average", "same_day_booking_count", "same_day_booking_rate",
    ):
        metric_families[lead_metric] = "lead_time"

    def metric_family(metric_id: str) -> str:
        return metric_families.get(metric_id, metric_id.rsplit("_", 1)[0])

    for example in dataset.questions:
        expects_clarification = example.expected_plan.clarification_required
        clarification_total += 1
        ambiguity = analyzer.detect_ambiguity(example.question)
        needs_clarification = ambiguity is not None
        if expects_clarification == needs_clarification or (
            not expects_clarification and not example.expected_plan.answerable
        ):
            clarification_hits += 1
        if expects_clarification:
            continue

        plan = plan_for(planner, analyzer, example.question)

        answerability_total += 1
        if plan.answerable == example.expected_plan.answerable:
            answerability_hits += 1
        if not example.expected_plan.answerable:
            continue

        if example.analysis_type:
            analysis_total += 1
            allowed = equivalent_analysis.get(example.analysis_type, {example.analysis_type})
            if plan.analysis_type in allowed:
                analysis_hits += 1

        if example.metrics:
            metric_total += 1
            expected_families = {metric_family(m) for m in example.metrics}
            plan_families = {metric_family(m) for m in plan.metrics}
            if set(example.metrics) & set(plan.metrics) or expected_families & plan_families:
                metric_hits += 1

        if example.dimensions:
            dimension_total += 1
            if set(example.dimensions) & set(plan.dimensions) or set(
                example.dimensions
            ) <= set(plan.required_columns):
                dimension_hits += 1

        if example.date_context:
            date_total += 1
            if plan.date_filters or plan.comparisons:
                date_hits += 1

    def pct(hits, total):
        return 100.0 * hits / total if total else 100.0

    analysis_accuracy = pct(analysis_hits, analysis_total)
    metric_accuracy = pct(metric_hits, metric_total)
    dimension_accuracy = pct(dimension_hits, dimension_total)
    date_accuracy = pct(date_hits, date_total)
    answerability_accuracy = pct(answerability_hits, answerability_total)
    clarification_accuracy = pct(clarification_hits, clarification_total)

    summary = (
        f"analysis_type={analysis_accuracy:.1f}% ({analysis_hits}/{analysis_total}) "
        f"metric={metric_accuracy:.1f}% ({metric_hits}/{metric_total}) "
        f"dimension={dimension_accuracy:.1f}% ({dimension_hits}/{dimension_total}) "
        f"date={date_accuracy:.1f}% ({date_hits}/{date_total}) "
        f"answerability={answerability_accuracy:.1f}% ({answerability_hits}/{answerability_total}) "
        f"clarification={clarification_accuracy:.1f}% ({clarification_hits}/{clarification_total})"
    )
    print(f"\nPlanner regression accuracy: {summary}")

    assert answerability_total >= 50  # regression must cover at least 50 questions
    assert analysis_accuracy >= 90.0, summary
    assert metric_accuracy >= 85.0, summary
    assert dimension_accuracy >= 90.0, summary
    assert answerability_accuracy >= 95.0, summary
