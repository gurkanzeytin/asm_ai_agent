import logging
import re

from pydantic import BaseModel, Field

from app.context.extractor import ContextExtractor
from app.services.query_analyzer import QueryAnalyzer

logger = logging.getLogger(__name__)

_UNSAFE_WRITE_SIGNAL_PREFIX = "unsafe_write_intent:"
_UNSAFE_WRITE_PATTERNS: tuple[tuple[str, str], ...] = (
    ("delete", r"\b(delete\s+from|sil\w*)\b"),
    ("drop", r"\b(drop\s+table|tablo\w*\s+sil\w*)\b"),
    ("truncate", r"\btruncate\s+table\b"),
    ("update", r"\b(update\s+\w+\s+set|guncelle\w*)\b"),
    ("insert", r"\b(insert\s+into|kayit\s+ekle\w*|veri\s+ekle\w*)\b"),
    ("alter", r"\balter\s+table\b"),
    ("create_table", r"\bcreate\s+table\b"),
)
class AnswerabilityResult(BaseModel):
    """Deterministic verdict on whether a question maps onto the schema domain."""

    answerable: bool = Field(..., description="True when the question can be attempted as SQL.")
    reason: str = Field(..., description="Short machine-readable reason for the verdict.")
    signals: list[str] = Field(
        default_factory=list, description="Domain signals detected in the question."
    )


class AnswerabilityInput(BaseModel):
    """Typed decision contract (AI-INTELLIGENCE-018, item 2).

    A short follow-up must be evaluated using the RESOLVED analytical context,
    not raw text alone. Built once in `ReportingService.run_workflow()` — the
    only place both `ContextResolver`'s output and the raw question coexist —
    and threaded through `AgentState` to `AnswerabilityGuard.assess()`.
    """

    raw_question: str = Field(..., description="Exactly as the user typed it.")
    resolved_question: str = Field(..., description="After ContextResolver rewriting/merge.")
    has_valid_prior_context: bool = Field(
        default=False, description="ResolutionResult.context_applied — real prior-turn "
        "analytical state was retained, replaced, or extended this turn."
    )
    resolved_metrics: list[str] = Field(default_factory=list)
    resolved_dimensions: list[str] = Field(default_factory=list)
    resolved_date_range: str | None = Field(
        default=None, description="Explicit or inherited date expression, if any."
    )
    context_operation: str | None = Field(
        default=None, description="The follow-up signal that fired this turn, if any "
        "(e.g. 'additive_or_replacement_followup', 'elliptical_analytical_followup', "
        "'date_only_followup', 'pronoun_reference') — None for an independent question.",
    )
    pending_clarification: bool = Field(
        default=False, description="Whether this turn resolved a pending clarification reply "
        "(e.g. 'hepsini') — such a reply is answerable by construction, never out-of-scope.",
    )

    def has_resolved_domain_context(self) -> bool:
        """A merged analytical context that carries a real metric or dimension
        is, by itself, sufficient domain evidence — independent of whatever
        the raw follow-up text alone would (fail to) signal."""
        return self.has_valid_prior_context and bool(
            self.resolved_metrics or self.resolved_dimensions
        )


class AnswerabilityGuard:
    """Decides whether a database-bound question is inside the schema domain (AG-022).

    Purely deterministic: a question is answerable when it carries at least one
    domain signal — a known entity (doctor, patient, appointment, ...), a
    department name, or a temporal filter combined with an aggregate operation.
    Questions with no domain signal at all (weather, stocks, generic talk that
    leaked past intent classification) are diverted to OUT_OF_SCOPE guidance
    instead of producing hallucinated SQL.
    """

    def __init__(
        self,
        query_analyzer: QueryAnalyzer | None = None,
        context_extractor: ContextExtractor | None = None,
    ) -> None:
        self._query_analyzer = query_analyzer or QueryAnalyzer()
        self._context_extractor = context_extractor or ContextExtractor()

    def assess(
        self,
        question: str,
        resolved_context_signals: list[str] | None = None,
        context: "AnswerabilityInput | None" = None,
    ) -> AnswerabilityResult:
        try:
            return self._assess(question, resolved_context_signals or [], context)
        except Exception as error:  # degrade open: never block a real question
            logger.error("AnswerabilityGuard failed open: %s", error)
            return AnswerabilityResult(
                answerable=True, reason="guard_error_failed_open", signals=[]
            )

    def _assess(
        self,
        question: str,
        resolved_context_signals: list[str],
        context: "AnswerabilityInput | None" = None,
    ) -> AnswerabilityResult:
        # AI-INTELLIGENCE-018 (item 2/8): a reply that already resolved a
        # pending grounded-value clarification is answerable by construction
        # — evaluated BEFORE any raw-text domain-signal scan, never diverted
        # to out-of-scope classification.
        if context is not None and context.pending_clarification:
            return AnswerabilityResult(
                answerable=True, reason="pending_clarification_context", signals=[]
            )

        analysis = self._query_analyzer.analyze(question)
        context_signals = self._context_extractor.extract(question)
        folded_question = self._context_extractor.fold(question)

        signals: list[str] = []
        signals.extend(f"entity:{entity.entity_type}" for entity in analysis.entities)
        if context_signals.department:
            signals.append(f"department:{context_signals.department}")
        signals.extend(
            f"date:{date_range.expression}" for date_range in analysis.detected_dates
        )
        signals.extend(f"operation:{op}" for op in analysis.detected_operations)
        signals.extend(resolved_context_signals)

        unsafe_write_intent = self._unsafe_write_intent(folded_question)
        if unsafe_write_intent:
            signal = f"{_UNSAFE_WRITE_SIGNAL_PREFIX}{unsafe_write_intent}"
            logger.warning(
                "AnswerabilityGuard blocked unsafe write intent: operation=%s question=%r",
                unsafe_write_intent,
                question,
                extra={"answerable": False, "reason": "unsafe_write_intent", "signal": signal},
            )
            return AnswerabilityResult(
                answerable=False,
                reason="unsafe_write_intent",
                signals=[*signals, signal],
            )

        # Matched rewrite synonyms are intentionally NOT a domain signal: the
        # conversational rewrite group matches filler words ("bana", "acaba")
        # in completely unrelated questions. Domain rewrites (e.g. "kalp" ->
        # "kardiyoloji") surface as entities in the expanded query instead.
        has_resolved_domain_context = any(
            signal.startswith(("inherited_entity:", "inherited_metric:"))
            for signal in resolved_context_signals
        ) or (context is not None and context.has_resolved_domain_context())
        has_entity = (
            bool(analysis.entities)
            or bool(context_signals.department)
            or has_resolved_domain_context
        )
        has_dated_aggregate = bool(analysis.detected_dates) and bool(
            analysis.detected_operations
        )

        if has_resolved_domain_context:
            verdict, reason = True, "resolved_context_detected"
        elif has_entity:
            verdict, reason = True, "domain_entity_detected"
        elif has_dated_aggregate:
            verdict, reason = True, "dated_aggregate_detected"
        else:
            verdict, reason = False, "no_domain_signal"

        logger.info(
            "AnswerabilityGuard verdict: answerable=%s reason=%s signals=%s question=%r",
            verdict,
            reason,
            signals or "none",
            question,
            extra={
                "answerable": verdict,
                "reason": reason,
                "signals": signals,
                "question": question,
            },
        )
        return AnswerabilityResult(answerable=verdict, reason=reason, signals=signals)

    def _unsafe_write_intent(self, folded_question: str) -> str | None:
        for operation, pattern in _UNSAFE_WRITE_PATTERNS:
            if re.search(pattern, folded_question):
                return operation
        return None
