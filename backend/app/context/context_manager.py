import logging
from typing import TYPE_CHECKING

from app.context import analytical_signals as _analytical_signals
from app.context import merge_policy as _merge_policy
from app.context.extractor import ContextExtractor
from app.context.models import ConversationTurn, PendingClarification, ResolutionResult
from app.context.resolver import ContextResolver
from app.context.session_store import DEFAULT_SESSION_ID, SessionStore

if TYPE_CHECKING:
    from app.planning.models import QueryPlan

logger = logging.getLogger(__name__)


class ContextManager:
    """Facade of the conversational context engine.

    resolve() runs before the NLU pipeline and rewrites follow-up questions
    into self-contained ones; update() runs after the workflow and records
    the latest explicit filters. Both degrade to no-ops on any internal
    failure — the context engine must never break the main pipeline.
    """

    def __init__(
        self,
        store: SessionStore | None = None,
        extractor: ContextExtractor | None = None,
        resolver: ContextResolver | None = None,
    ) -> None:
        self._store = store or SessionStore()
        self._extractor = extractor or ContextExtractor()
        self._resolver = resolver or ContextResolver(self._extractor)

    def resolve(
        self, question: str, session_id: str = DEFAULT_SESSION_ID
    ) -> ResolutionResult:
        """Resolves a question against the session context. Never raises."""
        try:
            context = self._store.get(session_id)
            result = self._resolver.resolve(question, context)
            if result.follow_up_detected and context.query_plan_snapshot is not None:
                result.retained_query_plan_snapshot = dict(context.query_plan_snapshot)
        except Exception as error:  # degrade, never break the pipeline
            logger.error("ContextManager.resolve failed: %s", error)
            return ResolutionResult(
                original_question=question, resolved_question=question
            )

        logger.info(
            "Conversational context resolution: session=%s applied=%s "
            "clarification=%s confidence=%.2f\n"
            "  Original : %s\n"
            "  Resolved : %s\n"
            "  Inherited: %s",
            session_id,
            result.applied,
            result.clarification_needed,
            result.confidence,
            result.original_question,
            result.resolved_question,
            result.inherited or "none",
            extra={
                "session_id": session_id,
                "original_question": result.original_question,
                "resolved_question": result.resolved_question,
                "inherited_filters": result.inherited,
                "confidence": result.confidence,
                "clarification_required": result.clarification_needed,
            },
        )
        return result

    def update(
        self,
        resolution: ResolutionResult,
        session_id: str = DEFAULT_SESSION_ID,
        canonical_analysis_type: str | None = None,
        query_plan: "QueryPlan | None" = None,
    ) -> bool:
        """Records the interaction and refreshes the session filters. Never raises.

        Args:
            resolution: Outcome of `resolve()` for this turn.
            session_id: Session key to update.
            canonical_analysis_type: The workflow's actual, post-execution analysis
                type (see app.context.analysis_type.resolve_canonical_analysis_type),
                derived from the real AnalyticsResult/outcome — never from the
                pre-execution keyword guess in `signals.analysis_type`. Always
                takes precedence when supplied, since it reflects what the
                pipeline actually did, not what the raw question text merely
                looked like before execution.
            query_plan: The workflow's actual, post-planning QueryPlan, when
                available. Authoritative source for the typed analytical
                signals (dimensions/metrics/ranking/limit/time_grain/filters)
                — preferred over `resolution.resolved_signals` (which was
                necessarily computed from the resolve()-time raw-text
                fallback, before planning ran). The same merge policy is
                re-applied here against the pre-mutation context snapshot and
                the same follow-up verdict already decided at resolve() time,
                so precedence still holds even though this runs after it.
        """
        try:
            if resolution.clarification_needed:
                return False

            signals = self._extractor.extract(resolution.resolved_question)

            def _mutate(context) -> None:
                # Latest explicit statement replaces the previous filter of the
                # same type (context expiration rule). Untouched types persist.
                if query_plan is not None and query_plan.date_filters:
                    # Exact successful-plan date context is authoritative. In
                    # particular, never reduce "2026 Ocak" to a month-only raw
                    # text match and silently lose its year.
                    context.date_expression = query_plan.date_filters[0].expression
                elif signals.date_expression:
                    context.date_expression = signals.date_expression
                if signals.department:
                    context.department = signals.department
                if signals.entity_types:
                    context.entity_types = signals.entity_types
                if canonical_analysis_type:
                    context.analysis_type = canonical_analysis_type
                elif signals.analysis_type:
                    context.analysis_type = signals.analysis_type

                # Only content-bearing questions become the continuation anchor;
                # greetings/small talk must not hijack "Peki geçen ay?" follow-ups.
                if signals.entity_types or signals.is_analytical or signals.asks_department:
                    context.last_question = resolution.resolved_question

                # Typed analytical signals (Parts 4-8). Prefer the authoritative
                # QueryPlan-derived signals over the resolve()-time raw-text
                # guess when the real plan is available.
                if query_plan is not None:
                    current_analytical = _analytical_signals.from_query_plan(query_plan)
                    inherited_snapshot = context.analytical_signals()
                    folded_question = self._extractor.fold(resolution.resolved_question)
                    merged, _explicit, _removed = _merge_policy.merge_analytical_signals(
                        current=current_analytical,
                        inherited=inherited_snapshot,
                        follow_up_detected=resolution.follow_up_detected,
                        folded_question=folded_question,
                    )
                    # AI-INTELLIGENCE-016: an organization-wide scope phrase
                    # ("tüm şubeler", "tüm aile sağlığı merkezleri", ...) must
                    # clear an inherited branch filter even on a follow-up —
                    # the generic merge rule would otherwise re-inherit it
                    # (current is legitimately empty, not "no signal").
                    if query_plan.scope == "all" and merged.branch_filters:
                        merged = merged.model_copy(update={"branch_filters": []})
                else:
                    merged = resolution.resolved_signals

                context.dimensions = merged.dimensions
                context.metrics = merged.metrics
                context.ranking = merged.ranking
                context.limit = merged.limit
                context.time_grain = merged.time_grain
                context.comparison_targets = merged.comparison_targets
                context.status_filters = merged.status_filters
                context.department_filters = merged.department_filters
                context.branch_filters = merged.branch_filters
                context.doctor_filters = merged.doctor_filters
                context.service_filters = merged.service_filters
                context.category_filters = merged.category_filters
                context.source_filters = merged.source_filters

                if query_plan is not None:
                    context.query_plan_snapshot = query_plan.model_dump(mode="json")

                # A successful new turn always supersedes any stale pending
                # clarification, whether or not it was the answer to it.
                context.pending_clarification = None

                context.turns.append(
                    ConversationTurn(
                        question=resolution.original_question,
                        resolved_question=resolution.resolved_question,
                        signals=signals,
                    )
                )

            # Atomic read-modify-write: closes the race where two concurrent
            # requests on the same session each read stale state and one
            # update silently overwrites the other (see SessionStore.update).
            context = self._store.update(session_id, _mutate)

            logger.info(
                "Conversational context updated: session=%s date=%s department=%s "
                "entities=%s analysis=%s dimensions=%s metrics=%s status_filters=%s "
                "ranking=%s limit=%s time_grain=%s turns=%d",
                session_id,
                context.date_expression,
                context.department,
                context.entity_types,
                context.analysis_type,
                context.dimensions,
                context.metrics,
                context.status_filters,
                context.ranking,
                context.limit,
                context.time_grain,
                len(context.turns),
                extra={
                    "session_id": session_id,
                    "context_date": context.date_expression,
                    "context_department": context.department,
                    "context_entities": context.entity_types,
                    "context_analysis_type": context.analysis_type,
                    "context_dimensions": context.dimensions,
                    "context_metrics": context.metrics,
                    "context_status_filters": context.status_filters,
                    "context_ranking": context.ranking,
                    "context_limit": context.limit,
                    "context_time_grain": context.time_grain,
                },
            )
            return True
        except Exception as error:  # degrade, never break the pipeline
            logger.error("ContextManager.update failed: %s", error)
            return False

    def set_pending_clarification(
        self,
        session_id: str,
        field: str,
        reason: str,
        choices: list[str] | None = None,
        original_question: str | None = None,
        candidate_values: list[str] | None = None,
        original_analysis_type: str | None = None,
        original_metrics: list[str] | None = None,
        original_dimensions: list[str] | None = None,
        original_date_expression: str | None = None,
        original_filters: dict[str, list[str]] | None = None,
    ) -> None:
        """Sets a bounded pending clarification (Part 7) without touching any
        other field in the session's context — never overwrites the last
        valid analytical state with incomplete clarification data. Never raises.

        The optional `original_*`/`candidate_values` arguments (AI-INTELLIGENCE-017)
        snapshot the analytical request that raised a grounded-value clarification
        (see app.planning.value_resolver), so a reply ("hepsini", "ilkini", an
        explicit value) can resume planning without losing the original intent.
        """
        try:

            def _mutate(context) -> None:
                context.pending_clarification = PendingClarification(
                    field=field,
                    reason=reason,
                    choices=choices or [],
                    original_question=original_question,
                    candidate_values=candidate_values or [],
                    original_analysis_type=original_analysis_type,
                    original_metrics=original_metrics or [],
                    original_dimensions=original_dimensions or [],
                    original_date_expression=original_date_expression,
                    original_filters=original_filters or {},
                )

            self._store.update(session_id, _mutate)
            logger.info(
                "Pending clarification set: session=%s field=%s",
                session_id,
                field,
                extra={"session_id": session_id, "pending_field": field},
            )
        except Exception as error:  # degrade, never break the pipeline
            logger.error("ContextManager.set_pending_clarification failed: %s", error)

    def clear(self, session_id: str = DEFAULT_SESSION_ID) -> bool:
        """Clears the session context (new-conversation reset).

        Idempotent: clearing an unknown/already-cleared session is a safe no-op.
        Returns True when a live session actually existed and was removed.
        """
        return self._store.clear(session_id)

    def turn_count(self, session_id: str) -> int:
        """Returns the current retained turn count for a session (diagnostics)."""
        return self._store.turn_count(session_id)

    def is_expired_or_absent(self, session_id: str) -> bool:
        """True when the session has no live (non-expired) context (diagnostics)."""
        return self._store.is_expired_or_absent(session_id)

    def get_pending_clarification(self, session_id: str) -> PendingClarification | None:
        """Returns the session's current pending clarification state, if any (diagnostics)."""
        return self._store.get(session_id).pending_clarification

    def entity_types(self, session_id: str) -> list[str]:
        """Read-only typed entity snapshot used for request diagnostics."""
        return list(self._store.get(session_id).entity_types)

    def extract_date(self, question: str) -> str | None:
        """Expose the canonical context extractor without duplicating date rules."""
        return self._extractor.extract(question).date_expression
