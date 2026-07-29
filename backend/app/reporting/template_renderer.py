"""LLM çağırmadan deterministik rapor şekillerini Türkçe basan renderer.

AI-INTELLIGENCE-011: nihai QueryPlan'ın ürettiği typed alias'lar tek doğruluk
kaynağıdır — cohort/karşılaştırma/anomali sonuçları generic tek-satır özeti
yerine kendi Türkçe sunumlarını kullanır. Tüm etiketler ve sayı biçimleri
merkezi sunum katmanından (app/reporting/presentation.py) gelir.
"""

import re
import unicodedata
from dataclasses import dataclass
from numbers import Number
from typing import Any

from app.application_models.workflow_models import QueryResult
from app.reporting.presentation import (
    STATUS_LABELS_TR,
    format_number,
    format_percent,
    format_value,
    get_column_label,
    label_for,
)
from app.reporting.report_classifier import ReportType
from app.shared.result_limits import DEFAULT_GROUPED_RESULT_LIMIT
from app.shared.result_window import cap_query_result, result_notice

COMPARISON_CONTRACT_FALLBACK = (
    "# Karşılaştırma Yapılamadı\n\n"
    "Bu karşılaştırma için iki ayrı dönem sonucu oluşmadı. "
    "İki takvim ayı veya iki takvim yılı gibi daha net bir aralıkla tekrar sorabilirsiniz."
)


@dataclass(frozen=True)
class TemplateRenderResult:
    title: str
    markdown: str
    template_name: str


