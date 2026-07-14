"""Builds the insight-generation prompt from structured analytics only.

The LLM receives exclusively: the analytics object (scalar metrics, compact
rankings, insight fields), the deterministic business rules, and the
visualization decision. Never raw SQL, never database schema, never raw rows.
"""

import json
from typing import Any

from app.analytics.models import AnalyticsResult
from app.insights.models import InsightRule
from app.prompts.loader import prompt_loader
from app.prompts.renderer import prompt_renderer

_PROMPT_NAME = "insight_generation"
_MAX_RANKED_ENTRIES = 5


class InsightPromptBuilder:
    """Renders the insight prompt template with a sanitized analytics payload."""

    def build(self, analytics: AnalyticsResult, rules: list[InsightRule]) -> str:
        template = prompt_loader.get_prompt(_PROMPT_NAME)
        visualization = "NONE"
        if analytics.visualization:
            visualization = (
                f"{analytics.visualization.type.value} ({analytics.visualization.reason})"
            )
        return prompt_renderer.render(
            template,
            {
                "analytics_json": json.dumps(
                    self.analytics_payload(analytics), ensure_ascii=False, indent=2
                ),
                "rules": ", ".join(rule.value for rule in rules) or "NONE",
                "visualization": visualization,
            },
        )

    def analytics_payload(self, analytics: AnalyticsResult) -> dict[str, Any]:
        """Whitelisted view of the analytics object exposed to the LLM.

        Large structures are truncated to the top entries; nothing outside the
        analytics object is ever included.
        """
        scalar_metrics = {
            key: value
            for key, value in analytics.metrics.items()
            if not isinstance(value, (list, dict))
        }
        payload: dict[str, Any] = {
            "analytics_type": analytics.analytics_type,
            "data_shape": analytics.data_shape.value,
            "row_count": analytics.row_count,
            "metrics": scalar_metrics,
        }
        # Insight fields are copies of metric values under alternate names; sending
        # both duplicates prompt tokens. Keep only entries carrying new information.
        extra_insights = {
            key: value
            for key, value in analytics.insights.items()
            if value not in scalar_metrics.values()
        }
        if extra_insights:
            payload["insights"] = extra_insights
        top_n = analytics.metrics.get("top_n")
        if isinstance(top_n, list) and top_n:
            payload["top_categories"] = top_n[:_MAX_RANKED_ENTRIES]
        distribution = analytics.metrics.get("distribution")
        if isinstance(distribution, dict) and distribution:
            payload["distribution_percentages"] = distribution
        return payload
