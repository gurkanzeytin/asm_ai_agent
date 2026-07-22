import logging
import re

from app.context import analytical_signals as _analytical_signals
from app.context import merge_policy as _merge_policy
from app.context.extractor import ContextExtractor
from app.context.models import (
    ConversationContext,
    ExtractedSignals,
    ResolutionResult,
)
from app.semantics.view_mapping import fold as _fold

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

# AI-INTELLIGENCE-011: opposite-direction follow-ups ("Peki artmamış olanlar?")
# re-run the previous analytical question with the predicate inverted. Pairs are
# kept in diacritic form because last_question preserves the user's spelling.
_INVERSION_PAIRS: list[tuple[str, str]] = [
    ("artmış", "artmamış"),
    ("yükselmiş", "yükselmemiş"),
    ("düşmüş", "düşmemiş"),
    ("gelmiş", "gelmemiş"),
    ("gerçekleşmiş", "gerçekleşmemiş"),
    ("patlamış", "patlamamış"),
    ("en çok", "en az"),
]
CONFIDENCE_NEGATION_FOLLOWUP = 0.93

_CLARIFICATION_MULTIPLE = (
    "Daha önce birden fazla konu konuşuldu. Hangisini kastettiğinizi belirtir misiniz?"
)
_CLARIFICATION_NONE = (
    "Bu ifadenin neyi kastettiğini anlayamadım. Sorunuzu biraz daha açık yazabilir misiniz?"
)

