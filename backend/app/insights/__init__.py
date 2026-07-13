"""Insight Intelligence Engine — explains deterministic analytics.

Public surface:
    InsightEngine        — orchestrates rules → confidence → LLM narrative
    InsightRulesEngine   — deterministic business rules and confidence
    InsightPromptBuilder — analytics-only prompt construction
    models               — typed DTOs (InsightResult, InsightRule, ...)
"""

from app.insights.insight_engine import InsightEngine
from app.insights.models import (
    InsightConfidence,
    InsightNarrative,
    InsightResult,
    InsightRule,
)
from app.insights.prompt_builder import InsightPromptBuilder
from app.insights.rules_engine import InsightRulesEngine

__all__ = [
    "InsightEngine",
    "InsightConfidence",
    "InsightNarrative",
    "InsightResult",
    "InsightRule",
    "InsightPromptBuilder",
    "InsightRulesEngine",
]