class TemplateReportRenderer:
    """Renders small deterministic report shapes without invoking an LLM."""

    def render(
        self,
        report_type: ReportType,
        query_result: QueryResult,
        question: str | None = None,
    ) -> TemplateRenderResult | None:
        if report_type == ReportType.ANALYTICAL:
            return None
        if report_type == ReportType.EMPTY:
            return self._render_empty(question)

        # Typed deterministic shapes get their own Turkish presentation.
        typed = self._render_typed(query_result)
        if typed is not None:
            return typed

        if report_type == ReportType.SINGLE_VALUE:
            return self._render_single_value(query_result, question)
        if report_type == ReportType.SINGLE_ROW:
            return self._render_single_row(query_result)
        if report_type == ReportType.TABLE:
            return self._render_table(query_result)
        return None

    def _render_empty(self, question: str | None) -> TemplateRenderResult:
        # AG-022 NO_RESULT_GUIDANCE: boş sonuç geçerli bir cevaptır; soru
        # bağlamına uygun, gerçek view alanlarına dayalı öneriler verilir.
        lines = [
            "# Sonuç Bulunamadı",
            "",
            _empty_result_summary(question),
            "",
            "## Deneyebilecekleriniz",
            "",
        ]
        lines.extend(f"- {suggestion}" for suggestion in _empty_result_suggestions(question))
        return TemplateRenderResult(
            title="Sonuç Bulunamadı",
            markdown="\n".join(lines),
            template_name="empty",
        )

    # ── typed presentations ──────────────────────────────────────────────

    def _render_typed(self, query_result: QueryResult) -> TemplateRenderResult | None:
        if not query_result.rows:
            return None
        columns = set(query_result.columns)
        if "cohort_total_count" in columns and len(query_result.rows) == 1:
            return self._render_cohort(query_result.rows[0])
        if {"current_period_count", "baseline_period_count"} <= columns and len(
            query_result.rows
        ) == 1:
            return self._render_comparison(query_result.rows[0])
        if {"current_entity_count", "baseline_entity_count"} <= columns and len(
            query_result.rows
        ) == 1:
            return self._render_entity_comparison(query_result.rows[0])
        if "rate_point_change" in columns and len(query_result.rows) >= 1:
            return self._render_anomaly(query_result)
        return None

    def _render_cohort(self, row: dict[str, Any]) -> TemplateRenderResult:
        total = row.get("cohort_total_count")
        lines = [
            "# Son Dakika Randevu Analizi",
            "",
            f"Son dakika alınan {format_number(total)} randevunun "
            f"{format_percent(row.get('completed_rate'))} kadarı gerçekleşti. "
            f"Gelmeme oranı {format_percent(row.get('no_show_rate'))} olarak hesaplandı.",
            "",
            "## Temel Göstergeler",
            "",
            f"- **{format_number(total)}** — {label_for('cohort_total_count')}",
        ]
        for prefix in ("completed", "checked_in", "no_show", "in_progress", "waiting"):
            rate = row.get(f"{prefix}_rate")
            if isinstance(rate, Number):
                lines.append(
                    f"- **{format_percent(rate)}** — {label_for(f'{prefix}_rate')}"
                )
        return TemplateRenderResult(
            "Son Dakika Randevu Analizi", "\n".join(lines), "cohort"
        )

    def _render_comparison(self, row: dict[str, Any]) -> TemplateRenderResult:
        current = row.get("current_period_count")
        baseline = row.get("baseline_period_count")
        absolute = row.get("absolute_change")
        # Contract guard: a comparison without both periods is never rendered
        # as a comparison — a single value on the comparison template misleads.
        if not (
            isinstance(current, Number)
            and isinstance(baseline, Number)
            and isinstance(absolute, Number)
        ):
            return TemplateRenderResult(
                "Karşılaştırma Yapılamadı",
                COMPARISON_CONTRACT_FALLBACK,
                "comparison_fallback",
            )
        current_label = str(row.get("current_period_label") or "Mevcut dönem")
        baseline_label = str(row.get("baseline_period_label") or "Önceki dönem")
        percentage = row.get("percentage_change")
        if float(absolute) > 0:
            direction = "arttı"
        elif float(absolute) < 0:
            direction = "azaldı"
        else:
            direction = "değişmedi"
        summary = (
            f"{current_label} döneminde {format_number(current)} randevu, "
            f"{baseline_label} döneminde {format_number(baseline)} randevu kaydedildi; "
            f"randevu sayısı {format_number(abs(float(absolute)))} adet {direction}"
        )
        if isinstance(percentage, Number):
            summary += f" ({format_percent(percentage)})"
        summary += "."
        lines = ["# Dönem Karşılaştırması", "", summary]
        return TemplateRenderResult("Dönem Karşılaştırması", "\n".join(lines), "comparison")

    def _render_entity_comparison(self, row: dict[str, Any]) -> TemplateRenderResult:
        current = row.get("current_entity_count")
        baseline = row.get("baseline_entity_count")
        # Contract guard (comparison-contract rule): both conditional counts
        # must exist, or the comparison presentation would mislead.
        if not (isinstance(current, Number) and isinstance(baseline, Number)):
            return TemplateRenderResult(
                "Karşılaştırma Yapılamadı",
                COMPARISON_CONTRACT_FALLBACK,
                "comparison_fallback",
            )
        current_label = str(row.get("current_entity_label") or "Birinci grup")
        baseline_label = str(row.get("baseline_entity_label") or "İkinci grup")
        difference = float(current) - float(baseline)
        # No-forced-winner rule: a tie is stated as a tie.
        if difference > 0:
            verdict = f"{current_label} daha yoğun"
        elif difference < 0:
            verdict = f"{baseline_label} daha yoğun"
        else:
            verdict = "iki grup eşit yoğunlukta"
        summary = (
            f"{current_label} için {format_number(current)} randevu, "
            f"{baseline_label} için {format_number(baseline)} randevu kaydedildi; "
            f"{verdict}."
        )
        lines = ["# Karşılaştırma", "", summary]
        return TemplateRenderResult("Karşılaştırma", "\n".join(lines), "entity_comparison")

    def _render_anomaly(self, query_result: QueryResult) -> TemplateRenderResult:
        rows = [
            row
            for row in query_result.rows
            if isinstance(row.get("rate_point_change"), Number)
        ]
        label_column = next(
            (
                column
                for column in query_result.columns
                if not any(m in column.lower() for m in ("count", "rate", "change"))
            ),
            None,
        )
        increased = [row for row in rows if float(row["rate_point_change"]) > 0]
        lines = ["# Dönemsel Artış Analizi", ""]
        if not increased:
            # Olay yoksa kazanan seçilmez: bunu açıkça söyleriz. Metin
            # ResultReasoner ile birebir aynı ("artış tespit edilmedi") —
            # aynı olguyu iki farklı yerde farklı ifade etmek tutarsızlık
            # yaratıyordu (robustluk turu 2026-07-29).
            lines.append(
                "İncelenen dönemde hiçbir grupta aranan oranda artış tespit edilmedi."
            )
        else:
            ranked = sorted(
                increased, key=lambda row: float(row["rate_point_change"]), reverse=True
            )
            top = ranked[0]
            label = str(top.get(label_column, "?")) if label_column else "?"
            lines.append(
                f"En belirgin artış **{label}** grubunda: oran farkı "
                f"{format_percent(top.get('rate_point_change'))} puan."
            )
            lines.extend(["", "## Artış Görülen Gruplar", ""])
            for row in ranked[:5]:
                group = str(row.get(label_column, "?")) if label_column else "?"
                lines.append(
                    f"- **{group}** — oran farkı "
                    f"{format_percent(row.get('rate_point_change'))} puan, "
                    f"mevcut dönem {format_number(row.get('current_period_count'))} kayıt"
                )
        return TemplateRenderResult("Dönemsel Artış Analizi", "\n".join(lines), "anomaly")

    # ── generic shapes ───────────────────────────────────────────────────

    def _render_single_value(
        self, query_result: QueryResult, question: str | None = None
    ) -> TemplateRenderResult:
        row = query_result.rows[0]
        label, value = next(iter(row.items()))
        rendered_value = _render_cell(label, value)
        markdown = "# Yanıt\n\n" + _single_value_sentence(label, rendered_value, question)
        return TemplateRenderResult("Yanıt", markdown, "single_value")

    def _render_single_row(self, query_result: QueryResult) -> TemplateRenderResult:
        # A single row commonly mixes a DIMENSION column with its metric
        # (e.g. "Şube: TEST ASM Gebze, Protokole Dönüşüm Oranı: %100") -
        # label_for() only ever consults the metric-alias catalog, so any
        # dimension column rendered raw title-cased ("Subeadi") instead of
        # its Turkish label ("Şube"). get_column_label() covers both.
        row = query_result.rows[0]
        lines = ["# Yanıt", ""]
        branch_note = _single_branch_scope_note(query_result)
        if branch_note:
            lines.extend([branch_note, ""])
        lines.extend(["Bulduğum değerler:", ""])
        for key in query_result.columns:
            if key in row:
                lines.append(f"- **{get_column_label(key)}:** {_render_cell(key, row[key])}")
        for key, value in row.items():
            if key not in query_result.columns:
                lines.append(f"- **{get_column_label(key)}:** {_render_cell(key, value)}")
        return TemplateRenderResult("Yanıt", "\n".join(lines), "single_row")

    def _render_table(self, query_result: QueryResult) -> TemplateRenderResult:
        # Table columns are almost always a mix of dimensions and metrics
        # (e.g. entity_label + appointment_count) - label_for() only ever
        # consults the metric-alias catalog, so every dimension column
        # rendered raw ("Entity Label", "Cinsiyetid", "Doktoradi") instead of
        # its Turkish label (2026-07-27, found across every grouped answer
        # in live multi-turn testing). get_column_label() covers both.
        query_result = cap_query_result(query_result, DEFAULT_GROUPED_RESULT_LIMIT)
        columns = query_result.columns or _columns_from_rows(query_result.rows)
        branch_note = _single_branch_scope_note(query_result)
        header = "| " + " | ".join(get_column_label(col) for col in columns) + " |"
        separator = "| " + " | ".join("---" for _ in columns) + " |"
        rows = []
        for row in query_result.rows:
            cells = [_escape_markdown(_render_cell(col, row.get(col, ""))) for col in columns]
            rows.append("| " + " | ".join(cells) + " |")
        markdown = "\n".join(
            [
                "# Sonuçlar",
                "",
                result_notice(query_result),
                "",
                *([branch_note, ""] if branch_note else []),
                header,
                separator,
                *rows,
            ]
        )
        return TemplateRenderResult("Sonuçlar", markdown, "table")


