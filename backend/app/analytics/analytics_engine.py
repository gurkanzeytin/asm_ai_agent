"""Deterministic Analytics Engine — runs after successful SQL execution.

Profiles the SQL result set (numeric / temporal / label columns), classifies its
shape, computes shape-appropriate metrics via the calculator registry, prepares
insight fields for the future LLM insight generator, and attaches a
visualization recommendation. No LLM calls anywhere in this module.
"""

import logging
import re
import time
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Any

from app.analytics import calculators
from app.analytics.intent_detector import AnalyticsIntentDetector
from app.analytics.models import (
    AnalyticsIntent,
    AnalyticsResult,
    DataShape,
    DisplayableKPI,
    MetricSummary,
    ResultShape,
)
from app.analytics.trend_analysis import TrendMetrics, compute_trend_metrics
from app.analytics.visualization_selector import VisualizationSelector
from app.application_models.workflow_models import QueryResult
from app.reporting.presentation import (
    build_column_metadata,
    get_analysis_type_label,
    get_metric_label,
)

if TYPE_CHECKING:
    from app.planning.models import QueryPlan

logger = logging.getLogger(__name__)


@dataclass
class _ComputedMetrics:
    """Internal carrier so `_compute_metrics` can return both the flattened
    scalar dict (unchanged external shape) and the typed trend verdict."""

    scalar: dict[str, Any]
    trend_metrics: TrendMetrics | None

# Column-name fragments that indicate a temporal axis (Turkish + English).
# "ay"/"week"/"month" require a trailing word boundary — without it, bucketed
# metric aliases like "monthly_appointment_count"/"weekly_appointment_count"
# (the actual metric column, not the date bucket) false-match on the bare
# "month"/"week" substring, get misclassified as a second temporal column, and
# collapse a valid multi-row trend result to DataShape.TABULAR instead of
# TIME_SERIES.
_TEMPORAL_NAME_PATTERN = re.compile(
    r"tarih|date|zaman|time|saat|hour|gun|day|hafta|week\b|ay\b|month\b|yil|year|donem|period",
    re.IGNORECASE,
)
# Values like 2026-07-13, 2026-07, 2026/07/13, 13.07.2026
_TEMPORAL_VALUE_PATTERN = re.compile(
    r"^\d{4}[-/.]\d{1,2}([-/.]\d{1,2})?([ T].*)?$|^\d{1,2}[-/.]\d{1,2}[-/.]\d{4}$"
)
_ID_NAME_PATTERN = re.compile(r"(^|_)id$|^id($|_)", re.IGNORECASE)

_TOP_N_SIZE = 5
_MAX_DISTRIBUTION_CATEGORIES = 12
# Turkish direction wording in two grammatical forms, for the two distinct
# sentence slots MIXED_TREND_SIGNAL fills ("eğim {X} işaret ederken" needs the
# dative case; "arasında {Y} görülmektedir" needs the plain noun).
_SLOPE_DIRECTION_TR = {"upward": "yükselişe", "downward": "düşüşe", "flat": "yatay seyre"}
_ENDPOINT_DIRECTION_TR = {"upward": "yükseliş", "downward": "düşüş", "flat": "yatay seyir"}
# Adjective form for "genel yön {X}dır" (AI-INTELLIGENCE-018 item 7's allowed
# mixed/fluctuating-trend statement — never "sürekli"/"tutarlı" language).
_ENDPOINT_DIRECTION_ADJECTIVE_TR = {"upward": "yukarı", "downward": "aşağı", "flat": "yatay"}


