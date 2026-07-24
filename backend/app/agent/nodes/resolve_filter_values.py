import logging
import time

from app.agent.nodes.node_interface import IAgentNode
from app.agent.state import AgentState
from app.application_models.query_analysis import AmbiguityResult
from app.planning.models import QueryPlan, ResolvedFilterPlan
from app.planning.value_resolver import (
    ValueResolver,
    build_clarification_headline,
    build_clarification_message,
    extract_candidate_phrases,
    extract_comparison_pair,
)

logger = logging.getLogger(__name__)


class ResolveFilterValuesNode(IAgentNode):
    """Grounds candidate filter phrases against real DB values (AI-INTELLIGENCE-016).

    Runs after planning, before SQL generation. Never invents a filter — an
    unresolved or ambiguous candidate degrades to a clarification request
    (state.ambiguity) instead of a guessed LIKE predicate. Organization-wide
    scope (plan.scope == "all") never resolves a branch-family filter.

    `state.forced_filter_override` (AI-INTELLIGENCE-017) short-circuits
    extraction/resolution for fields already resolved by a pending
    clarification reply ("hepsini", an explicit candidate, an ordinal) —
    those fields are applied directly, never re-extracted from text, so a
    replayed original question can never re-trigger the same clarification.
    """

    def __init__(self, resolver: ValueResolver | None = None) -> None:
        self.resolver = resolver or ValueResolver()

    async def execute(self, state: AgentState) -> AgentState:
        logger.info("ResolveFilterValuesNode execution started.")
        start_time = time.perf_counter()
        plan = state.query_plan
        ambiguity: AmbiguityResult | None = None

        try:
            if plan is not None:
                plan, ambiguity = await self._resolve_plan(plan, state.forced_filter_override)
        except Exception as error:
            logger.error(
                f"ResolveFilterValuesNode failed; continuing without grounded filters: {error}"
            )

        duration = (time.perf_counter() - start_time) * 1000
        logger.info("ResolveFilterValuesNode completed.")

        return state.model_copy(
            update={
                "query_plan": plan,
                "ambiguity": state.ambiguity or ambiguity,
                "current_node": "resolve_filter_values",
                "completed_nodes": state.completed_nodes + ["resolve_filter_values"],
                "duration_ms": state.duration_ms + duration,
                "node_timings": {**state.node_timings, "resolve_filter_values": duration},
            }
        )

    async def _resolve_plan(
        self, plan: QueryPlan, forced_overrides: dict[str, list[str]]
    ) -> tuple[QueryPlan, AmbiguityResult | None]:
        resolved_filters = dict(plan.resolved_filters)
        branch_filters = list(plan.branch_filters)
        ambiguity: AmbiguityResult | None = None

        # Pending-clarification overrides (a resolved "hepsini"/ordinal/explicit
        # reply) always win and are never re-extracted from text.
        for field_name, values in forced_overrides.items():
            resolved_filters[field_name] = ResolvedFilterPlan(
                field=field_name,
                values=list(values),
                source="pending_clarification",
                confidence=1.0,
                grounded=True,
                match_type="alias" if values else "cleared",
                clarification_required=False,
            )
            if field_name == "branch":
                branch_filters = list(values)

        candidates = extract_candidate_phrases(plan.question)
        if plan.scope == "all":
            # Organization-wide scope: never resolve a branch-family filter,
            # regardless of any capitalized-looking token near the phrase.
            candidates = {field: v for field, v in candidates.items() if field != "branch"}
        candidates = {field: v for field, v in candidates.items() if field not in forced_overrides}

        for field_name, phrases in candidates.items():
            phrase = phrases[0]
            resolved = await self.resolver.resolve(field_name, phrase)
            resolved_filters[field_name] = ResolvedFilterPlan(
                field=field_name,
                values=(
                    [resolved.matched_value] if resolved.grounded and resolved.matched_value else []
                ),
                source="grounded_value_resolver",
                confidence=resolved.confidence,
                grounded=resolved.grounded,
                match_type=resolved.match_type,
                original_text=resolved.original_text,
                clarification_required=resolved.clarification_required,
                clarification_message=(
                    build_clarification_message(resolved)
                    if resolved.clarification_required
                    else None
                ),
                alternatives=resolved.alternatives,
            )

            if field_name == "branch" and resolved.grounded and resolved.matched_value:
                branch_filters = [resolved.matched_value]

            if resolved.clarification_required and ambiguity is None:
                # `question` carries only the lead sentence — GenerateClarificationNode
                # renders `options` as its own bullet list; embedding the bullets
                # here too would render every option twice (item 4).
                ambiguity = AmbiguityResult(
                    matched_phrase=resolved.original_text,
                    question=build_clarification_headline(resolved),
                    options=resolved.alternatives or [],
                )

        # Explicit two-value comparison ("Kardiyoloji ile Psikiyatri'yi
        # karşılaştır"): both sides must ground on the SAME field; anything
        # less is silently ignored — a guessed pair must never trigger a
        # clarification or an invented filter.
        pair = extract_comparison_pair(plan.question)
        if pair is not None:
            for field_name in ("department", "branch"):
                if field_name in forced_overrides:
                    continue
                existing = resolved_filters.get(field_name)
                if existing is not None and existing.grounded and len(existing.values) >= 2:
                    continue
                left = await self.resolver.resolve(field_name, pair[0])
                right = await self.resolver.resolve(field_name, pair[1])
                if not (
                    left.grounded
                    and right.grounded
                    and left.matched_value
                    and right.matched_value
                ):
                    continue
                values = list(dict.fromkeys([left.matched_value, right.matched_value]))
                resolved_filters[field_name] = ResolvedFilterPlan(
                    field=field_name,
                    values=values,
                    source="grounded_value_resolver",
                    confidence=min(left.confidence, right.confidence),
                    grounded=True,
                    match_type="comparison_pair",
                    original_text=f"{pair[0]} / {pair[1]}",
                    clarification_required=False,
                )
                if field_name == "branch":
                    branch_filters = values
                # The question IS a two-entity comparison: align the plan so
                # the deterministic builder's entity-comparison path applies
                # (one conditional-count row, no GROUP BY over composite text).
                pair_plan_updates = {
                    "analysis_type": "comparison",
                    "dimensions": [],
                    "planned_dimensions": [],
                }
                plan = plan.model_copy(update=pair_plan_updates)
                break

        plan = plan.model_copy(
            update={"resolved_filters": resolved_filters, "branch_filters": branch_filters}
        )
        return plan, ambiguity