def _columns_from_rows(rows: list[dict[str, Any]]) -> list[str]:
    seen: list[str] = []
    for row in rows:
        for key in row:
            if key not in seen:
                seen.append(key)
    return seen


def _render_cell(column: str, value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, Number) and not isinstance(value, bool):
        return format_value(column, value)
    return str(value)


def _single_branch_scope_note(query_result: QueryResult) -> str | None:
    if len(query_result.rows) != 1:
        return None
    branch_column = next(
        (column for column in query_result.columns if column in {"SubeAdi", "branch"}),
        None,
    )
    if branch_column is None:
        return None
    value = query_result.rows[0].get(branch_column)
    if value in (None, ""):
        return None
    return (
        "Not: Bu sorgu sonucunda tek şube bulundu; şube bazında çoklu "
        "karşılaştırma oluşmadı."
    )


def _single_value_sentence(label: str, rendered_value: str, question: str | None = None) -> str:
    display_label = label_for(label)
    normalized_label = display_label.casefold()
    normalized_question = (question or "").casefold()

    if "randevu" in normalized_label and (
        "toplam" in normalized_label
        or "say" in normalized_label
        or "kaç" in normalized_question
    ):
        if "2025" in normalized_question:
            return f"2025 yılında toplam **{rendered_value}** randevu alınmış."
        return f"Toplam randevu sayısı **{rendered_value}**."
    if "hasta" in normalized_label and (
        "tekil" in normalized_label or "farklı" in normalized_question
    ):
        return f"Farklı hasta sayısı **{rendered_value}**."
    return f"{display_label}: **{rendered_value}**."


