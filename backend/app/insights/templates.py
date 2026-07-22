"""Insight Engine için deterministik Türkçe anlatı şablonları.

LLM kullanılamadığında veya kanıt yetersiz olduğunda garanti temellendirilmiş
yedek olarak kullanılır. Her cümle yalnız analytics nesnesinde zaten bulunan
değerlerden kurulur — hiçbir şey uydurulmaz. Kullanıcıya giden tüm metinler
doğal Türkçedir; sayı biçimleri merkezi sunum katmanından gelir.
"""

from app.analytics.models import AnalyticsResult
from app.insights.models import InsightNarrative, InsightRule
from app.reporting.presentation import format_number

INSUFFICIENT_EVIDENCE_SUMMARY = "Analiz için yeterli veri bulunamadı."

_TITLES: dict[str, str] = {
    "trend": "Trend Analizi",
    "growth_rate": "Büyüme Analizi",
    "comparison": "Dönem Karşılaştırması",
    "ranking": "Sıralama Analizi",
    "distribution": "Dağılım Analizi",
    "average": "Ortalama Analizi",
    "median": "Medyan Analizi",
    "minimum": "En Düşük Değer Analizi",
    "maximum": "En Yüksek Değer Analizi",
    "time_series": "Zaman Serisi Analizi",
    "percentage_change": "Değişim Analizi",
    "summary": "Sonuç Özeti",
    "none": "Analiz Sonucu",
    "list": "Sonuç Özeti",
}

_TREND_LABELS = {"upward": "yükseliş", "downward": "düşüş", "stable": "yatay seyir"}
_CHANGE_CLASSIFICATION = {"increase": "arttı", "decrease": "azaldı", "no_change": "değişmedi"}
_SLOPE_DIRECTION_TR = {"upward": "yükselişe", "downward": "düşüşe", "flat": "yatay seyre"}
_ENDPOINT_DIRECTION_TR = {"upward": "yükseliş", "downward": "düşüş", "flat": "yatay seyir"}
SINGLE_CATEGORY_LIMITATION = (
    "Seçilen kapsamda yalnızca bir kategori bulunduğu için kategoriler arası "
    "karşılaştırma yapılamadı."
)


def build_title(analytics: AnalyticsResult) -> str:
    return _TITLES.get(analytics.analytics_type, "Analiz Sonucu")


def format_percentage(value: float) -> str:
    """Tutarlı Türkçe yüzde biçimi: %18,4."""
    text = f"{value:.1f}".replace(".", ",")
    return f"%{text}"


def safe_ratio_percentage(numerator: float, denominator: float) -> str | None:
    """Payı bölene güvenli biçimde oranlar; bölen sıfırsa None döner (uydurma yok)."""
    if not denominator:
        return None
    return format_percentage(numerator / denominator * 100)


def classify_change(difference: float | None) -> str:
    """Farkı artış/azalış/değişim yok olarak sınıflar — eşik uydurmadan, işaret bazlı."""
    if difference is None or difference == 0:
        return "no_change"
    return "increase" if difference > 0 else "decrease"


def build_insufficient_evidence_narrative(analytics: AnalyticsResult) -> InsightNarrative:
    return InsightNarrative(
        title=build_title(analytics),
        summary=INSUFFICIENT_EVIDENCE_SUMMARY,
        highlights=[],
        observations=["Sonuç kümesi, yorum üretmek için yeterli veri içermiyor."],
        considerations=[],
    )


