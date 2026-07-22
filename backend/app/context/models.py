from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.context.analytical_signals import AnalyticalSignals


class ExtractedSignals(BaseModel):
    """Deterministic context signals detected in a single user question."""

    date_expression: Optional[str] = Field(
        default=None,
        description="Raw temporal expression as the user wrote it (e.g. 'bugün', 'geçen hafta').",
    )
    department: Optional[str] = Field(
        default=None, description="Canonical department name mentioned in the question."
    )
    entity_types: List[str] = Field(
        default_factory=list,
        description="Domain entity types mentioned (Doctor, Patient, Appointment, ...).",
    )
    pronouns: List[str] = Field(
        default_factory=list,
        description="Referential pronouns found ('bunlardan', 'onlar', 'o bölüm', ...).",
    )
    analysis_type: Optional[str] = Field(
        default=None,
        description="Detected analysis style: ranking | comparison | trend | count | list.",
    )
    is_analytical: bool = Field(
        default=False,
        description="Whether the question carries an aggregate/ranking/count cue.",
    )
    asks_department: bool = Field(
        default=False,
        description="Whether the question itself asks about departments (blocks department inheritance).",
    )
    is_date_only_followup: bool = Field(
        default=False,
        description="Whether the question is only a new date filter (e.g. 'Peki geçen ay?').",
    )
    is_elliptical: bool = Field(
        default=False,
        description="Whether the question is short enough (few content tokens) to plausibly "
        "depend on the previous turn rather than being a complete, independent question. "
        "Deterministic proxy for 'missing subject / clear dependency on previous turn' — "
        "never used alone, only combined with an analytical/entity cue.",
    )


class PendingClarification(BaseModel):
    """Bounded pending clarification state (e.g. an ambiguous ranking metric).

    Deliberately minimal and never overwrites the last valid analytical
    context — set only via ContextManager.set_pending_clarification(), which
    touches nothing else in the session's context.
    """

    field: str = Field(
        ..., description="Name of the field awaiting clarification (e.g. 'ranking_metric', "
        "or 'value_filter:<field>' for AI-INTELLIGENCE-016/017 grounded value clarification)."
    )
    reason: str = Field(..., description="Why the previous turn was ambiguous.")
    choices: List[str] = Field(
        default_factory=list, description="Candidate values offered to the user, if any."
    )
    # ── AI-INTELLIGENCE-017: typed context for grounded value clarification ──
    # Snapshot of the ORIGINAL analytical request at the moment clarification
    # was raised, so a reply ("hepsini", "ilkini", an explicit value) can
    # resume planning without losing the original question's intent (item 7).
    original_question: Optional[str] = Field(
        default=None, description="Full question text that triggered this clarification."
    )
    candidate_values: List[str] = Field(
        default_factory=list, description="Grounded candidate values offered (ordinal-addressable)."
    )
    original_analysis_type: Optional[str] = Field(default=None)
    original_metrics: List[str] = Field(default_factory=list)
    original_dimensions: List[str] = Field(default_factory=list)
    original_date_expression: Optional[str] = Field(default=None)
    original_filters: Dict[str, List[str]] = Field(
        default_factory=dict, description="Other grounded filter families already resolved this turn."
    )


class ConversationTurn(BaseModel):
    """One user interaction retained in the short-term context window."""

    question: str = Field(..., description="Original user question.")
    resolved_question: str = Field(..., description="Question after context resolution.")
    signals: ExtractedSignals = Field(
        default_factory=ExtractedSignals, description="Signals extracted from the resolved question."
    )