_DATE_SCOPE_RE = re.compile(
    r"\b(20\d{2}|bugun|dun|yarin|tarih|gun|hafta|ay|yil|donem|ocak|subat|mart|"
    r"nisan|mayis|haziran|temmuz|agustos|eylul|ekim|kasim|aralik)\b"
)


def _fold_turkish(text: str) -> str:
    folded = text.replace("İ", "i").replace("I", "ı").replace("ı", "i").casefold()
    normalized = unicodedata.normalize("NFD", folded)
    return "".join(
        character for character in normalized if unicodedata.category(character) != "Mn"
    )


def _empty_result_summary(question: str | None) -> str:
    scopes = _empty_scope_labels(question)
    if scopes:
        return (
            f"{_join_tr(scopes).capitalize()} için eşleşen kayıt bulamadım. "
            "Seçilen kapsamda kayıt olmayabilir."
        )
    return (
        "Bu kriterlerle eşleşen kayıt bulamadım. Tarih aralığı veya filtreler "
        "kapsamı fazla daraltmış olabilir."
    )


def _empty_scope_labels(question: str | None) -> list[str]:
    folded = _fold_turkish(question or "")
    scopes: list[str] = []
    if _DATE_SCOPE_RE.search(folded):
        scopes.append("tarih aralığı")
    if _contains_any(
        folded, ("randevu durumu", "durum", "gercekles", "iptal", "gelmedi")
    ):
        scopes.append("randevu durumu")
    if _contains_any(folded, ("bolum", "brans", "poliklinik")):
        scopes.append("bölüm")
    if _contains_any(folded, ("sube", "lokasyon", "merkez")):
        scopes.append("şube")
    if _contains_any(folded, ("doktor", "hekim")):
        scopes.append("doktor")
    if _contains_any(folded, ("hizmet", "islem")):
        scopes.append("hizmet")
    if _contains_any(folded, ("kaynak", "kanal")):
        scopes.append("kaynak")
    return scopes


def _empty_result_suggestions(question: str | None) -> list[str]:
    folded = _fold_turkish(question or "")
    suggestions: list[str] = []
    if _DATE_SCOPE_RE.search(folded):
        suggestions.append("Tarih aralığını genişletip aynı soruyu yeniden deneyin.")
    if _contains_any(
        folded, ("randevu durumu", "durum", "gercekles", "iptal", "gelmedi")
    ):
        suggestions.append(
            "Randevu durumu filtresini kaldırıp önce toplam dağılıma bakın."
        )

    filter_scopes = [
        label
        for label, tokens in (
            ("bölüm", ("bolum", "brans", "poliklinik")),
            ("şube", ("sube", "lokasyon", "merkez")),
            ("doktor", ("doktor", "hekim")),
            ("hizmet", ("hizmet", "islem")),
            ("kaynak", ("kaynak", "kanal")),
        )
        if _contains_any(folded, tokens)
    ]
    if filter_scopes:
        suggestions.append(
            f"{_join_tr(filter_scopes).capitalize()} filtresini sadeleştirip sonucu yeniden deneyin."
        )
    if _contains_any(folded, ("sadece", "yalniz", "filtre", "haric", "disinda")):
        suggestions.append("Filtreleri tek tek kaldırarak hangi koşulun sonucu daralttığını kontrol edin.")

    suggestions.append(
        "Önce aynı kapsamı toplam sayı olarak sorun; sonuç varsa ardından kırılım isteyin."
    )
    return _unique(suggestions)[:4]


def _contains_any(text: str, tokens: tuple[str, ...]) -> bool:
    return any(token in text for token in tokens)


def _join_tr(items: list[str]) -> str:
    if len(items) <= 1:
        return items[0] if items else ""
    return ", ".join(items[:-1]) + f" ve {items[-1]}"


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            result.append(item)
            seen.add(item)
    return result


def _plain(value: Any) -> str:
    return "-" if value is None else str(value)


# Cohort sunumu STATUS_LABELS_TR sözlüğünü label_for üzerinden kullanır; import
# burada sözlüğün tek merkezden geldiğini açıkça belgelemek için tutulur.
_ = STATUS_LABELS_TR


def _escape_markdown(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")
