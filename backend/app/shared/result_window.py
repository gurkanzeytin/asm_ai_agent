"""Small, dependency-light helpers for presenting bounded query results."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.shared.result_limits import DEFAULT_GROUPED_RESULT_LIMIT

if TYPE_CHECKING:
    from app.application_models.workflow_models import QueryResult


def cap_query_result(query_result: QueryResult, limit: int) -> QueryResult:
    """Return a metadata-preserving row window for reports and other consumers."""
    safe_limit = max(0, limit)
    rows = query_result.rows[:safe_limit]
    was_trimmed = len(query_result.rows) > len(rows)
    return query_result.model_copy(
        update={
            "rows": rows,
            "row_count": len(rows),
            "returned_row_count": len(rows),
            "displayed_row_count": min(len(rows), DEFAULT_GROUPED_RESULT_LIMIT),
            "result_truncated": query_result.result_truncated or was_trimmed,
            "has_more": query_result.has_more or was_trimmed,
            "applied_limit": safe_limit,
        }
    )


def result_notice(query_result: QueryResult) -> str:
    """Build truthful Turkish wording from known counts and truncation metadata."""
    shown = len(query_result.rows)
    if query_result.result_truncated or query_result.has_more:
        if query_result.total_count is not None:
            return (
                f"Toplam {query_result.total_count:,} sonuç bulundu; ilk {shown} sonuç "
                "gösteriliyor."
            ).replace(",", ".")
        return f"İlk {shown} sonuç gösteriliyor. Daha fazla sonuç bulunmaktadır."
    if query_result.result_group_count is not None and query_result.columns:
        # Keep the module import-light so it can safely be used during bootstrap.
        from app.reporting.presentation import get_dimension_label

        group_label = get_dimension_label(query_result.columns[0]).casefold()
        return f"{query_result.result_group_count} {group_label} listelenmiştir."
    return f"Toplam {shown} kayıt listelenmiştir."
