"""Analytical reasoning: implicit intent -> explicit query strategy (AI-INTELLIGENCE-008).

Turns vague, analyst-style Turkish wording ("iptaller patlamış", "işler nasıl
gidiyor", "son dakika alanlar") into an explicit, deterministic
AnalyticalStrategy: goal, analysis type, current/baseline periods, cohort
definition, KPI set, and minimum sample size. Every default the agent picks is
recorded as a human-readable assumption so the final answer can state it.

Fully deterministic — no LLM calls. The strategy augments the QueryPlan; it
never replaces the catalog-driven resolution.
"""

import logging

from pydantic import BaseModel, Field

from app.semantics.catalog import _term_in  # deterministic suffix-tolerant matching

logger = logging.getLogger(__name__)

# ── Assumption policy (single source of truth, user-visible wording) ─────────

ASSUMPTION_POLICY: dict[str, str] = {
    "bu_aralar": "'Bu aralar' son 30 gün olarak yorumlandı.",
    "onceki_donem": "Karşılaştırma tabanı: önceki eşit 30 günlük dönem.",
    "son_dakika": (
        "'Son dakika' randevunun başlangıcına 24 saatten az kala alınması olarak "
        "yorumlandı (BaslangicTarihi - CreatedDate < 24 saat)."
    ),
    "cok_fark": (
        "'Çok fark' metrik dağılımının uçları ve yoğunlaşması üzerinden değerlendirildi."
    ),
    "isler_nasil": (
        "'İşler nasıl gidiyor' temel KPI'ların (randevu hacmi, gerçekleşme, gelmeme, "
        "tekil hasta) dönem karşılaştırması olarak yorumlandı."
    ),
    "gecen_sene": "Karşılaştırma tabanı: geçen yılın aynı dönemi.",
    "kontrol": (
        "'Kontrole gelenler' kontrol tipindeki randevular (RandevuTipiAdi) olarak yorumlandı."
    ),
    "min_sample": (
        "20 kayıttan küçük gruplar düşük örneklem olarak işaretlendi; oranları "
        "yanıltıcı olabilir."
    ),
}

DEFAULT_MINIMUM_SAMPLE_SIZE = 20

_KPI_SET = [
    "appointment_count",
    "completed_appointment_rate",
    "no_show_rate",
    "unique_patient_count",
]

_ANOMALY_TRIGGERS = (
    "patlamis", "patladi", "firlamis", "firladi", "ani artis", "aniden artti",
    "anormal artis", "orani artmis", "artmis", "yukselmis",
)
# Negated forms ("artmamış olanlar") run the SAME anomaly comparison with the
# predicate inverted: groups whose rate_point_change is not positive.
_ANOMALY_NEGATED_TRIGGERS = (
    "artmamis", "yukselmemis", "patlamamis", "artis gostermeyen",
)
_PERFORMANCE_TRIGGERS = (
    "isler nasil gidiyor", "nasil gidiyoruz", "genel durum nasil",
    "durumumuz nasil", "genel gidisat", "performans ozeti", "isler nasil",
)
_LAST_MINUTE_TRIGGERS = (
    "son dakika", "son anda", "gunu gunune alan",
)
_VARIANCE_TRIGGERS = (
    "cok fark var mi", "fark var mi", "farklilik var mi", "arasinda cok fark",
    "arasinda fark var", "dengesiz", "esitsiz",
)
_RECENT_PERIOD_TRIGGERS = ("bu aralar", "son zamanlarda", "son donemde")
_PREVIOUS_YEAR_TRIGGERS = (
    "gecen seneye kiyasla", "gecen yila kiyasla", "gecen seneye gore",
    "gecen yila gore", "gecen sene ile", "gecen yil ile",
)


class AnalyticalStrategy(BaseModel):
    """Explicit query strategy derived from an implicit analytical question."""

    question_goal: str
    analysis_type: str
    current_period: str | None = None
    baseline_period: str | None = None
    cohort: str | None = None
    metrics: list[str] = Field(default_factory=list)
    dimensions: list[str] = Field(default_factory=list)
    minimum_sample_size: int = DEFAULT_MINIMUM_SAMPLE_SIZE
    assumptions: list[str] = Field(default_factory=list)
    result_shape: str = "summary"
    comparison_direction: str = "increase"  # "increase" | "no_increase"


def _has(folded_question: str, triggers: tuple[str, ...]) -> bool:
    return any(_term_in(folded_question, trigger, False) for trigger in triggers)


