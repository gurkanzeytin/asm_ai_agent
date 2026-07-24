import logging
import re

from app.context import analytical_signals as _analytical_signals
from app.context import merge_policy as _merge_policy
from app.context.extractor import _MONTH_NAMES, ContextExtractor
from app.context.models import (
    ConversationContext,
    ExtractedSignals,
    ResolutionResult,
)

# Reuse the context extractor's length-preserving fold directly. Importing
# through ``app.semantics`` here eagerly initializes the semantic engine and,
# during application bootstrap, creates a planning -> context -> semantics ->
# services -> planning cycle before the graph can even start.
_fold = ContextExtractor().fold

logger = logging.getLogger(__name__)

# Deterministic confidence scores per resolution rule. Enrichment below the
# threshold is never applied — the question passes through untouched.
CONFIDENCE_PRONOUN = 0.95
CONFIDENCE_DATE_FOLLOWUP = 0.92
CONFIDENCE_DATE_INHERIT = 0.90
CONFIDENCE_DEPARTMENT_INHERIT = 0.85
CONFIDENCE_THRESHOLD = 0.80

# A bare month name ("haziran ayinda") carries no year of its own - only
# matched when the WHOLE expression is exactly this shape, never a relative
# span like "son 3 ayinda" ("last 3 months", which also contains "ayinda"
# but must stay relative to today, not get a fixed year prepended).
_BARE_MONTH_EXPRESSION = re.compile(rf"^(?:{_MONTH_NAMES})\s+ayinda$")
_YEAR_TOKEN = re.compile(r"\b(19|20)\d{2}\b")

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

# Constraint-editing verbs are inherently relational when a valid analytical
# plan exists in memory: they modify that plan rather than introduce a new
# standalone analysis.  Keep this narrow so a complete independent question
# that merely shares a dimension never inherits stale context.
_CONSTRAINT_EDIT_MARKERS = (
    "sadece",
    "sinirla",
    "sinirlandir",
    "filtrele",
    "ayir",
)

_OUTPUT_ACTION_FOLLOWUP_MARKERS = (
    "bunu calistir",
    "bunun grafig",
    "calistir",
    "tabloya cevir",
    "tablo olarak getir",
    "tablo yap",
    "tabloyu getir",
    "tablo getir",
    "grafik yap",
    "grafik ciz",
    "grafige cevir",
    "sql olarak ver",
    "sql ini ver",
    "sqlini ver",
    "sorgusunu ver",
)
_CONVERSATIONAL_CONTINUATION_MARKERS = ("o zaman", "peki")