def build_deterministic_narrative(
    analytics: AnalyticsResult, rules: list[InsightRule]
) -> InsightNarrative:
    """Yalnız hesaplanmış metriklerden kurulan şablon anlatısı."""
    if InsightRule.INSUFFICIENT_EVIDENCE in rules:
        return build_insufficient_evidence_narrative(analytics)

    metrics = analytics.metrics
    highlights: list[str] = []
    observations: list[str] = []
    considerations: list[str] = []

    growth_rate = metrics.get("growth_rate")

    # Trend family: one coherent sentence built from the reconciled
    # endpoint-vs-slope verdict — never two independent claims that could
    # contradict each other (the old growth_rate-direction +
    # trend_direction-direction pair could disagree on the same series).
    trend_metrics = analytics.trend_metrics
    if trend_metrics is not None:
        consistency = trend_metrics.trend_consistency
        if consistency == "insufficient_data":
            considerations.append(
                "Eğilim hesaplamak için yeterli sayıda tamamlanmış dönem "
                "bulunmadığından bir yön belirtilmemiştir."
            )
        elif consistency in ("consistent_upward", "consistent_downward"):
            direction_word = "yükseliş" if consistency == "consistent_upward" else "düşüş"
            highlights.append(
                f"Dönem genelinde ve uç dönemler arasında tutarlı bir {direction_word} "
                "görülmektedir."
            )
        elif consistency == "mixed":
            slope_text = _SLOPE_DIRECTION_TR.get(trend_metrics.slope_direction, "belirsiz")
            endpoint_text = _ENDPOINT_DIRECTION_TR.get(
                trend_metrics.endpoint_direction, "belirsiz"
            )
            highlights.append(
                f"Dönem genelindeki eğim {slope_text} işaret ederken, ilk ve son "
                f"karşılaştırılabilir dönem arasında {endpoint_text} görülmektedir."
            )
        elif consistency == "flat":
            highlights.append("Değerler dönem boyunca büyük ölçüde yatay seyretmiştir.")

        if trend_metrics.comparison_excluded_partial_period and trend_metrics.excluded_periods:
            excluded = ", ".join(trend_metrics.excluded_periods)
            considerations.append(
                f"{excluded} dönemi henüz tamamlanmadığı için eğilim hesabında tam "
                "dönemlerle birlikte değerlendirilmemiştir."
            )

    # "Highest value" is a comparative claim — never made when only one
    # category exists (comparison_sufficient is False in that case).
    top_category = metrics.get("top_category")
    if top_category and analytics.comparison_sufficient is not False:
        highlights.append(f"En yüksek değer '{top_category}' grubunda.")
    if analytics.comparison_sufficient is False and analytics.comparison_limitation_reason:
        considerations.append(analytics.comparison_limitation_reason)

    largest_change = metrics.get("largest_change")
    if largest_change:
        highlights.append(f"En büyük değişim {largest_change} içinde gerçekleşti.")

    # Comparison family: current vs. previous value, when both are already
    # available (difference/percentage_change are pre-computed by the
    # analytics layer for time-series data — never invented here).
    difference = metrics.get("difference")
    percentage_change = metrics.get("percentage_change")
    if isinstance(difference, (int, float)) and growth_rate is None:
        change_kind = _CHANGE_CLASSIFICATION[classify_change(difference)]
        change_text = f"Değer önceki döneme göre {change_kind}"
        if isinstance(percentage_change, (int, float)) and difference != 0:
            change_text += f" ({format_percentage(abs(percentage_change))})"
        highlights.append(change_text + ".")

    # Distribution family: leading category share + remaining-category summary.
    distribution = metrics.get("distribution")
    total = metrics.get("total")
    if isinstance(distribution, dict) and distribution:
        ranked_shares = sorted(distribution.items(), key=lambda item: item[1], reverse=True)
        leading_label, leading_share = ranked_shares[0]

        # Concrete counts (not just percentages), when the ranking metric is
        # available — e.g. "Toplam 13 kayıttan 8 tanesi (%61,5) 'Beklemede'
        # durumunda." Never invented: only built from ranking/total, which are
        # already computed by the analytics layer.
        ranking = metrics.get("ranking")
        counts_by_label: dict[str, float] = {}
        if isinstance(ranking, list):
            counts_by_label = {
                entry.get("label"): entry.get("value")
                for entry in ranking
                if isinstance(entry, dict) and entry.get("label") is not None
            }
        leading_count = counts_by_label.get(leading_label)
        if leading_count is not None and total:
            distribution_summary = (
                f"Toplam {format_number(total)} kayıttan {format_number(leading_count)} "
                f"tanesi ({format_percentage(leading_share)}) '{leading_label}' durumunda."
            )
            remaining_entries = [
                (label, counts_by_label[label])
                for label, _share in ranked_shares[1:]
                if label in counts_by_label
            ]
            if remaining_entries:
                remaining_total = sum(count for _label, count in remaining_entries)
                parts = ", ".join(
                    f"{format_number(count)} '{label}'" for label, count in remaining_entries
                )
                distribution_summary += f" Kalan {format_number(remaining_total)} kayıt: {parts}."
            highlights.insert(0, distribution_summary)

        observations.append(
            f"'{leading_label}' toplamın {format_percentage(leading_share)} kadarını oluşturuyor."
        )
        if len(ranked_shares) > 1:
            remaining_share = round(100.0 - leading_share, 2)
            observations.append(
                f"Kalan {len(ranked_shares) - 1} kategori toplamın "
                f"{format_percentage(remaining_share)} kadarını paylaşıyor."
            )

    # Top-N/ranking family: leader plus the gap to the runner-up. Implies a
    # ranking against other categories — never fired for a single category.
    top_n = metrics.get("top_n")
    if isinstance(top_n, list) and top_n and analytics.comparison_sufficient is not False:
        leader = top_n[0]
        observations.append(
            f"Sıralamada ilk sırada '{leader.get('label')}' "
            f"({format_number(leader.get('value'))}) yer alıyor."
        )
        if len(top_n) > 1:
            runner_up = top_n[1]
            gap = leader.get("value") - runner_up.get("value")
            if isinstance(gap, (int, float)):
                observations.append(
                    f"İkinci sıradaki '{runner_up.get('label')}' ile farkı "
                    f"{format_number(gap)}."
                )

    if total is not None:
        observations.append(f"Sonuç kümesindeki toplam: {format_number(total)}.")
    average = metrics.get("average")
    if average is not None:
        observations.append(f"Ortalama değer: {format_number(average)}.")
    highest = metrics.get("highest_value")
    lowest = metrics.get("lowest_value")
    if highest is not None and lowest is not None:
        observations.append(
            f"Değerler {format_number(lowest)} ile {format_number(highest)} arasında."
        )

    comparison_ok = analytics.comparison_sufficient is not False
    if InsightRule.DOMINANT_CATEGORY in rules and top_category and comparison_ok:
        observations.append(f"'{top_category}' toplamın yarısından fazlasını oluşturuyor.")
    if InsightRule.BALANCED_DISTRIBUTION in rules and comparison_ok:
        observations.append("Değerler kategoriler arasında dengeli dağılıyor.")
    if InsightRule.OUTLIER_DETECTED in rules and top_category and comparison_ok:
        observations.append(f"'{top_category}' ortalamanın belirgin biçimde üzerinde.")

    if InsightRule.SINGLE_CATEGORY_COMPARISON in rules and top_category:
        observations.append(f"'{top_category}' için sonuçlar özetlenmiştir.")

    summary = (
        highlights[0]
        if highlights
        else (observations[0] if observations else "Sonuç kümesi için temel metrikler hesaplandı.")
    )

    return InsightNarrative(
        title=build_title(analytics),
        summary=summary,
        highlights=highlights,
        observations=observations,
        considerations=considerations,
    )