# The single status term documented as verified NOT to exist in the data
# (app/resources/view_semantics.json RandevuDurumu description: "'İptal'
# değeri veride bulunmaz") — narrow and specific, not a general "any
# unmatched status-like word" guess. Mentioning it must trigger clarification
# rather than silently producing a filter that can never match any row.
_UNSUPPORTED_STATUS_TERM = "iptal"
_CANONICAL_STATUS_VALUES = [
    "Beklemede",
    "Gelmedi",
    "Gerçekleşti",
    "Giriş Yapılmış",
    "İşlem Sürmekte",
]
_CLARIFICATION_UNSUPPORTED_STATUS = (
    "'İptal' durumu bu sistemde kayıtlı değil. Doğrulanmış randevu durumları: "
    + ", ".join(_CANONICAL_STATUS_VALUES)
    + ". Hangisini kastettiniz?"
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
        result.overridden_fields = self._overridden_fields(signals, context)

        # Unsupported status (Part 9): never silently ground an unsupported
        # value or produce a filter that can never match a row — surface a
        # clarification instead, offering the real canonical status vocabulary.
        if _UNSUPPORTED_STATUS_TERM in _fold(question):
            result.clarification_needed = True
            result.clarification_question = _CLARIFICATION_UNSUPPORTED_STATUS
            result.clarification_options = list(_CANONICAL_STATUS_VALUES)
            result.confidence = 0.0
            return self._finalize(result, question, context, signals)

        # Pending clarification resolution (Part 7): a bounded pending field
        # (e.g. an ambiguous ranking metric from 'En iyi doktorları göster.')
        # is resolved deterministically when the current turn's raw text
        # matches a real catalog metric — never guessed, never LLM-derived.
        # The resolved metric flows into `resolved_signals` through the same
        # from_raw_text() catalog match below; this only marks the diagnostic
        # flag and adds an explicit follow-up signal.
        if (
            context.pending_clarification
            and context.pending_clarification.field == "ranking_metric"
            and self._resolves_pending_ranking_metric(question)
        ):
            result.pending_clarification_resolved = True
            result.follow_up_signals.append("pending_clarification_resolved")

        # Negation follow-up ("Peki artmamış olanlar?") re-runs the previous
        # analytical question with the comparison predicate inverted, keeping
        # metric, dimension, and periods intact.
        negated = self._negation_followup(question, context)
        if negated is not None:
            result.resolved_question = negated
            result.inherited["previous_question"] = context.last_question or ""
            result.inherited["inverted_predicate"] = "true"
            result.confidence = CONFIDENCE_NEGATION_FOLLOWUP
            result.applied = True
            result.follow_up_signals.append("negation_followup")
            return self._finalize(result, question, context, signals)

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
            result.follow_up_signals.append("date_only_followup")
            return self._finalize(result, question, context, signals)

        resolved = question
        confidences: list[float] = []

        # 1. Pronoun resolution — requires a unique referent, else clarify.
        # A pronoun is always a strong follow-up signal even when the referent
        # turns out to be ambiguous (clarification path) — the question really
        # does depend on prior context, it just can't be resolved safely.
        if signals.pronouns:
            result.follow_up_signals.append("pronoun_reference")
            referent = self._referent(signals, context)
            if referent is None:
                return self._finalize(
                    self._clarification(result, context), question, context, signals
                )
            resolved = self._substitute_pronouns(resolved, signals, referent)
            result.inherited["referent"] = referent
            confidences.append(CONFIDENCE_PRONOUN)

        # 2. Department inheritance — only when the question does not name a
        # department itself, is not asking about departments, AND is short
        # enough to plausibly be incomplete on its own (elliptical). A full,
        # independent question that merely contains an entity or analytics
        # word (e.g. "Kadın hastaların yaş dağılımını göster") must NOT
        # silently inherit a stale department from an earlier turn.
        department_from_pronoun = "referent" in result.inherited and (
            context.department or ""
        ) in result.inherited["referent"]
        if (
            context.department
            and not signals.department
            and not signals.asks_department
            and not department_from_pronoun
            and signals.is_elliptical
            and (signals.entity_types or signals.is_analytical)
        ):
            resolved = f"{context.department} {resolved}"
            result.inherited["department"] = context.department
            confidences.append(CONFIDENCE_DEPARTMENT_INHERIT)
            result.follow_up_signals.append("elliptical_department_inherit")

        # 3. Date inheritance — only for short, analytical continuations, so
        # plain listing questions and complete independent questions are
        # never silently date-scoped by a stale filter.
        if (
            context.date_expression
            and not signals.date_expression
            and (signals.pronouns or (signals.is_analytical and signals.is_elliptical))
        ):
            resolved = f"{context.date_expression} {resolved}"
            result.inherited["date"] = context.date_expression
            confidences.append(CONFIDENCE_DATE_INHERIT)
            if not signals.pronouns:
                result.follow_up_signals.append("elliptical_date_inherit")

        if confidences:
            result.confidence = min(confidences)
            if result.confidence >= CONFIDENCE_THRESHOLD:
                result.resolved_question = resolved
                result.applied = True
            else:
                result.inherited = {}
                result.follow_up_signals = []
                result.confidence = 1.0
        return self._finalize(result, question, context, signals)

    def _overridden_fields(
        self, signals: ExtractedSignals, context: ConversationContext
    ) -> list[str]:
        """Detects which field types the current turn stated explicitly, displacing
        a *different* value already held in session context — explicit-value
        precedence made observable. Never mutates context; read-only comparison."""
        overridden: list[str] = []
        if (
            signals.date_expression
            and context.date_expression
            and signals.date_expression != context.date_expression
        ):
            overridden.append("date")
        if (
            signals.department
            and context.department
            and signals.department != context.department
        ):
            overridden.append("department")
        if (
            signals.analysis_type
            and context.analysis_type
            and signals.analysis_type != context.analysis_type
        ):
            overridden.append("analysis_type")
        if (
            signals.entity_types
            and context.entity_types
            and set(signals.entity_types) != set(context.entity_types)
        ):
            overridden.append("entity_types")
        return overridden

    def _finalize(
        self,
        result: ResolutionResult,
        question: str,
        context: ConversationContext,
        signals: ExtractedSignals,
    ) -> ResolutionResult:
        """Syncs the follow-up-specific field aliases and computes the typed
        analytical-signal merge (Parts 4-8) — the single choke point every
        `resolve()` return path passes through, so the merge always reflects
        the final follow-up verdict."""
        current_signals = _analytical_signals.from_raw_text(question, department=signals.department)

        # Elliptical dimension/analytical follow-up ("Doktor bazında?",
        # "Şubelere göre?") — short, has no date/pronoun, and "bazında"/"göre"
        # alone are not analytical cues, so none of the existing pronoun/
        # date-only/negation/elliptical-department-or-date signals fire for
        # it. It is still a genuine follow-up whenever it resolves to real
        # analytical content (a dimension/metric/ranking/etc.) AND there is
        # actual inheritable context to continue — never merely because the
        # session has history (Part 6: no inheritance from bare membership).
        if (
            not result.follow_up_signals
            and signals.is_elliptical
            and not current_signals.is_empty()
            and not context.is_empty()
        ):
            result.follow_up_signals.append("elliptical_analytical_followup")

        result.follow_up_detected = bool(result.follow_up_signals)
        result.follow_up_confidence = result.confidence
        result.context_applied = result.applied

        inherited_signals = context.analytical_signals()
        folded_question = self._extractor.fold(question)
        resolved_signals, explicit_fields, removed_fields = (
            _merge_policy.merge_analytical_signals(
                current=current_signals,
                inherited=inherited_signals,
                follow_up_detected=result.follow_up_detected,
                folded_question=folded_question,
            )
        )
        result.resolved_signals = resolved_signals
        result.explicit_fields = explicit_fields
        result.removed_fields = removed_fields
        return result

    def _resolves_pending_ranking_metric(self, question: str) -> bool:
        from app.semantics import catalog

        folded = self._extractor.fold(question)
        return bool(catalog.match_metrics(folded))

    def _negation_followup(
        self, question: str, context: ConversationContext
    ) -> str | None:
        """Rewrites a short opposite-direction follow-up onto the last question."""
        if not context.last_question:
            return None
        folded_question = _fold(question)
        if len(folded_question.split()) > 5:
            return None
        folded_last = _fold(context.last_question)
        for positive, negative in _INVERSION_PAIRS:
            for source, target in ((positive, negative), (negative, positive)):
                if (
                    _fold(target) in folded_question
                    and _fold(source) in folded_last
                    and _fold(target) not in folded_last
                ):
                    pattern = re.compile(re.escape(source), re.IGNORECASE)
                    return pattern.sub(target, context.last_question, count=1)
        return None

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
