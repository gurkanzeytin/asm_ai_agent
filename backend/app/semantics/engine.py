import logging
import time

from app.application_models.query_analysis import QueryAnalysis
from app.context.extractor import ContextExtractor
from app.semantics import catalog, ontology
from app.semantics.models import (
    SemanticAmbiguity,
    SemanticConstraint,
    SemanticFrame,
)
from app.services.query_analyzer import QueryAnalyzer

logger = logging.getLogger(__name__)

_HELP_MARKERS = (
    "yardim",
    "neler yapabilirsin",
    "nasil kullanilir",
    "ne sorabilirim",
    "help",
)

_NEGATION_MARKERS = ("olmayan", "bulunmayan", "almayan", "gelmeyen")

_DISTRIBUTION_MARKERS = ("dagilim", "dagilimi")

_VOLUME_RANKING_MARKERS = ("yogun", "en cok randevu", "en fazla randevu")

# Entities that carry an event date. A temporal filter on a non-event subject
# ("bugünkü doktorlar") semantically scopes their appointments, not the
# subject's own dates (e.g. a doctor's hire date).
_EVENT_ENTITIES = {
    "Appointment",
    "Prescription",
    "Hospitalization",
    "LaboratoryTest",
    "Invoice",
    "Diagnosis",
}


class SemanticUnderstandingEngine:
    """Deterministic semantic interpreter (REASONING-001).

    Turns a (context-resolved) question into a structured SemanticFrame using
    rule-based extraction, the domain ontology, and the existing NLU output.
    Never generates SQL, never calls an LLM, never guesses ambiguous meaning.
    """

    def __init__(
        self,
        query_analyzer: QueryAnalyzer | None = None,
        context_extractor: ContextExtractor | None = None,
    ) -> None:
        self._analyzer = query_analyzer or QueryAnalyzer()
        self._extractor = context_extractor or ContextExtractor()

    def understand(self, question: str) -> SemanticFrame:
        start = time.perf_counter()
        analysis = self._analyzer.analyze(question)
        folded = self._extractor.fold(question)
        # Medical synonyms ("kalp" -> "kardiyoloji") resolve in the expanded
        # query, so semantic signals are read from both surfaces.
        folded_expanded = self._extractor.fold(analysis.expanded_query)
        signals = self._extractor.extract(question)
        signals_expanded = self._extractor.extract(analysis.expanded_query)
        department = signals.department or signals_expanded.department
        search_text = f"{folded} {folded_expanded}"

        primary, fact = self._subjects(analysis, folded)
        goal = self._goal(search_text)
        constraints = self._constraints(analysis, department, folded)

        # A date filter on a non-event subject scopes that subject's
        # appointments ("bugünkü doktorlar" = doctors with appointments today).
        if (
            primary
            and any(c.type == "date" for c in constraints)
            and (fact or primary) not in _EVENT_ENTITIES
        ):
            fact = "Appointment"
        ambiguities = self._ambiguities(search_text)
        question_type = self._question_type(
            search_text, signals, analysis, department, goal, ambiguities
        )
        secondary = self._secondary_subjects(analysis, primary, fact, department, folded)
        subjects = {s for s in [primary, fact, *secondary] if s}
        relationships = ontology.relationships_between(subjects)
        requested_output = self._requested_output(goal, question_type, primary, search_text)
        confidence = self._confidence(
            primary, goal, constraints, ambiguities, signals, question_type
        )

        frame = SemanticFrame(
            question=question,
            normalized_question=analysis.final_query or analysis.normalized_query,
            goal=goal,
            primary_subject=primary,
            fact_subject=fact if fact != primary else None,
            secondary_subjects=secondary,
            requested_output=requested_output,
            constraints=constraints,
            question_type=question_type,
            relationships=relationships,
            ambiguities=ambiguities,
            confidence=confidence,
            duration_ms=(time.perf_counter() - start) * 1000,
        )
        self._log_frame(frame)
        return frame

    # ── Subjects ─────────────────────────────────────────────────────────

    def _subjects(
        self, analysis: QueryAnalysis, folded_question: str
    ) -> tuple[str | None, str | None]:
        """Primary = last-mentioned non-department entity (Turkish is verb-final);
        fact = first-mentioned. 'En yoğun X' implies Appointment volume."""
        positioned: list[tuple[int, str]] = []
        implied: list[str] = []
        for entity in analysis.entities:
            position = folded_question.find(entity.normalized_text)
            if position >= 0:
                positioned.append((position, entity.entity_type))
            else:
                # Surfaced only by synonym rewrites ("yoğun" -> randevu volume):
                # such entities are facts, never what the user asked to see.
                implied.append(entity.entity_type)
        positioned.sort()

        non_department = [name for _, name in positioned if name != "Department"]
        has_department = any(name == "Department" for _, name in positioned)

        if non_department:
            primary = non_department[-1]
            fact = non_department[0]
        elif has_department:
            primary = "Department"
            fact = next((name for name in implied if name != "Department"), "Department")
        elif implied:
            primary = fact = implied[0]
        else:
            return None, None

        if fact == primary and any(m in folded_question for m in _VOLUME_RANKING_MARKERS):
            if primary != "Appointment":
                fact = "Appointment"
        return primary, fact

    def _secondary_subjects(
        self,
        analysis: QueryAnalysis,
        primary: str | None,
        fact: str | None,
        department: str | None,
        folded_question: str,
    ) -> list[str]:
        subjects: list[str] = []
        for entity in analysis.entities:
            if entity.entity_type not in subjects and entity.entity_type != primary:
                subjects.append(entity.entity_type)
        if fact and fact != primary and fact not in subjects:
            subjects.append(fact)
        if department and "Department" not in subjects and primary != "Department":
            subjects.append("Department")
        return subjects

    # ── Goal / constraints / types ───────────────────────────────────────

    def _goal(self, search_text: str) -> str | None:
        for goal, markers in ontology.GOAL_MARKERS:
            if any(marker in search_text for marker in markers):
                return goal
        return None

    def _constraints(
        self,
        analysis: QueryAnalysis,
        department: str | None,
        folded_question: str,
    ) -> list[SemanticConstraint]:
        constraints: list[SemanticConstraint] = []
        for date_range in analysis.detected_dates:
            constraints.append(
                SemanticConstraint(
                    type="date",
                    value=date_range.expression,
                    detail=f"{date_range.start_date.isoformat()}..{date_range.end_date.isoformat()}",
                )
            )
        if department:
            constraints.append(SemanticConstraint(type="department", value=department))
        if any(marker in folded_question for marker in _NEGATION_MARKERS):
            constraints.append(
                SemanticConstraint(type="negation", value="exclude matching rows")
            )
        if analysis.detected_limit is not None:
            constraints.append(
                SemanticConstraint(type="limit", value=str(analysis.detected_limit))
            )
        if analysis.detected_order is not None:
            constraints.append(
                SemanticConstraint(type="order", value=analysis.detected_order)
            )
        return constraints

    def _ambiguities(self, search_text: str) -> list[SemanticAmbiguity]:
        return [
            SemanticAmbiguity(phrase=phrase, reason=reason)
            for phrase, reason in ontology.AMBIGUOUS_PHRASES.items()
            if phrase in search_text
        ]

    def _question_type(
        self,
        search_text: str,
        signals,
        analysis: QueryAnalysis,
        department: str | None,
        goal: str | None,
        ambiguities: list[SemanticAmbiguity],
    ) -> str:
        if any(marker in search_text for marker in _HELP_MARKERS):
            return "general_help"

        # Kept in sync with AnswerabilityGuard's actual out-of-scope gate
        # (app/services/answerability.py) - that guard is the real decision
        # point, but this classification is logged as "Question Type" right
        # alongside it, and a bare column mention ("kadın erkek oranı") with
        # no entity noun would otherwise log "out_of_scope" for a question
        # the pipeline goes on to answer, which is confusing when debugging
        # from these logs (2026-07-24).
        has_domain_signal = bool(
            analysis.entities
            or department
            or (analysis.detected_dates and analysis.detected_operations)
            or catalog.match_any_column_mention(search_text)
        )
        if not has_domain_signal and not signals.pronouns:
            return "out_of_scope"

        if signals.pronouns or signals.is_date_only_followup:
            return "follow_up"
        if any(marker in search_text for marker in _NEGATION_MARKERS):
            return "negative"
        if any(marker in search_text for marker in ontology.EXISTENCE_MARKERS):
            return "existence"
        if goal == "COMPARE":
            return "comparison"
        if goal == "TREND":
            return "trend"
        if any(marker in search_text for marker in _DISTRIBUTION_MARKERS):
            return "distribution"
        if goal == "RANK" or ambiguities:
            return "ranking"
        if goal in ("COUNT", "AGGREGATE"):
            return "aggregation"
        if goal in ("ANALYZE", "SUMMARIZE"):
            return "analytical"
        return "information_retrieval"

    def _requested_output(
        self,
        goal: str | None,
        question_type: str,
        primary: str | None,
        search_text: str,
    ) -> str | None:
        if question_type == "existence":
            return "boolean"
        if goal == "COUNT":
            return "count"
        if goal == "AGGREGATE":
            return "average" if "ortalama" in search_text else "total"
        if goal == "RANK":
            return "ranking"
        if goal == "TREND":
            return "time_series"
        if question_type in ("comparison", "distribution"):
            return "distribution"
        if goal in ("ANALYZE", "SUMMARIZE"):
            return "summary"
        if primary:
            return ontology.SUBJECT_OUTPUT_NAMES.get(primary, f"{primary.lower()}_list")
        return None

    # ── Confidence ───────────────────────────────────────────────────────

    def _confidence(
        self,
        primary: str | None,
        goal: str | None,
        constraints: list[SemanticConstraint],
        ambiguities: list[SemanticAmbiguity],
        signals,
        question_type: str,
    ) -> float:
        score = 0.5
        if primary:
            score += 0.2
        if goal:
            score += 0.15
        score += min(0.15, 0.05 * len(constraints))
        if ambiguities:
            score -= 0.35
        # Unresolved pronouns after context resolution mean the referent is unknown.
        if signals.pronouns and question_type == "follow_up":
            score -= 0.2
        if question_type == "out_of_scope":
            score = min(score, 0.4)
        return round(max(0.05, min(0.99, score)), 2)

    # ── Logging ──────────────────────────────────────────────────────────

    def _log_frame(self, frame: SemanticFrame) -> None:
        logger.info(
            "\n============ SEMANTIC UNDERSTANDING (REASONING-001) ============\n"
            f"Original Question : {frame.question}\n"
            f"Normalized        : {frame.normalized_question}\n"
            f"Goal              : {frame.goal or 'none'}\n"
            f"Primary Subject   : {frame.primary_subject or 'none'}"
            f"{f'  (fact: {frame.fact_subject})' if frame.fact_subject else ''}\n"
            f"Secondary Subjects: {frame.secondary_subjects or 'none'}\n"
            f"Constraints       : {[f'{c.type}={c.value}' for c in frame.constraints] or 'none'}\n"
            f"Question Type     : {frame.question_type}\n"
            f"Requested Output  : {frame.requested_output or 'none'}\n"
            f"Relationships     : {[r.render() for r in frame.relationships] or 'none'}\n"
            f"Ambiguities       : {[a.phrase for a in frame.ambiguities] or 'none'}\n"
            f"Confidence        : {frame.confidence:.2f}\n"
            f"Duration          : {frame.duration_ms:.2f} ms\n"
            "================================================================",
            extra={
                "semantic_frame": frame.model_dump(),
                "semantic_duration_ms": frame.duration_ms,
            },
        )
