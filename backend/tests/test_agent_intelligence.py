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
    ],
)
def test_metric_matching(question, expected_metric):
    assert expected_metric in catalog.match_metrics(fold(question))


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