_CLARIFICATION_MULTIPLE = (
    "Daha önce birden fazla konu konuşuldu. Hangisini kastettiğinizi belirtir misiniz?"
)
_CLARIFICATION_NONE = (
    "Bu ifadenin neyi kastettiğini anlayamadım. Sorunuzu biraz daha açık yazabilir misiniz?"
)
_CLARIFICATION_DATE_WITHOUT_CONTEXT = (
    "Bu tarih için hangi randevu analizini görmek istediğinizi belirtir misiniz?"
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

        # AI-INTELLIGENCE-017 (item 8): a reply to a pending GROUNDED VALUE
        # clarification ("hepsini", "ilkini", an explicit candidate) must be
        # evaluated FIRST — before the unsupported-status guard, before
        # pronoun/date/negation follow-up handling, and (structurally, since
        # this whole resolve() call happens before AgentState/the graph is
        # even built) before AnswerabilityGuard/out-of-scope routing. A
        # context-resolvable clarification reply must never fall through to
        # out-of-scope detection.
        if (
            context.pending_clarification
            and context.pending_clarification.field.startswith("value_filter:")
        ):
            pending_resolution = self._resolve_pending_value_clarification(
                question, context.pending_clarification
            )
            if pending_resolution is not None:
                resolved_question, filter_override = pending_resolution
                result.resolved_question = resolved_question
                result.filter_override = filter_override
                result.pending_clarification_resolved = True
                result.applied = True
                result.confidence = 1.0
                result.follow_up_signals.append("pending_value_clarification_resolved")
                result.inherited["previous_question"] = (
                    context.pending_clarification.original_question or ""
                )
                return self._finalize(result, question, context, signals)

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
        if signals.is_date_only_followup and self._has_inheritable_analysis(context):
            new_date = self._resolve_relative_year(
                signals.date_expression or "", context.date_expression
            )
            swapped = self._swap_date(context.last_question or "", new_date)
            result.resolved_question = self._anchor_bare_month_year(
                swapped, signals.date_expression or "", context.date_expression
            )
            result.inherited["previous_question"] = context.last_question
            result.inherited["entity_types"] = ",".join(context.entity_types)
            result.inherited["metrics"] = ",".join(context.metrics)
            result.inherited["date"] = new_date
            result.confidence = CONFIDENCE_DATE_FOLLOWUP
            result.applied = True
            result.follow_up_signals.append("date_only_followup")
            return self._finalize(result, question, context, signals)

        # A date fragment is conversationally incomplete, not out of domain.
        # Without a successful analytical anchor there is no safe subject or
        # metric to invent, so route it to the existing clarification outcome.
        if signals.is_date_only_followup:
            result.clarification_needed = True
            result.clarification_question = self._date_clarification(
                signals.date_expression
            )
            result.confidence = 0.0
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
        folded_question = self._extractor.fold(question)

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

        # AI-INTELLIGENCE-018 (item 1/3): a fully-worded ADDITIVE/REPLACEMENT
        # follow-up ("Bir de gerçekleşme oranını ekle.") has too many content
        # tokens to count as elliptical, but is still unambiguously a
        # follow-up — without this, `merge_metrics()`'s own additive-marker
        # branch (which fires regardless of `follow_up_detected`) could pull
        # in the inherited metric while every OTHER family (dimensions, date,
        # ...) stayed un-inherited because `follow_up_detected` never went True.
        if (
            not result.follow_up_signals
            and not current_signals.is_empty()
            and not context.is_empty()
            and _merge_policy.has_strong_followup_marker(folded_question)
        ):
            result.follow_up_signals.append("additive_or_replacement_followup")

        if (
            not result.follow_up_signals
            and not context.is_empty()
            and any(marker in folded_question for marker in _CONSTRAINT_EDIT_MARKERS)
        ):
            result.follow_up_signals.append("constraint_edit_followup")

        if (
            not result.follow_up_signals
            and not context.is_empty()
            and any(
                marker in folded_question
                for marker in _CONVERSATIONAL_CONTINUATION_MARKERS
            )
            and not current_signals.is_empty()
        ):
            result.follow_up_signals.append("conversational_continuation")

        if (
            not result.follow_up_signals
            and context.query_plan_snapshot is not None
            and any(
                marker in folded_question
                for marker in _OUTPUT_ACTION_FOLLOWUP_MARKERS
            )
            and current_signals.is_empty()
        ):
            result.follow_up_signals.append("output_action_followup")

        # "Top 10 departments" does not state what is being ranked.  When a
        # successful prior plan supplies that metric, it is a genuine ranking
        # continuation; a fully specified ranking question with its own metric
        # remains independent.
        if (
            not result.follow_up_signals
            and not context.is_empty()
            and current_signals.ranking is not None
            and not current_signals.metrics
            and bool(context.metrics)
        ):
            result.follow_up_signals.append("implicit_metric_ranking_followup")

        # AI-INTELLIGENCE-018 (item 1): a strong-marker additive/replacement
        # follow-up must become SELF-CONTAINED text, the same way the
        # existing date-only-followup branch replays `context.last_question`
        # with a swapped date — otherwise the planner (which independently
        # re-derives dimensions/metrics from raw `state.question` text, with
        # no access to `resolved_signals`) never sees the inherited branch
        # dimension or prior metric and can't build the right QueryPlan/SQL.
        # Deliberately scoped to ONLY the new strong-marker signal, not the
        # pre-existing generic `elliptical_analytical_followup` — that one
        # already fires for genuinely independent short questions that merely
        # happen to be short (e.g. a new department's own doctor listing),
        # where concatenating the prior question would corrupt the text.
        if (
            result.follow_up_signals
            and _merge_policy.has_strong_followup_marker(folded_question)
            and context.last_question
            and result.resolved_question == question
        ):
            result.resolved_question = (
                f"{context.last_question.rstrip('.')}. {question}".strip()
            )
            result.inherited["previous_question"] = context.last_question

        result.follow_up_detected = bool(result.follow_up_signals)
        result.follow_up_confidence = result.confidence

        inherited_signals = context.analytical_signals()
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

        # AI-INTELLIGENCE-018 (item 3): context_applied must reflect ACTUAL
        # semantic inheritance, not just the narrower pronoun/date-only/
        # negation branches that already set result.applied above. Any family
        # where the merged result differs from what the current turn's own
        # text alone would produce means a prior-turn value was retained,
        # extended, or replaced — genuine context use. An independent full
        # question never triggers this: merge_list_field/merge_metrics always
        # return the current turn's own (non-empty) values unchanged when the
        # current turn already states them explicitly, so resolved==current.
        if not result.applied and not context.is_empty():
            merged_uses_context = any(
                getattr(resolved_signals, family) != getattr(current_signals, family)
                for family in (
                    "dimensions",
                    "metrics",
                    "ranking",
                    "limit",
                    "time_grain",
                    "comparison_targets",
                    *_analytical_signals.FILTER_FAMILIES,
                )
            )
            if merged_uses_context:
                result.applied = True
                if "context_merge_applied" not in result.follow_up_signals:
                    result.follow_up_signals.append("context_merge_applied")

        result.context_applied = result.applied
        return result

    def _resolve_pending_value_clarification(
        self, question: str, pending
    ) -> tuple[str, dict[str, list[str]]] | None:
        """Resolves a reply to a pending grounded-value clarification (item 5/7).

        Returns (resolved_question, filter_override) where `resolved_question`
        replays the ORIGINAL analytical question (so the full pipeline resumes
        with the right dimension/metric/date intact) and `filter_override`
        short-circuits AI-INTELLIGENCE-016 extraction/resolution for the
        pending field this turn (AgentState.forced_filter_override) — an
        empty list means "clear this filter family" (an 'all' reply), a
        one-item list means the chosen grounded value. Returns None when the
        reply matches neither an 'all' phrase, an ordinal, nor a candidate —
        the turn then falls through to normal (non-pending) resolution.
        """
        from app.planning.value_resolver import (
            ALL_REPLY_PATTERN,
            ORDINAL_REPLY_INDEX,
            resolve_value,
        )

        bare_field = pending.field.split(":", 1)[-1]
        original_question = pending.original_question or question
        folded = _fold(question)

        if ALL_REPLY_PATTERN.search(folded):
            return original_question, {bare_field: []}

        for word, index in ORDINAL_REPLY_INDEX.items():
            if word in folded and 0 <= index < len(pending.candidate_values):
                return original_question, {bare_field: [pending.candidate_values[index]]}

        if pending.candidate_values:
            matched = resolve_value(bare_field, question, pending.candidate_values)
            if matched.grounded and matched.matched_value:
                return original_question, {bare_field: [matched.matched_value]}

        return None

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
        if any(marker in pronoun_text for marker in ("aynisi", "aynisini", "bunun")):
            if (
                context.metrics
                or context.dimensions
                or context.query_plan_snapshot is not None
            ):
                return _PLURAL_REFERENTS["Appointment"]

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

    def _has_inheritable_analysis(self, context: ConversationContext) -> bool:
        """A date-only continuation needs both a subject and analytical meaning."""
        return bool(
            context.last_question
            and context.entity_types
            and (context.metrics or context.analysis_type)
        )

    def _resolve_relative_year(
        self, expression: str, reference_expression: str | None
    ) -> str:
        """Resolve 'bir önceki yıl' against the active calendar-year anchor.

        Other relative expressions retain their normal QueryAnalyzer semantics
        (for example ``geçen yıl`` is relative to today's calendar year).
        """
        folded = self._extractor.fold(expression)
        if folded not in {"bir onceki yil", "onceki yil"}:
            return expression
        if reference_expression:
            match = _YEAR_TOKEN.search(reference_expression)
            if match:
                return f"{int(match.group()) - 1} yilinda"
        return "gecen yil"

    def _anchor_bare_month_year(
        self, swapped: str, expression: str, reference_expression: str | None
    ) -> str:
        """A bare month name ('haziran ayında') carries no year of its own.

        `_swap_date` excises whatever span `ContextExtractor` re-detects
        inside the PREVIOUS question's raw text and drops the new (year-less)
        expression in its place. Whether a year survives depends entirely on
        that previous span's shape: "2025 Mayıs ayında..." -> the extractor's
        span is just "mayıs ayında" (year excluded), so the leading "2025 "
        text is untouched by the replace and survives on its own (MT-011).
        But "2025 yılında..." -> the span IS "2025 yılında" (year included),
        so replacing it with a year-less month erases the year outright.

        Rather than predict which case applies (the two "date_expression"
        values in play - `ContextExtractor`'s own re-extraction inside
        `_swap_date` vs. `context.date_expression`, which may instead be
        sourced from the query plan's own date-detector - can disagree on
        whether a span includes its year), this checks the ACTUAL swapped
        output: only inject the conversation's anchor year when it is
        genuinely missing, never when the swap already preserved one
        (avoids a duplicated "2025 2025 haziran ayında...").
        """
        folded_expression = self._extractor.fold(expression)
        if not _BARE_MONTH_EXPRESSION.match(folded_expression):
            return swapped
        if _YEAR_TOKEN.search(swapped):
            return swapped
        if reference_expression:
            match = _YEAR_TOKEN.search(reference_expression)
            if match:
                return f"{match.group()} {swapped}"
        return swapped

    def _date_clarification(self, expression: str | None) -> str:
        match = re.search(r"\b((?:19|20)\d{2})\b", expression or "")
        if match:
            return (
                f"{match.group(1)} yılı için hangi randevu analizini görmek "
                "istediğinizi belirtir misiniz?"
            )
        return _CLARIFICATION_DATE_WITHOUT_CONTEXT

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
