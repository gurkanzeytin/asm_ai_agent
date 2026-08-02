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

    metric_id: str = Field(
        ..., description="Metric catalog id (app/resources/metric_catalog.json)."
    )
    expression: str | None = Field(
        default=None, description="Resolved SQL expression, set by the SQL builder."
    )
    alias: str | None = Field(default=None, description="SELECT alias chosen by the SQL builder.")
    aggregation_type: str | None = Field(
        default=None, description="Catalog formula_type: count_rows | avg | conditional_rate | ..."
    )
    format_type: str | None = Field(
        default=None, description="Catalog result_type: integer | float | percentage."
    )
    conditional_filter: str | None = Field(
        default=None,
        description="Status/condition predicate the metric's formula depends on, if any.",
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
        "service|category|source|appointment_type|gender|nationality|date), when resolvable.",
    )


class MetricPredicate(BaseModel):
    """A grounded row-level condition a metric is computed over.

    The point of this type is that the condition is DATA, not code. The metric
    catalog freezes its conditions into formulas — seven `conditional_rate`
    metrics are one SQL shape with seven hard-coded predicates — so a share the
    catalog never anticipated ("kadın hasta oranı", "randevu süresi 30
    dakikadan uzun olanların oranı") had no way to be expressed and silently
    degraded to a plain count. Parameterising the predicate answers the whole
    family without a new metric per question.

    Only ever built from already-grounded input: a value bound by
    `ValueResolver` against real database values, or a numeric literal parsed
    from the question. The SQL builder re-validates the column against the
    column catalog and the operator against its own allow-list before
    rendering, so an invalid predicate fails closed (metric skipped) rather
    than reaching SQL.
    """

    column: str = Field(..., description="Real view column the condition applies to.")
    operator: str = Field(..., description="One of =, <>, >, >=, <, <=, IS NULL, IS NOT NULL.")
    values: list[str | float] = Field(
        default_factory=list,
        description="Right-hand operand(s); empty for IS NULL / IS NOT NULL.",
    )


class InlineMetric(BaseModel):
    """A metric composed at plan time instead of looked up by catalog id.

    Coexists with the catalog: `QueryPlan.metrics` still carries catalog ids,
    and a catalog id always wins. An inline metric is only built when no
    catalog metric expresses what was asked.
    """

    shape: str = Field(..., description="Aggregate shape; 'rate' is the only one built today.")
    predicate: MetricPredicate | None = Field(
        default=None,
        description=(
            "Legacy single numerator condition. Used when numerator_predicates "
            "is empty so previously serialized plans remain valid."
        ),
    )
    numerator_predicates: list[MetricPredicate] = Field(
        default_factory=list,
        description=(
            "Grounded row conditions joined with AND to form the numerator. "
            "Empty falls back to the legacy predicate field."
        ),
    )
    denominator_predicates: list[MetricPredicate] = Field(
        default_factory=list,
        description=(
            "Grounded row conditions joined with AND to form a conditional "
            "denominator. Empty means all rows in the outer query scope."
        ),
    )
    label: str = Field(..., description="Turkish label shown to the user for this metric.")


class AggregateThreshold(BaseModel):
    """A HAVING-style threshold on the aggregated metric value.

    Captures "belirli bir sayıdan az/fazla olanları göster" wording — a filter
    on the grouped aggregate (COUNT/SUM/AVG), NOT on a raw column. Only
    meaningful when the plan groups by at least one dimension; a threshold
    without a GROUP BY has nothing to filter and is ignored by the builder.
    """

    operator: str = Field(..., description="Comparison operator: one of <, <=, >, >=.")
    value: float = Field(
        ..., description="Right-hand numeric bound the aggregate is compared against."
    )
    metric: str | None = Field(
        default=None,
        description="Metric id the threshold applies to; None means the plan's primary metric.",
    )


