
from pydantic import BaseModel, Field


class JoinStep(BaseModel):
    """One foreign-key hop on the minimal join path."""

    from_table: str = Field(..., description="Table owning the foreign key column.")
    from_column: str = Field(..., description="Foreign key column name.")
    to_table: str = Field(..., description="Referenced table name.")
    to_column: str = Field(..., description="Referenced (usually primary key) column name.")

    def render(self) -> str:
        return f"{self.from_table}.{self.from_column} -> {self.to_table}.{self.to_column}"


class DateFilterPlan(BaseModel):
    """A temporal constraint carried into the plan."""

    expression: str = Field(..., description="Original temporal wording (e.g. 'bugun').")
    start_date: str = Field(..., description="ISO start date of the range.")
    end_date: str = Field(..., description="ISO end date of the range.")
    column: str | None = Field(
        default=None, description="Date column on the fact table, when one is discoverable."
    )


class PeriodPlan(BaseModel):
    """One ordered comparison period with half-open date boundaries."""

    label: str = Field(..., description="Human-readable period label.")
    start_inclusive: str = Field(..., description="ISO inclusive lower boundary.")
    end_exclusive: str = Field(..., description="ISO exclusive upper boundary.")
    column: str | None = Field(
        default=None, description="Date column used by the comparison predicate."
    )


class PlannedMetric(BaseModel):
    """One metric the plan requires, resolved from the metric catalog.

    Additive companion to the legacy `QueryPlan.metrics` id list — carries the
    catalog-resolved shape of each metric (formula type/result format/source
    columns) without requiring downstream readers to re-look-up the catalog.
    `expression`/`alias` stay unset until the SQL builder resolves them.
    """

    metric_id: str = Field(..., description="Metric catalog id (app/resources/metric_catalog.json).")
    expression: str | None = Field(default=None, description="Resolved SQL expression, set by the SQL builder.")
    alias: str | None = Field(default=None, description="SELECT alias chosen by the SQL builder.")
    aggregation_type: str | None = Field(
        default=None, description="Catalog formula_type: count_rows | avg | conditional_rate | ..."
    )
    format_type: str | None = Field(default=None, description="Catalog result_type: integer | float | percentage.")
    conditional_filter: str | None = Field(
        default=None, description="Status/condition predicate the metric's formula depends on, if any."
    )
    source_columns: list[str] = Field(
        default_factory=list, description="Catalog required_columns this metric depends on."
    )


class PlannedDimension(BaseModel):
    """One grouping dimension the plan requires, resolved from catalog/schema."""

    column: str = Field(..., description="Real view column to group/filter by.")
    canonical_name: str | None = Field(
        default=None,
        description="Canonical dimension vocabulary name (branch|doctor|department|status|"
        "service|category|source|date), when resolvable.",
    )