class AnalyticsEngine:
    """Computes a structured AnalyticsResult from a question and its SQL result."""

    def __init__(
        self,
        intent_detector: AnalyticsIntentDetector | None = None,
        visualization_selector: VisualizationSelector | None = None,
    ) -> None:
        self.intent_detector = intent_detector or AnalyticsIntentDetector()
        self.visualization_selector = visualization_selector or VisualizationSelector()

    def analyze(
        self,
        question: str,
        query_result: QueryResult,
        plan: "QueryPlan | None" = None,
        metric_aliases: dict[str, str] | None = None,
    ) -> AnalyticsResult:
        start_time = time.perf_counter()

        intents = self.intent_detector.detect(question)
        metric_column, label_column, temporal_column = self._profile_columns(query_result, question)
        data_shape = self._classify_shape(query_result, metric_column, temporal_column, plan)
        result_shape = self._classify_result_shape(query_result, data_shape, plan)

        values = self._numeric_values(query_result, metric_column)
        labels = self._labels(query_result, label_column or temporal_column)

        grain = plan.grouping_granularity if plan else None
        metrics = self._compute_metrics(data_shape, values, labels, grain)
        insights = self._prepare_insights(data_shape, metrics.scalar, labels, values)
        analytics_type = self._analytics_type(intents, data_shape)

        category_count = len(set(labels)) if labels else 0
        visualization = self.visualization_selector.select(
            data_shape=data_shape,
            intents=intents,
            row_count=query_result.row_count,
            category_count=category_count,
            metric_count=len(plan.metrics) if plan else 1,
        )

        metric_summaries = self._compute_metric_summaries(
            plan, query_result, metric_aliases, labels, result_shape
        )
        displayable_kpis = self._displayable_kpis(
            plan, query_result, metric_aliases, result_shape
        )
        if result_shape in {
            ResultShape.SCALAR_AGGREGATE,
            ResultShape.MULTI_METRIC_SCALAR_AGGREGATE,
        }:
            # A returned aggregate cell is already a business statistic. Never
            # calculate a second distribution (count/total/median/min/max) over it.
            metrics = _ComputedMetrics(
                scalar={item.key: item.value for item in displayable_kpis},
                trend_metrics=None,
            )
            insights = {item.key: item.value for item in displayable_kpis}

        comparison_category_count = None
        comparison_sufficient = None
        comparison_limitation_reason = None
        if data_shape == DataShape.CATEGORICAL:
            comparison_category_count = category_count
            comparison_sufficient = category_count >= 2
            if category_count == 1:
                comparison_limitation_reason = (
                    "Seçilen kapsamda yalnızca bir kategori bulunduğu için "
                    "kategoriler arası karşılaştırma yapılamadı."
                )

        duration_ms = (time.perf_counter() - start_time) * 1000
        result = AnalyticsResult(
            analytics_type=analytics_type,
            analytics_type_label=get_analysis_type_label(analytics_type),
            intents=intents,
            data_shape=data_shape,
            metrics=metrics.scalar,
            insights=insights,
            visualization=visualization,
            metric_column=metric_column,
            label_column=label_column or temporal_column,
            row_count=query_result.row_count,
            technical_row_count=query_result.row_count,
            business_record_count=(
                query_result.row_count
                if result_shape == ResultShape.RAW_RECORD_ROWS
                else None
            ),
            result_shape=result_shape,
            aggregate_result=result_shape in {
                ResultShape.SCALAR_AGGREGATE,
                ResultShape.MULTI_METRIC_SCALAR_AGGREGATE,
            },
            displayable_kpis=displayable_kpis,
            duration_ms=duration_ms,
            metric_summaries=metric_summaries,
            trend_metrics=metrics.trend_metrics,
            comparison_category_count=comparison_category_count,
            comparison_sufficient=comparison_sufficient,
            comparison_limitation_reason=comparison_limitation_reason,
        )
        self._log_result(question, result)
        return result

    # ── Multi-metric summaries (additive; never replaces metric_column) ───────

    def _compute_metric_summaries(
        self,
        plan: "QueryPlan | None",
        query_result: QueryResult,
        metric_aliases: dict[str, str] | None,
        labels: list[str],
        result_shape: ResultShape,
    ) -> dict[str, MetricSummary]:
        if not plan or not plan.metrics:
            return {}
        aliases = metric_aliases or {}
        summaries: dict[str, MetricSummary] = {}
        for metric_id in plan.metrics:
            column = aliases.get(metric_id, metric_id)
            if column not in query_result.columns:
                continue
            values = self._numeric_values(query_result, column)
            if not values:
                continue
            labeled = list(zip(labels, values, strict=True)) if len(labels) == len(values) else []
            top_dimension = bottom_dimension = None
            if labeled:
                ranked = calculators.rank(labeled)
                top_dimension, bottom_dimension = ranked[0][0], ranked[-1][0]
            is_scalar = result_shape in {
                ResultShape.SCALAR_AGGREGATE,
                ResultShape.MULTI_METRIC_SCALAR_AGGREGATE,
            }
            summaries[metric_id] = MetricSummary(
                metric_id=metric_id,
                metric_label=get_metric_label(metric_id),
                total=None if is_scalar else calculators.total(values),
                average=None if is_scalar else calculators.average(values),
                minimum=None if is_scalar else calculators.minimum(values),
                maximum=None if is_scalar else calculators.maximum(values),
                top_dimension=None if is_scalar else top_dimension,
                bottom_dimension=None if is_scalar else bottom_dimension,
                value=values[0] if is_scalar else None,
                format=self._metric_presentation(metric_id)[0],
                unit=self._metric_presentation(metric_id)[1],
            )
        return summaries

    def _displayable_kpis(
        self,
        plan: "QueryPlan | None",
        query_result: QueryResult,
        metric_aliases: dict[str, str] | None,
        result_shape: ResultShape,
    ) -> list[DisplayableKPI]:
        if result_shape not in {
            ResultShape.SCALAR_AGGREGATE,
            ResultShape.MULTI_METRIC_SCALAR_AGGREGATE,
        } or not plan or not query_result.rows:
            return []
        aliases = metric_aliases or {}
        row = query_result.rows[0]
        items: list[DisplayableKPI] = []
        for metric_id in plan.metrics:
            column = aliases.get(metric_id, metric_id)
            value = row.get(column)
            if value is None:
                continue
            fmt, unit = self._metric_presentation(metric_id)
            items.append(
                DisplayableKPI(
                    key=metric_id,
                    label=get_metric_label(metric_id),
                    value=value,
                    format=fmt,
                    unit=unit,
                )
            )
        return items

    def _metric_presentation(self, metric_id: str) -> tuple[str, str | None]:
        metadata = build_column_metadata([metric_id], resolved_metrics=[metric_id])[0]
        return str(metadata["format"]), metadata["unit"]

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

    def _question_preferred_column(self, question: str, candidates: list[str]) -> str | None:
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
                question_token.startswith(column_token) or column_token.startswith(question_token)
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
        plan: "QueryPlan | None" = None,
    ) -> DataShape:
        if query_result.row_count == 0:
            return DataShape.EMPTY
        # A plan that explicitly requested a grouping dimension defines a
        # GROUPED result contract regardless of how many rows the live data
        # happened to produce — a single branch matching the date range is
        # still a legitimate one-row slice of a grouped comparison, never a
        # bare scalar/single-record summary. Row-count-only classification
        # would otherwise misclassify it as SINGLE_ROW and silently flatten a
        # multi-metric grouped answer into one arbitrary scalar value.
        planned_dimension_present = bool(
            plan
            and plan.dimensions
            and any(
                dimension.lower() in {c.lower() for c in query_result.columns}
                for dimension in plan.dimensions
            )
        )
        if query_result.row_count == 1 and not planned_dimension_present:
            if len(query_result.columns) == 1 and metric_column:
                return DataShape.SINGLE_VALUE
            return DataShape.SINGLE_ROW
        if temporal_column and metric_column:
            return DataShape.TIME_SERIES
        if planned_dimension_present or (metric_column and len(query_result.columns) >= 2):
            return DataShape.CATEGORICAL
        return DataShape.TABULAR

    def _classify_result_shape(
        self,
        query_result: QueryResult,
        data_shape: DataShape,
        plan: "QueryPlan | None",
    ) -> ResultShape:
        if query_result.row_count == 0:
            return ResultShape.EMPTY
        metric_count = len(plan.metrics) if plan else 0
        dimension_count = len(plan.dimensions) if plan else 0
        if metric_count and not dimension_count and query_result.row_count == 1:
            return (
                ResultShape.SCALAR_AGGREGATE
                if metric_count == 1
                else ResultShape.MULTI_METRIC_SCALAR_AGGREGATE
            )
        if data_shape == DataShape.TIME_SERIES:
            return ResultShape.TIME_SERIES
        if dimension_count:
            return ResultShape.CATEGORICAL_GROUPED_RESULT
        if metric_count:
            return ResultShape.GROUPED_ROWS
        return ResultShape.RAW_RECORD_ROWS

    def _numeric_values(self, query_result: QueryResult, metric_column: str | None) -> list[float]:
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
        grain: str | None = None,
    ) -> "_ComputedMetrics":
        if not values:
            return _ComputedMetrics(scalar={"count": 0}, trend_metrics=None)

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
        trend_metrics = None

        if data_shape == DataShape.TIME_SERIES:
            # highest_period/lowest_period/largest_change stay over the FULL
            # series — presentational facts about the returned chart, which
            # must keep a partial trailing bucket. Only the endpoint/slope/
            # consistency verdict below excludes it.
            if labeled:
                ranked = calculators.rank(labeled)
                metrics["highest_period"] = ranked[0][0]
                metrics["lowest_period"] = ranked[-1][0]
                metrics["largest_change"] = calculators.largest_change(labels, values)

            trend_metrics = compute_trend_metrics(labels, values, grain, date.today())
            # difference/percentage_change/growth_rate/trend_direction are kept
            # as backward-compatible aliases of the endpoint verdict — computed
            # over comparable (complete) periods only, which is what actually
            # reconciles them with each other (they used to be independently
            # computed over the full series, including any partial trailing
            # bucket, which could contradict one another).
            metrics["difference"] = trend_metrics.endpoint_change
            metrics["percentage_change"] = trend_metrics.endpoint_percentage_change
            metrics["growth_rate"] = trend_metrics.endpoint_percentage_change
            metrics["trend_direction"] = trend_metrics.endpoint_direction
            metrics["endpoint_change"] = trend_metrics.endpoint_change
            metrics["endpoint_percentage_change"] = trend_metrics.endpoint_percentage_change
            metrics["endpoint_direction"] = trend_metrics.endpoint_direction
            metrics["slope"] = trend_metrics.slope
            metrics["slope_direction"] = trend_metrics.slope_direction
            metrics["monotonicity"] = trend_metrics.monotonicity
            metrics["trend_consistency"] = trend_metrics.trend_consistency
            metrics["volatility"] = trend_metrics.volatility
            metrics["comparable_period_count"] = trend_metrics.comparable_period_count
            metrics["first_comparable_period"] = trend_metrics.first_comparable_period
            metrics["last_comparable_period"] = trend_metrics.last_comparable_period
            metrics["comparison_excluded_partial_period"] = (
                trend_metrics.comparison_excluded_partial_period
            )
            # Turkish direction words for template engines that fill
            # {placeholder} slots directly from metrics (app.intelligence
            # RULE_WORDINGS) — never invented, just a fixed translation of the
            # already-computed direction verdict.
            metrics["slope_direction_tr"] = _SLOPE_DIRECTION_TR.get(trend_metrics.slope_direction)
            metrics["endpoint_direction_tr"] = _ENDPOINT_DIRECTION_TR.get(
                trend_metrics.endpoint_direction
            )
            metrics["endpoint_direction_adjective_tr"] = _ENDPOINT_DIRECTION_ADJECTIVE_TR.get(
                trend_metrics.endpoint_direction
            )

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

        return _ComputedMetrics(scalar=metrics, trend_metrics=trend_metrics)

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

    def _analytics_type(self, intents: list[AnalyticsIntent], data_shape: DataShape) -> str:
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
                "metric_summary_count": len(result.metric_summaries),
                "metric_summary_ids": sorted(result.metric_summaries),
                "comparison_category_count": result.comparison_category_count,
                "comparison_sufficient": result.comparison_sufficient,
                "partial_periods": (
                    result.trend_metrics.partial_periods if result.trend_metrics else []
                ),
                "excluded_periods": (
                    result.trend_metrics.excluded_periods if result.trend_metrics else []
                ),
                "comparable_period_count": (
                    result.trend_metrics.comparable_period_count if result.trend_metrics else None
                ),
            },
        )
