"""Query Planning Engine (AG-022).

Deterministic planning layer between NLU and SQL generation. Organizes the
constraints the NLU already extracted (dates, entities, departments, rankings,
limits, aggregations) into a single QueryPlan that becomes the contract for
the SQL prompt, and validates the generated SQL against that contract.

No LLM calls, no embeddings, no vector search.
"""

from app.planning.compliance import PlanComplianceValidator
from app.planning.models import ComplianceResult, JoinStep, QueryPlan
from app.planning.planner import QueryPlanner, format_plan_for_prompt

__all__ = [
    "ComplianceResult",
    "JoinStep",
    "PlanComplianceValidator",
    "QueryPlan",
    "QueryPlanner",
    "format_plan_for_prompt",
]
