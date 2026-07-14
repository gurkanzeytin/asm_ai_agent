"""Deterministic Analytics Engine — runs after successful SQL execution.

Profiles the SQL result set (numeric / temporal / label columns), classifies its
shape, computes shape-appropriate metrics via the calculator registry, prepares
insight fields for the future LLM insight generator, and attaches a
visualization recommendation. No LLM calls anywhere in this module.
"""

import logging
import re
import time
from typing import Any

from app.analytics import calculators
from app.analytics.intent_detector import AnalyticsIntentDetector
from app.analytics.models import AnalyticsIntent, AnalyticsResult, DataShape
from app.analytics.visualization_selector import VisualizationSelector
from app.application_models.workflow_models import QueryResult

logger = logging.getLogger(__name__)

# Column-name fragments that indicate a temporal axis (Turkish + English).
_TEMPORAL_NAME_PATTERN = re.compile(
    r"tarih|date|zaman|time|saat|hour|gun|day|hafta|week|ay\b|month|yil|year|donem|period",
    re.IGNORECASE,
)
# Values like 2026-07-13, 2026-07, 2026/07/13, 13.07.2026
_TEMPORAL_VALUE_PATTERN = re.compile(
    r"^\d{4}[-/.]\d{1,2}([-/.]\d{1,2})?([ T].*)?$|^\d{1,2}[-/.]\d{1,2}[-/.]\d{4}$"
)
_ID_NAME_PATTERN = re.compile(r"(^|_)id$|^id($|_)", re.IGNORECASE)

_TOP_N_SIZE = 5
_MAX_DISTRIBUTION_CATEGORIES = 12


