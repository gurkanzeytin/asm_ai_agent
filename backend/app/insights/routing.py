"""Complexity-based routing between deterministic insight generation, a local
LLM (Ollama/qwen3), and a remote LLM (NVIDIA/DeepSeek).

The router is a pure function of structured analytics signals already computed
by the deterministic layers (data shape, detected intents, business rules,
metric richness) plus a remote-data-policy check reused from
``app.llm.remote_policy``. It never inspects the raw question text and never
hard-codes a specific question — routing happens at the analysis-family level.

Deterministic candidacy is decided BEFORE complexity scoring, and does not
depend on which generic rules fired. ``DOMINANT_CATEGORY`` and
``OUTLIER_DETECTED`` are routine outputs of ``InsightRulesEngine`` on
perfectly ordinary small distributions (one category being the largest is the
normal case, not evidence of genuine complexity) — they must never, by
themselves, push a simple one-dimensional grouping to a remote model. Only
combined with genuine complexity signals (a time series, many rows/categories,
multiple intents, or an explicit statistical intent) does an outlier become
worth a stronger model's reasoning.

This module makes the decision; it does not call any provider. ``InsightEngine``
executes the decision and owns fallback behavior.
"""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.analytics.models import AnalyticsIntent, AnalyticsResult, DataShape
from app.insights.models import InsightConfidence, InsightRule
from app.llm.remote_policy import find_prohibited_fields

# Default cap on result size for deterministic candidacy — a one-dimensional
# grouping/comparison with more rows than this is still "simple" in shape but
# too large to summarize as a single deterministic sentence.
_DETERMINISTIC_MAX_ROWS_DEFAULT = 20

# Once a case has already failed deterministic candidacy, this (smaller,
# independent) threshold marks "many periods/categories to reason across" as
# a genuine complexity signal for remote-routing purposes.
_COMPLEXITY_MANY_ROWS_THRESHOLD = 6

# A period-over-period growth_rate at or beyond this magnitude (%) is treated
# as a genuine time-series anomaly signal — InsightRulesEngine's
# OUTLIER_DETECTED rule only ever fires for CATEGORICAL data, so trend
# anomalies need this separate, metrics-derived signal. AI-INTELLIGENCE-018
# (item 5): raised from 50% — an ordinary single-metric monthly trend can
# easily swing 50-60% endpoint-to-endpoint on modest absolute counts (e.g.
# 12 -> 19 appointments = +58%) without being a genuine anomaly; only a
# multi-hundred-percent swing is worth a stronger model's reasoning on its
# own, independent of metric/dimension count.
_EXTREME_GROWTH_RATE_THRESHOLD = 100.0

# Intents that signal an explicitly statistical/forecasting question rather
# than a plain grouping or trend — these always block deterministic candidacy,
# regardless of shape or row count.
_STATISTICAL_INTENTS = frozenset({AnalyticsIntent.CORRELATION, AnalyticsIntent.FORECAST})

# Shapes simple enough that no narrative reasoning is needed at all.
_TRIVIAL_SHAPES = (DataShape.EMPTY, DataShape.SINGLE_VALUE, DataShape.SINGLE_ROW)


class InsightGenerationMode(StrEnum):
    """Reusable routing decision — never encoded as question-string checks."""

    DETERMINISTIC = "deterministic"
    LOCAL_LLM = "local_llm"
    REMOTE_LLM = "remote_llm"


class RoutingDecision(BaseModel):
    """Safe, loggable diagnostic describing why a routing choice was made.

    Never carries prompts, rows, secrets, or PII — only structural signals
    already safe to log (shape, rule names, counts, booleans).
    """

    model_config = ConfigDict(frozen=True)

    deterministic_candidate: bool = Field(
        description="Whether the analysis family qualified for deterministic "
        "generation BEFORE any complexity scoring was even computed."
    )
    deterministic_reason: str | None = Field(
        default=None, description="Why it did/didn't qualify as a deterministic candidate."
    )
    complexity_score: int = 0
    complexity_factors: list[str] = Field(
        default_factory=list, description="Signals that contributed to the complexity score."
    )
    blocking_factors: list[str] = Field(
        default_factory=list,
        description="Signals that disqualified this analysis from deterministic routing.",
    )

    mode: InsightGenerationMode = Field(description="Final selected generation mode.")
    selected_provider: str = Field(
        description="Final provider: 'deterministic', 'ollama', or 'nvidia' — never 'gemini'."
    )
    selected_model: str | None = None
    routing_reason: str
    remote_policy_status: str = Field(
        default="not_applicable", description="not_applicable | allowed | rejected"
    )

    @property
    def final_mode(self) -> InsightGenerationMode:
        return self.mode

    @property
    def final_provider(self) -> str:
        return self.selected_provider

    @property
    def final_model(self) -> str | None:
        return self.selected_model