class ConversationContext(BaseModel):
    """Short-term conversational state for a single chat session.

    Holds only the latest explicit filters — each new explicit user statement
    replaces the previous value of the same type (context expiration rule).
    """

    session_id: str = Field(..., description="Opaque session key.")
    date_expression: Optional[str] = Field(
        default=None, description="Latest explicit temporal filter expression."
    )
    department: Optional[str] = Field(
        default=None, description="Latest explicitly mentioned department."
    )
    entity_types: List[str] = Field(
        default_factory=list, description="Entity types from the latest entity-bearing question."
    )
    analysis_type: Optional[str] = Field(
        default=None, description="Latest detected analysis style."
    )
    last_question: Optional[str] = Field(
        default=None, description="Most recent resolved question (used for date-only follow-ups)."
    )
    turns: List[ConversationTurn] = Field(
        default_factory=list, description="Sliding window of recent interactions."
    )
    updated_at: float = Field(
        default=0.0, description="Monotonic-ish wall-clock timestamp of the last interaction."
    )

    # ── Typed analytical follow-up signals (see app.context.analytical_signals) ──
    # Sourced from the authoritative post-execution QueryPlan whenever available
    # (see ContextManager.update`), never a second independent NLU guess.
    branch_filters: List[str] = Field(
        default_factory=list, description="Latest branch filter values (schema-grounded)."
    )
    doctor_filters: List[str] = Field(
        default_factory=list, description="Latest doctor filter values (schema-grounded)."
    )
    department_filters: List[str] = Field(
        default_factory=list,
        description="Latest department filter values, list form of `department` above "
        "(kept in sync; `department` remains the legacy singular field).",
    )
    status_filters: List[str] = Field(
        default_factory=list, description="Latest RandevuDurumu filter values (schema-grounded)."
    )
    service_filters: List[str] = Field(
        default_factory=list, description="Latest service filter values."
    )
    category_filters: List[str] = Field(
        default_factory=list, description="Latest category filter values."
    )
    source_filters: List[str] = Field(
        default_factory=list, description="Latest appointment-source filter values."
    )
    metrics: List[str] = Field(
        default_factory=list, description="Latest metric catalog ids (see metric_catalog.json)."
    )
    dimensions: List[str] = Field(
        default_factory=list,
        description="Latest grouping dimensions: branch|doctor|department|status|service|"
        "category|source|appointment_type|gender|nationality|date.",
    )
    ranking: Optional[str] = Field(default=None, description="Latest ranking direction: top|bottom.")
    limit: Optional[int] = Field(default=None, description="Latest explicit row/group limit.")
    time_grain: Optional[str] = Field(
        default=None, description="Latest time bucket: day|week|month|quarter|year."
    )
    comparison_targets: List[str] = Field(
        default_factory=list, description="Latest comparison period descriptors."
    )
    query_plan_snapshot: dict[str, Any] | None = Field(
        default=None,
        description="Serialized QueryPlan from the latest successful analytical turn. "
        "This is the authoritative structured continuation snapshot; result rows, "
        "reports, and visualizations are deliberately excluded.",
    )
    pending_clarification: Optional[PendingClarification] = Field(
        default=None,
        description="Bounded pending clarification state (e.g. ambiguous ranking metric). "
        "Never blocks or overwrites the rest of this context's valid fields.",
    )

    def is_empty(self) -> bool:
        """Returns True when no inheritable context has been accumulated yet."""
        return not (
            self.date_expression
            or self.department
            or self.entity_types
            or self.last_question
            or self.dimensions
            or self.metrics
            or self.status_filters
            or self.branch_filters
            or self.doctor_filters
            or self.service_filters
            or self.category_filters
            or self.source_filters
            or self.ranking
            or self.limit
            or self.time_grain
            or self.comparison_targets
        )

    def analytical_signals(self) -> AnalyticalSignals:
        """Snapshot of the currently stored typed analytical signals."""
        return AnalyticalSignals(
            dimensions=list(self.dimensions),
            metrics=list(self.metrics),
            ranking=self.ranking,
            limit=self.limit,
            time_grain=self.time_grain,
            comparison_targets=list(self.comparison_targets),
            status_filters=list(self.status_filters),
            department_filters=list(self.department_filters),
            branch_filters=list(self.branch_filters),
            doctor_filters=list(self.doctor_filters),
            service_filters=list(self.service_filters),
            category_filters=list(self.category_filters),
            source_filters=list(self.source_filters),
        )


