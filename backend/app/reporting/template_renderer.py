from dataclasses import dataclass
from typing import Any

from app.application_models.workflow_models import QueryResult
from app.reporting.report_classifier import ReportType


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
            return TemplateRenderResult(
                title="Sonuc Bulunamadi",
                markdown="# Sonuc Bulunamadi\n\nBelirtilen kriterlere uygun kayit bulunamadi.",
                template_name="empty",
            )
        if report_type == ReportType.SINGLE_VALUE:
            return self._render_single_value(query_result)
        if report_type == ReportType.SINGLE_ROW:
            return self._render_single_row(query_result)
        if report_type == ReportType.TABLE:
            return self._render_table(query_result)
        return None

    def _render_single_value(self, query_result: QueryResult) -> TemplateRenderResult:
        row = query_result.rows[0]
        label, value = next(iter(row.items()))
        markdown = (
            "# Sorgu Sonucu\n\n"
            f"**{_humanize(label)}:** {_format_value(value)}\n\n"
            f"Sorgu sonucuna gore toplam {_format_value(value)} kayit bulunmaktadir."
        )
        return TemplateRenderResult("Sorgu Sonucu", markdown, "single_value")

    def _render_single_row(self, query_result: QueryResult) -> TemplateRenderResult:
        row = query_result.rows[0]
        lines = ["# Sorgu Sonucu", ""]
        for key in query_result.columns:
            if key in row:
                lines.append(f"- **{_humanize(key)}:** {_format_value(row[key])}")
        for key, value in row.items():
            if key not in query_result.columns:
                lines.append(f"- **{_humanize(key)}:** {_format_value(value)}")
        return TemplateRenderResult("Sorgu Sonucu", "\n".join(lines), "single_row")

    def _render_table(self, query_result: QueryResult) -> TemplateRenderResult:
        columns = query_result.columns or _columns_from_rows(query_result.rows)
        header = "| " + " | ".join(_humanize(col) for col in columns) + " |"
        separator = "| " + " | ".join("---" for _ in columns) + " |"
        rows = []
        for row in query_result.rows:
            cells = [_escape_markdown(_format_value(row.get(col, ""))) for col in columns]
            rows.append("| " + " | ".join(cells) + " |")
        markdown = "\n".join(
            [
                "# Sorgu Sonucu",
                "",
                f"Toplam {query_result.row_count} kayit listelenmistir.",
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


def _humanize(value: str) -> str:
    return value.replace("_", " ").strip().title()


def _format_value(value: Any) -> str:
    if value is None:
        return "-"
    return str(value)


def _escape_markdown(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")
