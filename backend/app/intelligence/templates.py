"""Deterministic observation wordings.

Neutral, evidence-based phrasing only. Never operational recommendations:
wordings use "may deserve attention" / "is noteworthy" style language and never
"must" / "should" / "needs". These templates are the source of truth for facts;
the LLM may only reword them.
"""

# Rule-based wordings keyed by insight rule name. {placeholders} are filled
# from analytics metrics.
RULE_WORDINGS: dict[str, str] = {
    "HIGH_GROWTH": "Sustained growth detected: values increased by {growth_rate}%.",
    "MODERATE_GROWTH": "Growth has remained positive over the period ({growth_rate}%).",
    "DECLINING": "A downward change of {growth_rate}% is visible over the period.",
    "POSITIVE_TREND": "The overall trend is upward.",
    "NEGATIVE_TREND": "A downward trend is visible.",
    "STABLE_TREND": "Values have remained stable over the period.",
    "DOMINANT_CATEGORY": (
        "One category clearly dominates: '{top_category}' holds the largest share."
    ),
    "BALANCED_DISTRIBUTION": "No significant imbalance detected across categories.",
    "OUTLIER_DETECTED": (
        "'{top_category}' is significantly above the average and is noteworthy."
    ),
    "SINGLE_METRIC": "The result is a single metric value of {total}.",
    "INSUFFICIENT_EVIDENCE": "The result set does not contain enough data for observations.",
}

# Metric-derived wordings (fire independently of rules when evidence exists).
TOP_CATEGORY_WORDING = "'{top_category}' has the highest volume in this result."
LARGEST_CHANGE_WORDING = "The largest change occurred in {largest_change}."
SIGNIFICANT_SPREAD_WORDING = (
    "The difference between the highest ({highest_value}) and lowest ({lowest_value}) "
    "values is significant and may deserve attention."
)

# Modal/imperative words that must never appear in observation wording.
FORBIDDEN_WORDING_PATTERNS = (
    "must",
    "should",
    "needs to",
    "have to",
    "recommend",
    "advise",
)