class ResolvedFilterPlan(BaseModel):
    """One field's grounded filter resolution (AI-INTELLIGENCE-016).

    Produced only by `app.planning.value_resolver.ValueResolver` against real
    distinct database values — never from rewritten free text. `values` is
    empty unless `grounded` is True; an ungrounded/ambiguous mention carries
    `clarification_required=True` and `alternatives` instead of a guessed value.
    """

    field: str = Field(
        ...,
        description="branch|doctor|department|service|category|"
        "appointment_source|appointment_status|appointment_type|nationality|gender.",
    )
    values: list[str] = Field(default_factory=list, description="Grounded canonical values.")
    source: str = Field(default="grounded_value_resolver", description="Resolution source.")
    confidence: float = Field(default=0.0, description="0-1 match confidence.")
    grounded: bool = Field(default=False, description="True only when `values` is a real match.")
    match_type: str | None = Field(
        default=None, description="exact|normalized_exact|alias|prefix|fuzzy|no_match|ambiguous."
    )
    original_text: str | None = Field(
        default=None, description="Raw text mention that was resolved."
    )
    clarification_required: bool = Field(default=False)
    clarification_message: str | None = Field(default=None)
    alternatives: list[str] = Field(default_factory=list, description="Safe candidate options.")


class QueryPlan(BaseModel):
    """Deterministic contract between NLU and SQL generation (AG-022).

    Organizes every constraint the NLU extracted so none silently disappears
    between question understanding and SQL generation. Never contains SQL.
    """

    question: str = Field(..., description="Question the plan was built from.")
    planning_source: str = Field(
        default="deterministic",
        description=(
            "deterministic | llm_schema_reasoning; controls bounded SQL generation strategy."
        ),
    )
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
    scope: str = Field(
        default="filtered",
        description="'all' when the question used a generic organization-wide phrase "
        "('tüm şubeler', 'kurum genelinde', ...) — no branch VALUE filter may be produced. "
        "'filtered' otherwise (the default: no scope claim either way).",
    )
    excluded_departments: list[str] = Field(
        default_factory=list,
        description="Grounded department values to EXCLUDE ('Kardiyoloji hariç bölüm "
        "bazında ...'). Rendered as an atomic NOT IN (dept-split) or a NOT-containment "
        "row filter. Empty means no department exclusion.",
    )
    branch_filters: list[str] = Field(
        default_factory=list,
        description="Grounded branch (SubeAdi) values only. Never populated from a generic "
        "organizational phrase or free-text guess — only from a real grounded catalog/database "
        "lookup or an exact match against a validated known branch value. Empty means "
        "'no branch value filter', not 'unknown branch'.",
    )
    generic_scope_phrase_detected: str | None = Field(
        default=None,
        description="The matched generic-scope wording (e.g. 'tüm aile sağlığı merkezleri'), "
        "for diagnostics; None when no such phrase was detected.",
    )
    resolved_filters: dict[str, ResolvedFilterPlan] = Field(
        default_factory=dict,
        description="Typed, grounded filter resolutions keyed by field name "
        "(AI-INTELLIGENCE-016). Source of truth for value filters other than "
        "branch_filters/department_filter — never derived from rewritten free text.",
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
    percentile: int | None = Field(
        default=None,
        description="Top/bottom percentile slice requested ('en üstteki %10') — "
        "rendered as T-SQL TOP (N) PERCENT with the ranking ORDER BY. 1-99.",
    )
    aggregate_threshold: AggregateThreshold | None = Field(
        default=None,
        description="HAVING-style filter on the grouped aggregate value "
        "('200'den az randevusu olan bölümler'). Applied only when the plan groups.",
    )
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
    distinct: bool = Field(default=False, description="Whether the output requires DISTINCT rows.")
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
        default_factory=list,
        description="Catalog/schema-resolved shape of every entry in `dimensions`.",
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
    metric_specs: dict[str, InlineMetric] = Field(
        default_factory=dict,
        description=(
            "Metrics composed at plan time, keyed by the SQL alias they are selected as. "
            "An alias appearing in `metrics` is resolved from the catalog first and from "
            "here only when the catalog has no such id."
        ),
    )
    partial_reading_reasons: list[str] = Field(
        default_factory=list,
        description=(
            "Why this plan is a PARTIAL reading of its question (app.planning.coverage). "
            "Diagnostic only today — nothing routes on it yet."
        ),
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
        default_factory=list,
        description="Metric catalog ids from plan.metrics absent from the generated SQL.",
    )
    missing_dimensions: list[str] = Field(
        default_factory=list,
        description="Dimension columns from plan.dimensions absent from the generated SQL.",
    )