class ResolutionResult(BaseModel):
    """Outcome of resolving one question against the session context."""

    original_question: str = Field(..., description="Question exactly as the user typed it.")
    resolved_question: str = Field(..., description="Context-enriched question sent to the NLU pipeline.")
    inherited: Dict[str, str] = Field(
        default_factory=dict,
        description="Filters inherited from context, keyed by type (date, department, referent, ...).",
    )
    confidence: float = Field(
        default=1.0, description="Deterministic confidence of the applied resolution."
    )
    applied: bool = Field(
        default=False, description="Whether any context enrichment was applied."
    )
    clarification_needed: bool = Field(
        default=False, description="Whether the follow-up is ambiguous and needs clarification."
    )
    clarification_question: Optional[str] = Field(
        default=None, description="Clarification question to surface to the user."
    )
    clarification_options: List[str] = Field(
        default_factory=list, description="Candidate referents offered to the user."
    )

    # Explicit follow-up diagnostics (deterministic, never LLM-derived). These
    # describe *why* a resolution decision was made and must never be inferred
    # from session membership, entity overlap, or the presence of a date alone.
    follow_up_detected: bool = Field(
        default=False,
        description="Whether at least one strong, deterministic follow-up signal fired "
        "(pronoun/reference, elliptical short-form, date-only continuation, negation "
        "continuation) — independent of whether inheritance was ultimately applied "
        "(e.g. still False when a pronoun was found but the referent was ambiguous).",
    )
    follow_up_confidence: float = Field(
        default=1.0, description="Alias of `confidence` under the follow-up-specific name."
    )
    follow_up_signals: List[str] = Field(
        default_factory=list,
        description="Names of the deterministic follow-up signals that fired for this "
        "question (e.g. 'pronoun_reference', 'date_only_followup', "
        "'elliptical_department_inherit').",
    )
    context_applied: bool = Field(
        default=False, description="Alias of `applied` under the context-specific name."
    )
    overridden_fields: List[str] = Field(
        default_factory=list,
        description="Field names the current turn stated explicitly, replacing a "
        "different value previously held in session context (explicit-value "
        "precedence: current explicit statement always wins over inherited memory).",
    )

    # ── Typed analytical context handoff (Part 8) ─────────────────────────────
    # `resolved_signals` is the source of truth for what this turn's analytical
    # context actually is, after merging current-turn-explicit / inherited /
    # default per app.context.merge_policy. The free-text `resolved_question`
    # above remains the mechanism that actually drives the NLU/planning
    # pipeline in this iteration; `resolved_signals` is authoritative for the
    # context layer's own bookkeeping, diagnostics, and API contract.
    explicit_fields: List[str] = Field(
        default_factory=list,
        description="Analytical field names the current turn stated explicitly "
        "(via raw-text fallback matching before planning runs).",
    )
    removed_fields: List[str] = Field(
        default_factory=list,
        description="Field names that held a value in session context but were cleared "
        "or replaced with a different family this turn (e.g. 'dimensions' when the "
        "branch dimension was replaced by doctor).",
    )
    resolved_signals: AnalyticalSignals = Field(
        default_factory=AnalyticalSignals,
        description="Typed analytical signals for this turn after merging current-turn "
        "explicit values, inheritance, and defaults.",
    )
    pending_clarification_resolved: bool = Field(
        default=False,
        description="Whether this turn resolved a previously pending clarification "
        "(e.g. answering 'Gerçekleşme oranına göre' after an ambiguous ranking question).",
    )
    filter_override: Dict[str, List[str]] = Field(
        default_factory=dict,
        description="AI-INTELLIGENCE-017: fields resolved by this turn's pending "
        "value-clarification reply, threaded into AgentState.forced_filter_override. "
        "Empty list = 'clear this filter family' (an 'all' reply); non-empty = the "
        "chosen grounded value(s).",
    )
    retained_query_plan_snapshot: dict[str, Any] | None = Field(
        default=None,
        description="Previous successful QueryPlan snapshot made available only when "
        "this turn is a genuine follow-up. Independent questions receive None.",
    )
