"""LLM çağırmadan deterministik rapor şekillerini Türkçe basan renderer.

AI-INTELLIGENCE-011: nihai QueryPlan'ın ürettiği typed alias'lar tek doğruluk
kaynağıdır — cohort/karşılaştırma/anomali sonuçları generic tek-satır özeti
yerine kendi Türkçe sunumlarını kullanır. Tüm etiketler ve sayı biçimleri
merkezi sunum katmanından (app/reporting/presentation.py) gelir.
"""

from dataclasses import dataclass
from numbers import Number
from typing import Any

from app.application_models.workflow_models import QueryResult
from app.reporting.presentation import (
    STATUS_LABELS_TR,
    format_number,
    format_percent,
    format_value,
    label_for,
)
from app.reporting.report_classifier import ReportType

COMPARISON_CONTRACT_FALLBACK = (
    "# Karşılaştırma Yapılamadı\n\n"
    "Karşılaştırma için iki ayrı dönem sonucu oluşturulamadı. "
    "Tarih aralığını daha açık belirtmeyi deneyebilirsiniz "
    "(örneğin iki takvim ayı veya iki takvim yılı)."
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
    ) -> TemplateRenderResult | None:
        if report_type == ReportType.ANALYTICAL:
            return None
        if report_type == ReportType.EMPTY:
            # AG-022 NO_RESULT_GUIDANCE: boş sonuç geçerli bir cevaptır; soru
            # bağlamına uygun, gerçek view alanlarına dayalı öneriler verilir.
            markdown = (
                "# Sonuç Bulunamadı\n\n"
                "Sorgu başarıyla çalıştı ancak belirtilen kriterlere uygun kayıt bulunamadı. "
                "Seçtiğiniz tarih aralığında ya da filtrede gerçekten veri olmayabilir.\n\n"
                "## Deneyebilecekleriniz\n\n"
                "- Tarih aralığını genişletin (örneğin \"bugün\" yerine \"bu ay\").\n"
                "- Filtreyi sadeleştirip şube, bölüm veya randevu durumu bazında "
                "dağılımı isteyin.\n"
            )
            return TemplateRenderResult(
                title="Sonuç Bulunamadı",
                markdown=markdown,
                template_name="empty",
            )

        # Typed deterministic shapes get their own Turkish presentation.
        typed = self._render_typed(query_result)
        if typed is not None:
            return typed

        if report_type == ReportType.SINGLE_VALUE:
            return self._render_single_value(query_result)
        if report_type == ReportType.SINGLE_ROW:
            return self._render_single_row(query_result)
        if report_type == ReportType.TABLE:
            return self._render_table(query_result)
        return None

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
        lines = [
            "# Dönem Karşılaştırması",
            "",
            summary,
            "",
            "## Temel Göstergeler",
            "",
            f"- **{format_number(current)}** — {current_label}",
            f"- **{format_number(baseline)}** — {baseline_label}",
            f"- **{format_number(absolute)}** — {label_for('absolute_change')}",
        ]
        if isinstance(percentage, Number):
            lines.append(
                f"- **{format_percent(percentage)}** — {label_for('percentage_change')}"
            )
        return TemplateRenderResult("Dönem Karşılaştırması", "\n".join(lines), "comparison")

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
            # Olay yoksa kazanan seçilmez: bunu açıkça söyleriz.
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

    def _render_single_value(self, query_result: QueryResult) -> TemplateRenderResult:
        row = query_result.rows[0]
        label, value = next(iter(row.items()))
        rendered_value = _render_cell(label, value)
        markdown = (
            "# Sorgu Sonucu\n\n"
            f"**{label_for(label)}:** {rendered_value}\n\n"
            f"Sorguya göre toplam {rendered_value} kayıt bulunmaktadır."
        )
        return TemplateRenderResult("Sorgu Sonucu", markdown, "single_value")

    def _render_single_row(self, query_result: QueryResult) -> TemplateRenderResult:
        row = query_result.rows[0]
        lines = ["# Sorgu Sonucu", ""]
        for key in query_result.columns:
            if key in row:
                lines.append(f"- **{label_for(key)}:** {_render_cell(key, row[key])}")
        for key, value in row.items():
            if key not in query_result.columns:
                lines.append(f"- **{label_for(key)}:** {_render_cell(key, value)}")
        return TemplateRenderResult("Sorgu Sonucu", "\n".join(lines), "single_row")

    def _render_table(self, query_result: QueryResult) -> TemplateRenderResult:
        columns = query_result.columns or _columns_from_rows(query_result.rows)
        header = "| " + " | ".join(label_for(col) for col in columns) + " |"
        separator = "| " + " | ".join("---" for _ in columns) + " |"
        rows = []
        for row in query_result.rows:
            cells = [_escape_markdown(_render_cell(col, row.get(col, ""))) for col in columns]
            rows.append("| " + " | ".join(cells) + " |")
        markdown = "\n".join(
            [
                "# Sorgu Sonucu",
                "",
                f"Toplam {format_number(query_result.row_count)} kayıt listelenmiştir.",
                "",
                header,
                separator,
                *rows,
            ]
        )
        return TemplateRenderResult("Sorgu Sonucu", markdown, "table")


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


def _plain(value: Any) -> str:
    return "-" if value is None else str(value)


# Cohort sunumu STATUS_LABELS_TR sözlüğünü label_for üzerinden kullanır; import
# burada sözlüğün tek merkezden geldiğini açıkça belgelemek için tutulur.
_ = STATUS_LABELS_TR


def _escape_markdown(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")
