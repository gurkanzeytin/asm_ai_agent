import logging

from pydantic import BaseModel, Field

from app.context.extractor import ContextExtractor
from app.services.query_analyzer import QueryAnalyzer

logger = logging.getLogger(__name__)


class AnswerabilityResult(BaseModel):
    """Deterministic verdict on whether a question maps onto the schema domain."""

    answerable: bool = Field(..., description="True when the question can be attempted as SQL.")
    reason: str = Field(..., description="Short machine-readable reason for the verdict.")
    signals: list[str] = Field(
        default_factory=list, description="Domain signals detected in the question."
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

    def assess(self, question: str) -> AnswerabilityResult:
        try:
            return self._assess(question)
        except Exception as error:  # degrade open: never block a real question
            logger.error("AnswerabilityGuard failed open: %s", error)
            return AnswerabilityResult(
                answerable=True, reason="guard_error_failed_open", signals=[]
            )

    def _assess(self, question: str) -> AnswerabilityResult:
        analysis = self._query_analyzer.analyze(question)
        context_signals = self._context_extractor.extract(question)

        signals: list[str] = []
        signals.extend(f"entity:{entity.entity_type}" for entity in analysis.entities)
        if context_signals.department:
            signals.append(f"department:{context_signals.department}")
        signals.extend(
            f"date:{date_range.expression}" for date_range in analysis.detected_dates
        )
        signals.extend(f"operation:{op}" for op in analysis.detected_operations)

        # Matched rewrite synonyms are intentionally NOT a domain signal: the
        # conversational rewrite group matches filler words ("bana", "acaba")
        # in completely unrelated questions. Domain rewrites (e.g. "kalp" ->
        # "kardiyoloji") surface as entities in the expanded query instead.
        has_entity = bool(analysis.entities) or bool(context_signals.department)
        has_dated_aggregate = bool(analysis.detected_dates) and bool(
            analysis.detected_operations
        )

        if has_entity:
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