class QueryPlan(BaseModel):
    """Deterministic contract between NLU and SQL generation (AG-022).

    Organizes every constraint the NLU extracted so none silently disappears
    between question understanding and SQL generation. Never contains SQL.
    """

    question: str = Field(..., description="Question the plan was built from.")
    output_entity: str | None = Field(
        default=None, description="Entity type the user wants returned (e.g. Doctor)."
    )
    fact_entity: str | None = Field(
        default=None, description="Entity type being filtered/aggregated over (e.g. Appointment)."
    )
    output_table: str | None = Field(
        default=None, description="Schema table backing the output entity."
    )
    fact_table: str | None = Field(
        default=None, description="Schema table backing the fact entity."
    )
    date_filters: list[DateFilterPlan] = Field(
        default_factory=list, description="Temporal constraints, already resolved to ISO ranges."
    )
    periods: list[PeriodPlan] = Field(
        default_factory=list,
        description=(
            "Ordered comparison periods. The first period is the baseline and the "
            "second period is the current period."
        ),
    )
    department_filter: str | None = Field(
        default=None, description="Department name constraint, as stored in the database."
    )
    extra_filters: list[str] = Field(
        default_factory=list,
        description="Additional textual constraints that must survive (e.g. negation).",
    )
    aggregation: str | None = Field(
        default=None, description="Required aggregate function: COUNT, SUM, or AVG."
    )
    ranking: str | None = Field(
        default=None, description="Required ranking direction: DESC or ASC."
    )
    limit: int | None = Field(default=None, description="Explicit LIMIT requested.")
    order: str | None = Field(default=None, description="Explicit ordering direction.")
    analysis_type: str | None = Field(
        default=None, description="ranking | comparison | trend | count | list."
    )
    join_path: list[JoinStep] = Field(
        default_factory=list, description="Minimal FK path connecting fact, output, and filters."
    )
    projection: list[str] = Field(
        default_factory=list, description="Descriptive column(s) the SELECT must return."
    )
    distinct: bool = Field(
        default=False, description="Whether the output requires DISTINCT rows."
    )
    # ── Agent Intelligence Foundation (catalog-driven analytics) ──
    metrics: list[str] = Field(
        default_factory=list, description="Metric catalog ids resolved from the question."
    )
    dimensions: list[str] = Field(
        default_factory=list, description="Grouping dimension columns resolved from catalogs."
    )
    planned_metrics: list[PlannedMetric] = Field(
        default_factory=list,
        description="Catalog-resolved shape of every id in `metrics`. Additive/optional — "
        "prefer this over `metrics` for new consumers when populated; falls back to `metrics` "
        "otherwise. `aggregation`/`analysis_type` (below) remain legacy singular convenience "
        "fields derived only when exactly one metric is planned; they never represent a "
        "multi-metric plan on their own.",
    )
    planned_dimensions: list[PlannedDimension] = Field(
        default_factory=list, description="Catalog/schema-resolved shape of every entry in `dimensions`."
    )
    numerator: str | None = Field(
        default=None, description="Numerator metric id for ratio/percentage analyses."
    )
    denominator: str | None = Field(
        default=None, description="Denominator metric id for ratio/percentage analyses."
    )
    grouping_granularity: str | None = Field(
        default=None, description="Time bucket for trend analyses: hour | day | week | month."
    )
    comparisons: list[str] = Field(
        default_factory=list,
        description="Period comparison descriptors (e.g. current vs previous).",
    )
    derived_calculations: list[str] = Field(
        default_factory=list,
        description="Derived expressions the SQL must compute (e.g. age group).",
    )
    required_columns: list[str] = Field(
        default_factory=list, description="Real view columns the plan depends on."
    )
    answerable: bool = Field(
        default=True, description="Whether the question is answerable with the available columns."
    )
    answerability_reason: str | None = Field(
        default=None, description="Why the question cannot be answered, when answerable is False."
    )
    confidence: float | None = Field(
        default=None, description="Deterministic 0-1 confidence of the semantic resolution."
    )
    matched_examples: list[str] = Field(
        default_factory=list,
        description="Golden dataset example ids retrieved for few-shot context.",
    )
    # ── AI-INTELLIGENCE-008: explicit query strategy for implicit questions ──
    question_goal: str | None = Field(
        default=None, description="Explicit analytical goal resolved from implicit wording."
    )
    current_period: str | None = Field(
        default=None, description="Descriptor of the analysis period (e.g. last_30_days)."
    )
    baseline_period: str | None = Field(
        default=None, description="Descriptor of the comparison baseline (e.g. previous_30_days)."
    )
    cohort: str | None = Field(
        default=None, description="Cohort filter definition (e.g. lead time < 24h)."
    )
    minimum_sample_size: int | None = Field(
        default=None, description="Groups below this row count are flagged as low-sample."
    )
    assumptions: list[str] = Field(
        default_factory=list,
        description="Human-readable defaults the agent picked; must be stated in the answer.",
    )
    planner_ms: float = Field(default=0.0, description="Planning duration in milliseconds.")

    def constraint_count(self) -> int:
        """Number of hard constraints the plan carries (used for logging)."""
        return (
            len(self.date_filters)
            + (1 if self.department_filter else 0)
            + len(self.extra_filters)
            + (1 if self.aggregation else 0)
            + (1 if self.ranking else 0)
            + (1 if self.limit else 0)
        )


class ComplianceResult(BaseModel):
    """Outcome of validating generated SQL against a QueryPlan."""

    compliant: bool = Field(..., description="True when no planned constraint is missing.")
    missing: list[str] = Field(
        default_factory=list, description="Human-readable list of missing constraints."
    )
    missing_metrics: list[str] = Field(
        default_factory=list, description="Metric catalog ids from plan.metrics absent from the generated SQL."
    )
    missing_dimensions: list[str] = Field(
        default_factory=list, description="Dimension columns from plan.dimensions absent from the generated SQL."
    )