class InsightRouter:
    """Derives an ``InsightGenerationMode`` from structured analytics signals."""

    def __init__(
        self,
        *,
        enabled: bool = True,
        deterministic_enabled: bool = True,
        remote_complexity_threshold: int = 3,
        remote_available: bool = True,
        deterministic_max_rows: int = _DETERMINISTIC_MAX_ROWS_DEFAULT,
    ) -> None:
        self.enabled = enabled
        self.deterministic_enabled = deterministic_enabled
        self.remote_complexity_threshold = remote_complexity_threshold
        self.remote_available = remote_available
        self.deterministic_max_rows = deterministic_max_rows

    # ── Deterministic candidacy (family-level, rule-agnostic) ─────────────────

    def _deterministic_candidate(
        self, analytics: AnalyticsResult, confidence: InsightConfidence
    ) -> tuple[bool, str, list[str]]:
        """Decides deterministic eligibility purely from analysis-family shape.

        Runs BEFORE complexity scoring and never looks at which generic rules
        fired — a dominant category or a statistically detected outlier on an
        ordinary small distribution is the normal case, not a complexity signal.

        Returns (is_candidate, reason, blocking_factors).
        """
        if confidence == InsightConfidence.LOW:
            return True, "insufficient_evidence", []
        if len(analytics.metric_summaries) >= 2:
            # Independent metrics with different units/scales can never be
            # summarized as a single deterministic sentence. Checked BEFORE
            # the trivial-shape short-circuit below: a grouped multi-metric
            # plan can legitimately return exactly one row (e.g. only one
            # branch matched a narrow date range) — AnalyticsEngine still
            # classifies that as CATEGORICAL when a planned dimension is
            # present, but a dimensionless multi-metric single-row/single-
            # value result must not slip past this check either just because
            # its shape happens to look "trivial" on row count alone.
            return False, "multi_metric_result", ["multi_metric_analysis"]
        if analytics.data_shape in _TRIVIAL_SHAPES:
            return True, "trivial_shape", []

        blocking: list[str] = []
        if any(intent in _STATISTICAL_INTENTS for intent in analytics.intents):
            blocking.append("statistical_or_forecast_intent")
        if len(analytics.intents) > 1:
            blocking.append("multi_intent_cross_dimensional_analysis")
        if analytics.row_count > self.deterministic_max_rows:
            blocking.append("result_size_exceeds_deterministic_threshold")

        if analytics.data_shape == DataShape.CATEGORICAL:
            # One-dimensional grouping: exactly the family AnalyticsEngine
            # produces from a single metric+label column pair. No time axis,
            # no second grouping dimension, no forecasting/correlation intent.
            if not blocking:
                return True, "simple_distribution", []
            return False, "categorical_but_blocked", blocking

        if analytics.data_shape == DataShape.TIME_SERIES:
            # A basic two-period "before vs after" comparison is still
            # deterministic — the difference/percentage_change metrics are
            # already computed. More than two periods is a real trend/anomaly
            # narrative, not a simple comparison.
            if not blocking and analytics.row_count <= 2:
                return True, "simple_period_comparison", []
            if not blocking:
                blocking.append("multi_period_time_series")
            return False, "time_series_blocked", blocking

        # TABULAR and any other shape: not a recognized simple family.
        blocking.append(f"unrecognized_or_multidimensional_shape:{analytics.data_shape.value}")
        return False, "shape_not_simple", blocking

    # ── Complexity scoring (only reached once past deterministic candidacy) ──

    def compute_complexity(
        self, analytics: AnalyticsResult, rules: list[InsightRule]
    ) -> tuple[int, list[str]]:
        """Scores analysis complexity for cases that already failed the
        deterministic-candidate check. Every term is a genuine complexity
        signal — a generic routine rule (DOMINANT_CATEGORY, OUTLIER_DETECTED,
        BALANCED_DISTRIBUTION, SINGLE_METRIC) never contributes on its own;
        OUTLIER_DETECTED only counts when combined with a real complexity
        driver (a time series or a large multi-category breakdown).
        """
        score = 0
        factors: list[str] = []

        is_multi_intent = len(analytics.intents) > 1
        metric_count = len(analytics.metric_summaries)

        if analytics.data_shape == DataShape.TIME_SERIES:
            score += 1
            factors.append("time_series_shape")
        if analytics.data_shape == DataShape.TABULAR:
            score += 1
            factors.append("tabular_multidimensional_shape")
        if is_multi_intent:
            score += 1
            factors.append("multi_intent_analysis")
        if analytics.data_shape == DataShape.TABULAR and is_multi_intent:
            # Genuine cross-dimensional analysis: multiple analytical intents
            # over an unclassified/multi-column shape, not just one signal.
            score += 1
            factors.append("cross_dimensional_multi_intent_analysis")
        if any(intent in _STATISTICAL_INTENTS for intent in analytics.intents):
            score += 1
            factors.append("statistical_or_forecast_intent")

        many_rows = (
            analytics.row_count > _COMPLEXITY_MANY_ROWS_THRESHOLD
            and analytics.data_shape in (DataShape.TIME_SERIES, DataShape.CATEGORICAL)
        )
        if many_rows:
            score += 1
            factors.append("many_periods_or_categories")

        # Multiple independent metrics (different units/scales — count, rate,
        # duration) requested together are a genuine complexity driver on
        # their own; broken down by a dimension as well (the CATEGORICAL/
        # TIME_SERIES shape a grouped multi-metric result always produces)
        # makes it a full cross-metric comparison, not a single number.
        if metric_count >= 3:
            score += 2
            factors.append("multi_metric_analysis")
            if analytics.data_shape in (DataShape.CATEGORICAL, DataShape.TIME_SERIES):
                score += 1
                factors.append("multi_metric_dimensional_breakdown")
        elif metric_count == 2:
            score += 1
            factors.append("multi_metric_analysis")

        genuinely_complex_context = (
            analytics.data_shape == DataShape.TIME_SERIES or many_rows or len(analytics.intents) > 1
        )
        if InsightRule.OUTLIER_DETECTED in rules and genuinely_complex_context:
            score += 2
            factors.append("outlier_in_complex_context")

        # Time-series-specific anomaly signal: InsightRulesEngine only ever
        # computes OUTLIER_DETECTED for CATEGORICAL data, so a genuinely
        # anomalous trend (an extreme period-over-period swing) needs its own
        # metrics-derived signal here — never invented, only the already
        # computed growth_rate magnitude.
        growth_rate = analytics.metrics.get("growth_rate")
        if (
            analytics.data_shape == DataShape.TIME_SERIES
            and isinstance(growth_rate, (int, float))
            and abs(growth_rate) >= _EXTREME_GROWTH_RATE_THRESHOLD
        ):
            score += 1
            factors.append("extreme_period_over_period_change")

        return score, factors

    # ── Decision ───────────────────────────────────────────────────────────────

    def decide(
        self,
        analytics: AnalyticsResult,
        rules: list[InsightRule],
        confidence: InsightConfidence,
        remote_texts: tuple[str, ...] = (),
    ) -> RoutingDecision:
        """Picks deterministic / local_llm / remote_llm for one insight call."""
        if not self.enabled:
            return RoutingDecision(
                deterministic_candidate=False,
                deterministic_reason="insight_routing_disabled",
                mode=InsightGenerationMode.LOCAL_LLM,
                selected_provider="ollama",
                routing_reason="insight_routing_disabled_defaulting_to_local",
            )

        is_candidate, det_reason, blocking_factors = self._deterministic_candidate(
            analytics, confidence
        )

        if self.deterministic_enabled and is_candidate:
            return RoutingDecision(
                deterministic_candidate=True,
                deterministic_reason=det_reason,
                mode=InsightGenerationMode.DETERMINISTIC,
                selected_provider="deterministic",
                selected_model="templates",
                routing_reason=det_reason,
            )

        complexity_score, complexity_factors = self.compute_complexity(analytics, rules)

        # Remote data policy screening — reused verbatim from the existing
        # guard. A patient-level/PII reference anywhere in the payload that
        # would be sent to an LLM forces the local provider, regardless of
        # complexity, and is never treated as a hard failure.
        matched_fields: list[str] = []
        for text in remote_texts:
            matched_fields.extend(find_prohibited_fields(text))
        if matched_fields:
            return RoutingDecision(
                deterministic_candidate=False,
                deterministic_reason=det_reason,
                complexity_score=complexity_score,
                complexity_factors=complexity_factors,
                blocking_factors=blocking_factors,
                mode=InsightGenerationMode.LOCAL_LLM,
                selected_provider="ollama",
                routing_reason="remote_policy_rejected_patient_level_fields",
                remote_policy_status="rejected",
            )

        # Complex multi-metric/anomaly/multi-dimensional analysis: remote,
        # only when the remote provider is actually configured/available.
        if complexity_score >= self.remote_complexity_threshold and self.remote_available:
            return RoutingDecision(
                deterministic_candidate=False,
                deterministic_reason=det_reason,
                complexity_score=complexity_score,
                complexity_factors=complexity_factors,
                blocking_factors=blocking_factors,
                mode=InsightGenerationMode.REMOTE_LLM,
                selected_provider="nvidia",
                routing_reason="complex_multi_metric_or_anomaly_analysis",
                remote_policy_status="allowed",
            )

        # Medium complexity, or remote unavailable: local model.
        reason = (
            "medium_complexity_local_default"
            if complexity_score < self.remote_complexity_threshold
            else "remote_unavailable_falling_back_to_local"
        )
        return RoutingDecision(
            deterministic_candidate=False,
            deterministic_reason=det_reason,
            complexity_score=complexity_score,
            complexity_factors=complexity_factors,
            blocking_factors=blocking_factors,
            mode=InsightGenerationMode.LOCAL_LLM,
            selected_provider="ollama",
            routing_reason=reason,
            remote_policy_status="allowed",
        )
