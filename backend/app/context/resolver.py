import logging
import re

from app.context.extractor import ContextExtractor
from app.context.models import (
    ConversationContext,
    ExtractedSignals,
    ResolutionResult,
)

logger = logging.getLogger(__name__)

# Deterministic confidence scores per resolution rule. Enrichment below the
# threshold is never applied — the question passes through untouched.
CONFIDENCE_PRONOUN = 0.95
CONFIDENCE_DATE_FOLLOWUP = 0.92
CONFIDENCE_DATE_INHERIT = 0.90
CONFIDENCE_DEPARTMENT_INHERIT = 0.85
CONFIDENCE_THRESHOLD = 0.80

_PLURAL_REFERENTS = {
    "Doctor": "doktorlar",
    "Patient": "hastalar",
    "Appointment": "randevular",
    "Prescription": "receteler",
    "Diagnosis": "tanilar",
    "Invoice": "faturalar",
}

_DEPARTMENT_SCOPED_REFERENTS = {
    "Doctor": "{department} doktorlari",
    "Patient": "{department} hastalari",
    "Appointment": "{department} randevulari",
    "Prescription": "{department} receteleri",
}

_CLARIFICATION_MULTIPLE = (
    "Daha önce birden fazla konu konuşuldu. Hangisini kastettiğinizi belirtir misiniz?"
)
_CLARIFICATION_NONE = (
    "Bu ifadenin neyi kastettiğini anlayamadım. Sorunuzu biraz daha açık yazabilir misiniz?"
)


class ContextResolver:
    """Rewrites follow-up questions into self-contained ones using session context.

    Purely deterministic: only appends or substitutes context the user
    established earlier in the same session, never invents information, and
    never overrides anything the user stated explicitly in the new question.
    """

    def __init__(self, extractor: ContextExtractor | None = None) -> None:
        self._extractor = extractor or ContextExtractor()

    def resolve(
        self, question: str, context: ConversationContext
    ) -> ResolutionResult:
        signals = self._extractor.extract(question)
        result = ResolutionResult(
            original_question=question, resolved_question=question
        )

        # Date-only follow-up ("Peki geçen ay?") re-runs the previous question
        # with the new temporal filter — comparison/trend continuation.
        if signals.is_date_only_followup and context.last_question:
            result.resolved_question = self._swap_date(
                context.last_question, signals.date_expression or ""
            )
            result.inherited["previous_question"] = context.last_question
            result.inherited["date"] = signals.date_expression or ""
            result.confidence = CONFIDENCE_DATE_FOLLOWUP
            result.applied = True
            return result

        resolved = question
        confidences: list[float] = []

        # 1. Pronoun resolution — requires a unique referent, else clarify.
        if signals.pronouns:
            referent = self._referent(signals, context)
            if referent is None:
                return self._clarification(result, context)
            resolved = self._substitute_pronouns(resolved, signals, referent)
            result.inherited["referent"] = referent
            confidences.append(CONFIDENCE_PRONOUN)

        # 2. Department inheritance — only when the question does not name a
        # department itself and is not asking about departments.
        department_from_pronoun = "referent" in result.inherited and (
            context.department or ""
        ) in result.inherited["referent"]
        if (
            context.department
            and not signals.department
            and not signals.asks_department
            and not department_from_pronoun
            and (signals.entity_types or signals.is_analytical)
        ):
            resolved = f"{context.department} {resolved}"
            result.inherited["department"] = context.department
            confidences.append(CONFIDENCE_DEPARTMENT_INHERIT)

        # 3. Date inheritance — only for analytical continuations, so plain
        # listing questions are never silently date-scoped.
        if (
            context.date_expression
            and not signals.date_expression
            and (signals.is_analytical or signals.pronouns)
        ):
            resolved = f"{context.date_expression} {resolved}"
            result.inherited["date"] = context.date_expression
            confidences.append(CONFIDENCE_DATE_INHERIT)

        if confidences:
            result.confidence = min(confidences)
            if result.confidence >= CONFIDENCE_THRESHOLD:
                result.resolved_question = resolved
                result.applied = True
            else:
                result.inherited = {}
                result.confidence = 1.0
        return result

    def _referent(
        self, signals: ExtractedSignals, context: ConversationContext
    ) -> str | None:
        """Determines the unique referent for a pronoun, or None when ambiguous."""
        pronoun_text = " ".join(signals.pronouns)

        # "o bölüm" / "aynı bölüm" — direct department reference.
        if "bolum" in pronoun_text:
            return context.department

        # "o doktor" / "o hasta" point at a specific individual from a previous
        # answer; individual names are not retained, so this is never resolved.
        if re.search(r"\b(o|ayni)\s+(doktor|hasta)", pronoun_text):
            return None

        entities = context.entity_types
        if context.department:
            scoped = [e for e in entities if e in _DEPARTMENT_SCOPED_REFERENTS]
            if len(scoped) == 1:
                return _DEPARTMENT_SCOPED_REFERENTS[scoped[0]].format(
                    department=context.department
                )
            if not entities:
                return context.department
        if len(entities) == 1 and entities[0] in _PLURAL_REFERENTS:
            return _PLURAL_REFERENTS[entities[0]]
        return None

    def _substitute_pronouns(
        self, question: str, signals: ExtractedSignals, referent: str
    ) -> str:
        """Replaces each detected pronoun span with the resolved referent phrase."""
        folded = self._extractor.fold(question)
        resolved = folded
        for pronoun in signals.pronouns:
            if pronoun.startswith(("bunlardan", "onlardan", "sunlardan")):
                replacement = f"{referent} arasindan"
            else:
                replacement = referent
            resolved = re.sub(
                rf"\b{re.escape(pronoun)}\b", replacement, resolved, count=1
            )
        return re.sub(r"\s+", " ", resolved).strip()

    def _swap_date(self, previous_question: str, new_date: str) -> str:
        """Re-issues the previous question with the new temporal filter."""
        previous_signals = self._extractor.extract(previous_question)
        folded_previous = self._extractor.fold(previous_question)
        if previous_signals.date_expression:
            swapped = folded_previous.replace(
                previous_signals.date_expression, new_date, 1
            )
        else:
            swapped = f"{new_date} {folded_previous}"
        return re.sub(r"\s+", " ", swapped).strip()

    def _clarification(
        self, result: ResolutionResult, context: ConversationContext
    ) -> ResolutionResult:
        options: list[str] = []
        if context.department:
            options.append(context.department)
        options.extend(
            _PLURAL_REFERENTS[e] for e in context.entity_types if e in _PLURAL_REFERENTS
        )
        result.clarification_needed = True
        result.clarification_question = (
            _CLARIFICATION_MULTIPLE if options else _CLARIFICATION_NONE
        )
        result.clarification_options = options
        result.confidence = 0.0
        return result
