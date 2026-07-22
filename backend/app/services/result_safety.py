"""Downstream guards for bounded database, API, report, and LLM results."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from app.application_models.workflow_models import QueryResult
from app.shared.result_limits import (
    DEFAULT_TABLE_PAGE_SIZE,
    MAX_API_ROWS,
    MAX_LLM_BOTTOM_ROWS,
    MAX_LLM_TOP_ROWS,
)
from app.shared.result_window import (
    cap_query_result as cap_query_result,
)
from app.shared.result_window import (
    result_notice as result_notice,
)

if TYPE_CHECKING:
    from app.planning.models import QueryPlan


_ANALYTICAL_TYPES = {
    "distribution",
    "comparison",
    "trend",
    "summary",
    "count",
    "average",
    "ratio",
    "multi_metric",
    "time_series",
}
_IDENTIFIER_COLUMN = re.compile(
    r"(^|_)(id|hasta_id|patient_id)$|(?:Id|ID)$",
    re.IGNORECASE,
)
_PII_COLUMN = re.compile(
    r"hasta|patient|tc|kimlik|telefon|phone|email|adres|address|ad_soyad|name",
    re.IGNORECASE,
)

_GROUPED_RESULT_SHAPES = {
    "grouped_rows",
    "time_series",
    "categorical_grouped_result",
}


@dataclass(frozen=True)
class ApiResultWindow:
    rows: list[dict[str, Any]]
    source_record_count: int | None
    result_group_count: int | None
    returned_row_count: int
    displayed_row_count: int
    result_truncated: bool
    applied_limit: int
    has_more: bool
    total_count: int | None


def has_identifier_columns(columns: list[str]) -> bool:
    return any(_IDENTIFIER_COLUMN.search(column) for column in columns)


def is_unsafe_analytical_detail(
    query_result: QueryResult,
    plan: QueryPlan | None,
) -> bool:
    """Flag oversized identifier-bearing analytical output without changing its plan."""
    if not query_result.has_more or not has_identifier_columns(query_result.columns):
        return False
    if plan is None:
        return False
    analysis_type = (plan.analysis_type or "").casefold()
    is_analytical = (
        analysis_type in _ANALYTICAL_TYPES
        or bool(plan.metrics)
        or bool(plan.planned_metrics)
        or plan.aggregation is not None
        or plan.numerator is not None
        or plan.denominator is not None
    )
    return is_analytical and analysis_type != "list"


def api_result_window(query_result: QueryResult, analytics: Any = None) -> ApiResultWindow:
    """Create the transport-safe row window without issuing any count query."""
    rows = [] if query_result.unsafe_detail_output else query_result.rows[:MAX_API_ROWS]
    api_trimmed = len(query_result.rows) > len(rows)
    truncated = query_result.result_truncated or api_trimmed
    has_more = query_result.has_more or api_trimmed
    result_group_count = query_result.result_group_count
    source_record_count = query_result.source_record_count
    if analytics is not None:
        shape = getattr(getattr(analytics, "result_shape", None), "value", None)
        if shape in _GROUPED_RESULT_SHAPES and not query_result.has_more:
            result_group_count = getattr(analytics, "row_count", None)
        if source_record_count is None and not has_more:
            source_record_count = getattr(analytics, "business_record_count", None)
    return ApiResultWindow(
        rows=rows,
        source_record_count=source_record_count,
        result_group_count=result_group_count,
        returned_row_count=len(rows),
        displayed_row_count=min(len(rows), DEFAULT_TABLE_PAGE_SIZE),
        result_truncated=truncated,
        applied_limit=MAX_API_ROWS,
        has_more=has_more,
        total_count=query_result.total_count,
    )


def enrich_result_counts(query_result: QueryResult, analytics: Any) -> QueryResult:
    """Attach only counts already established by complete deterministic analytics."""
    shape = getattr(getattr(analytics, "result_shape", None), "value", None)
    updates: dict[str, Any] = {}
    if shape in _GROUPED_RESULT_SHAPES and not query_result.has_more:
        updates["result_group_count"] = getattr(analytics, "row_count", None)
    if not query_result.has_more and bool(getattr(analytics, "aggregate_result", False)):
        business_count = getattr(analytics, "business_record_count", None)
        if business_count is not None:
            updates["source_record_count"] = business_count
    return query_result.model_copy(update=updates) if updates else query_result


def llm_safe_rows(query_result: QueryResult) -> list[dict[str, Any]]:
    """Provide at most top/bottom aggregate rows and never identifier/PII detail rows."""
    safe_columns = [
        column
        for column in query_result.columns
        if not _IDENTIFIER_COLUMN.search(column) and not _PII_COLUMN.search(column)
    ]
    rows = [{column: row.get(column) for column in safe_columns} for row in query_result.rows]
    if len(rows) <= MAX_LLM_TOP_ROWS + MAX_LLM_BOTTOM_ROWS:
        return list(rows)
    top = rows[:MAX_LLM_TOP_ROWS]
    bottom = rows[-MAX_LLM_BOTTOM_ROWS:]
    return top + bottom


def safe_result_shape(query_result: QueryResult) -> str:
    """Describe result structure for the LLM without exposing additional records."""
    if query_result.unsafe_detail_output:
        return "unsafe_detail_output"
    if not query_result.rows:
        return "empty"
    if len(query_result.rows) == 1:
        return "scalar_aggregate" if len(query_result.columns) == 1 else "single_row"
    if query_result.result_group_count is not None:
        return "grouped_rows"
    return "bounded_tabular_rows"