def resolve_strategy(
    folded_question: str,
    matched_metrics: list[str],
    matched_dimensions: list[str],
) -> AnalyticalStrategy | None:
    """Resolves an implicit analytical intent to an explicit strategy.

    Returns None when the question carries no implicit-analysis signal — the
    regular catalog resolution is then authoritative on its own.
    """
    recent = _has(folded_question, _RECENT_PERIOD_TRIGGERS)
    previous_year = _has(folded_question, _PREVIOUS_YEAR_TRIGGERS)

    # 1) Sudden-increase wording -> anomaly comparison against a baseline.
    # Note: 'iptal' questions never reach here — the view has no 'İptal' status,
    # so check_answerability diverts them to a controlled limitation first.
    negated_anomaly = _has(folded_question, _ANOMALY_NEGATED_TRIGGERS)
    if negated_anomaly or _has(folded_question, _ANOMALY_TRIGGERS):
        no_show = any("no_show" in metric for metric in matched_metrics)
        metrics = (
            ["no_show_count", "no_show_rate", "appointment_count"]
            if no_show or _term_in(folded_question, "gelmeme")
            else (matched_metrics or ["appointment_count"])
        )
        assumptions = [ASSUMPTION_POLICY["bu_aralar"], ASSUMPTION_POLICY["onceki_donem"],
                       ASSUMPTION_POLICY["min_sample"]]
        return AnalyticalStrategy(
            question_goal=(
                "Artış göstermeyen grupları belirle ve önceki dönemle karşılaştır"
                if negated_anomaly
                else "Ani artışı tespit et ve önceki dönemle karşılaştır"
            ),
            analysis_type="anomaly_comparison",
            current_period="last_30_days",
            baseline_period="previous_30_days",
            metrics=metrics,
            dimensions=matched_dimensions[:1],
            assumptions=assumptions,
            comparison_direction="no_increase" if negated_anomaly else "increase",
        )

    # 2) "How are things going" -> multi-metric KPI comparison.
    if _has(folded_question, _PERFORMANCE_TRIGGERS):
        if previous_year:
            baseline, baseline_note = "same_period_previous_year", ASSUMPTION_POLICY["gecen_sene"]
        else:
            baseline, baseline_note = "previous_30_days", ASSUMPTION_POLICY["onceki_donem"]
        return AnalyticalStrategy(
            question_goal="Temel KPI'ları dönemsel olarak karşılaştır",
            analysis_type="multi_metric_performance",
            current_period="last_30_days" if not previous_year else "current_year_to_date",
            baseline_period=baseline,
            metrics=list(_KPI_SET),
            dimensions=matched_dimensions[:1],
            assumptions=[ASSUMPTION_POLICY["isler_nasil"], baseline_note],
        )

    # 3) Last-minute bookers -> lead-time cohort.
    if _has(folded_question, _LAST_MINUTE_TRIGGERS):
        return AnalyticalStrategy(
            question_goal="Son dakika randevu alan hastaların gelme davranışını incele",
            analysis_type="cohort_analysis",
            cohort="lead_time_under_24h (DATEDIFF(hour, CreatedDate, BaslangicTarihi) < 24)",
            metrics=["appointment_count", "completed_appointment_rate", "no_show_rate"],
            dimensions=matched_dimensions[:1],
            assumptions=[ASSUMPTION_POLICY["son_dakika"], ASSUMPTION_POLICY["min_sample"]],
        )

    # 4) "Is there a big difference" -> variance / distribution analysis.
    if _has(folded_question, _VARIANCE_TRIGGERS):
        dimensions = matched_dimensions[:1]
        return AnalyticalStrategy(
            question_goal="Gruplar arasındaki dağılım farkını ölç",
            analysis_type="variance_analysis",
            metrics=matched_metrics or ["appointment_count"],
            dimensions=dimensions,
            assumptions=[ASSUMPTION_POLICY["cok_fark"], ASSUMPTION_POLICY["min_sample"]],
        )

    # 5) Explicit previous-year comparison without KPI wording.
    if previous_year:
        return AnalyticalStrategy(
            question_goal="Bu dönemi geçen yılın aynı dönemiyle karşılaştır",
            analysis_type="baseline_comparison",
            current_period="current_year_to_date",
            baseline_period="same_period_previous_year",
            metrics=matched_metrics or ["appointment_count"],
            dimensions=matched_dimensions[:1],
            assumptions=[ASSUMPTION_POLICY["gecen_sene"]],
        )

    # 6) Vague recent-period wording alone -> adaptive time comparison.
    if recent:
        return AnalyticalStrategy(
            question_goal="Son dönemi önceki eşit dönemle karşılaştır",
            analysis_type="adaptive_time_comparison",
            current_period="last_30_days",
            baseline_period="previous_30_days",
            metrics=matched_metrics or ["appointment_count"],
            dimensions=matched_dimensions[:1],
            assumptions=[ASSUMPTION_POLICY["bu_aralar"], ASSUMPTION_POLICY["onceki_donem"]],
        )

    return None


def format_strategy_for_prompt(strategy_fields: dict) -> list[str]:
    """Compact strategy lines for the SQL prompt (from QueryPlan fields)."""
    lines: list[str] = []
    if strategy_fields.get("question_goal"):
        lines.append(f"- Goal: {strategy_fields['question_goal']}")
    if strategy_fields.get("current_period"):
        lines.append(f"- Current period: {strategy_fields['current_period']}")
    if strategy_fields.get("baseline_period"):
        lines.append(
            f"- Baseline period: {strategy_fields['baseline_period']} "
            f"(compute both periods in ONE query via conditional aggregation)"
        )
    if strategy_fields.get("cohort"):
        lines.append(f"- Cohort filter: {strategy_fields['cohort']}")
    if strategy_fields.get("minimum_sample_size"):
        lines.append(
            f"- Include group volume so groups under {strategy_fields['minimum_sample_size']} "
            f"rows can be flagged"
        )
    lines.append("- Return an aggregated summary, NEVER raw detail rows")
    return lines