class AnalyticsEngine:
    """Computes a structured AnalyticsResult from a question and its SQL result."""

    def __init__(
        self,
        intent_detector: AnalyticsIntentDetector | None = None,
        visualization_selector: VisualizationSelector | None = None,
    ) -> None:
        self.intent_detector = intent_detector or AnalyticsIntentDetector()
        self.visualization_selector = visualization_selector or VisualizationSelector()

    def analyze(self, question: str, query_result: QueryResult) -> AnalyticsResult:
        start_time = time.perf_counter()

        intents = self.intent_detector.detect(question)
        metric_column, label_column, temporal_column = self._profile_columns(
            query_result, question
        )
        data_shape = self._classify_shape(query_result, metric_column, temporal_column)

        values = self._numeric_values(query_result, metric_column)
        labels = self._labels(query_result, label_column or temporal_column)

        metrics = self._compute_metrics(data_shape, values, labels)
        insights = self._prepare_insights(data_shape, metrics, labels, values)
        analytics_type = self._analytics_type(intents, data_shape)

        category_count = len(set(labels)) if labels else 0
        visualization = self.visualization_selector.select(
            data_shape=data_shape,
            intents=intents,
            row_count=query_result.row_count,
            category_count=category_count,
        )

        duration_ms = (time.perf_counter() - start_time) * 1000
        result = AnalyticsResult(
            analytics_type=analytics_type,
            intents=intents,
            data_shape=data_shape,
            metrics=metrics,
            insights=insights,
            visualization=visualization,
            metric_column=metric_column,
            label_column=label_column or temporal_column,
            row_count=query_result.row_count,
            duration_ms=duration_ms,
        )
        self._log_result(question, result)
        return result

    # ── Result profiling ───────────────────────────────────────────────────────

    def _profile_columns(
        self, query_result: QueryResult, question: str = ""
    ) -> tuple[str | None, str | None, str | None]:
        """Identifies the metric (numeric), label (categorical), and temporal columns."""
        numeric_columns: list[str] = []
        temporal_columns: list[str] = []
        label_columns: list[str] = []

        for column in query_result.columns:
            column_values = [
                row.get(column) for row in query_result.rows if row.get(column) is not None
            ]
            if self._is_temporal(column, column_values):
                temporal_columns.append(column)
            elif column_values and all(
                isinstance(value, (int, float)) and not isinstance(value, bool)
                for value in column_values
            ):
                numeric_columns.append(column)
            else:
                label_columns.append(column)

        # Aggregates ("COUNT(*) AS n") are conventionally the last column. Id-like
        # numeric columns are never metrics: computing trends or rankings over
        # entity identifiers produces meaningless analytics. When several metric
        # columns exist, one whose name echoes the question's subject wins
        # ("randevularını analiz et" -> toplam_randevu, not iptal_edildi).
        metric_candidates = [c for c in numeric_columns if not _ID_NAME_PATTERN.search(c)]
        metric_column = self._question_preferred_column(question, metric_candidates) or (
            (metric_candidates or [None])[-1]
        )
        label_column = next(
            (c for c in label_columns if not _ID_NAME_PATTERN.search(c)),
            label_columns[0] if label_columns else None,
        )
        temporal_column = temporal_columns[0] if temporal_columns else None
        return metric_column, label_column, temporal_column

    def _question_preferred_column(
        self, question: str, candidates: list[str]
    ) -> str | None:
        """Picks the candidate column whose name shares a word stem with the question."""
        if not question or len(candidates) < 2:
            return None
        folded_question = self.intent_detector._fold(question)
        question_tokens = {
            token for token in re.findall(r"[^\W_]+", folded_question) if len(token) >= 4
        }
        for column in candidates:
            folded_column = self.intent_detector._fold(column)
            column_tokens = {
                token for token in re.findall(r"[^\W_]+", folded_column) if len(token) >= 4
            }
            if any(
                question_token.startswith(column_token)
                or column_token.startswith(question_token)
                for column_token in column_tokens
                for question_token in question_tokens
            ):
                return column
        return None

    def _is_temporal(self, column: str, values: list[Any]) -> bool:
        if _TEMPORAL_NAME_PATTERN.search(column):
            return True
        if not values:
            return False
        return all(
            isinstance(value, str) and _TEMPORAL_VALUE_PATTERN.match(value.strip())
            for value in values
        )

    def _classify_shape(
        self,
        query_result: QueryResult,
        metric_column: str | None,
        temporal_column: str | None,
    ) -> DataShape:
        if query_result.row_count == 0:
            return DataShape.EMPTY
        if query_result.row_count == 1:
            if len(query_result.columns) == 1 and metric_column:
                return DataShape.SINGLE_VALUE
            return DataShape.SINGLE_ROW
        if temporal_column and metric_column:
            return DataShape.TIME_SERIES
        if metric_column and len(query_result.columns) >= 2:
            return DataShape.CATEGORICAL
        return DataShape.TABULAR

    def _numeric_values(
        self, query_result: QueryResult, metric_column: str | None
    ) -> list[float]:
        if not metric_column:
            return []
        return [
            float(row[metric_column])
            for row in query_result.rows
            if isinstance(row.get(metric_column), (int, float))
            and not isinstance(row.get(metric_column), bool)
        ]

    def _labels(self, query_result: QueryResult, label_column: str | None) -> list[str]:
        if not label_column:
            return []
        return [str(row.get(label_column, "")) for row in query_result.rows]

    # ── Metric computation ─────────────────────────────────────────────────────

    def _compute_metrics(
        self,
        data_shape: DataShape,
        values: list[float],
        labels: list[str],
    ) -> dict[str, Any]:
        if not values:
            return {"count": 0}

        metrics: dict[str, Any] = {
            "count": calculators.count(values),
            "total": calculators.total(values),
            "average": calculators.average(values),
            "median": calculators.median(values),
            "minimum": calculators.minimum(values),
            "maximum": calculators.maximum(values),
            "highest_value": calculators.maximum(values),
            "lowest_value": calculators.minimum(values),
        }

        labeled = list(zip(labels, values, strict=True)) if len(labels) == len(values) else []

        if data_shape == DataShape.TIME_SERIES:
            metrics["difference"] = calculators.difference(values)
            metrics["percentage_change"] = calculators.percentage_difference(values)
            metrics["growth_rate"] = calculators.growth_rate(values)
            metrics["trend_direction"] = calculators.trend_direction(values)
            if labeled:
                ranked = calculators.rank(labeled)
                metrics["highest_period"] = ranked[0][0]
                metrics["lowest_period"] = ranked[-1][0]
                metrics["largest_change"] = calculators.largest_change(labels, values)

        if data_shape == DataShape.CATEGORICAL and labeled:
            ranked = calculators.rank(labeled)
            metrics["ranking"] = [{"label": label, "value": value} for label, value in ranked]
            metrics["top_n"] = [
                {"label": label, "value": value}
                for label, value in calculators.top_n(labeled, _TOP_N_SIZE)
            ]
            metrics["bottom_n"] = [
                {"label": label, "value": value}
                for label, value in calculators.bottom_n(labeled, _TOP_N_SIZE)
            ]
            metrics["top_category"] = ranked[0][0]
            metrics["bottom_category"] = ranked[-1][0]
            grand_total = sum(value for _, value in labeled)
            if grand_total > 0 and len(labeled) <= _MAX_DISTRIBUTION_CATEGORIES:
                metrics["distribution"] = {
                    label: round(value / grand_total * 100, 2) for label, value in ranked
                }

        return metrics

    # ── Insight preparation (Part 5 — consumed by a future LLM) ───────────────

    def _prepare_insights(
        self,
        data_shape: DataShape,
        metrics: dict[str, Any],
        labels: list[str],
        values: list[float],
    ) -> dict[str, Any]:
        insights: dict[str, Any] = {}
        for source_key, insight_key in (
            ("trend_direction", "trend"),
            ("growth_rate", "growth_rate"),
            ("top_category", "top_category"),
            ("bottom_category", "bottom_category"),
            ("largest_change", "largest_change"),
            ("highest_period", "highest_period"),
            ("lowest_period", "lowest_period"),
            ("total", "total"),
            ("average", "average"),
        ):
            if metrics.get(source_key) is not None:
                insights[insight_key] = metrics[source_key]
        if data_shape == DataShape.SINGLE_VALUE and values:
            insights["value"] = values[0]
        return insights

    def _analytics_type(
        self, intents: list[AnalyticsIntent], data_shape: DataShape
    ) -> str:
        primary = self.intent_detector.primary_intent(intents)
        if primary is not AnalyticsIntent.GENERAL:
            return primary.value
        # No analytical wording — fall back to what the data itself supports.
        shape_defaults = {
            DataShape.TIME_SERIES: AnalyticsIntent.TREND.value,
            DataShape.CATEGORICAL: AnalyticsIntent.COMPARISON.value,
            DataShape.SINGLE_VALUE: "summary",
            DataShape.SINGLE_ROW: "summary",
            DataShape.EMPTY: "none",
        }
        return shape_defaults.get(data_shape, "list")

    # ── Observability ──────────────────────────────────────────────────────────

    def _log_result(self, question: str, result: AnalyticsResult) -> None:
        scalar_metrics = {
            key: value
            for key, value in result.metrics.items()
            if not isinstance(value, (list, dict))
        }
        logger.info(
            "\n================ ANALYTICS ENGINE ================\n"
            f"Question\n{question}\n\n"
            f"Analytics Intents\n"
            f"{', '.join(intent.value for intent in result.intents) or 'None'}\n\n"
            f"Analytics Type\n{result.analytics_type}\n\n"
            f"Data Shape\n{result.data_shape.value} ({result.row_count} rows)\n\n"
            "Calculated Metrics\n"
            f"{scalar_metrics}\n\n"
            "Visualization Decision\n"
            f"{result.visualization.type.value if result.visualization else 'None'}"
            f" — {result.visualization.reason if result.visualization else ''}\n\n"
            f"Execution Time\n{result.duration_ms:.2f} ms\n"
            "==================================================",
            extra={
                "analytics_intents": [intent.value for intent in result.intents],
                "analytics_type": result.analytics_type,
                "data_shape": result.data_shape.value,
                "metrics": scalar_metrics,
                "visualization_type": (
                    result.visualization.type.value if result.visualization else None
                ),
                "visualization_reason": (
                    result.visualization.reason if result.visualization else None
                ),
                "row_count": result.row_count,
                "duration_ms": result.duration_ms,
            },
        )
