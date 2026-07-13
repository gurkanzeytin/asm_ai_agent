"""Analytics Intelligence Layer — deterministic post-execution analytics.

Public surface:
    AnalyticsEngine          — computes structured analytics from SQL results
    AnalyticsIntentDetector  — rule-based analytical intent detection
    VisualizationSelector    — rule-based visualization recommendation
    models                   — typed DTOs (AnalyticsResult, AnalyticsIntent, ...)
"""

from app.analytics.analytics_engine import AnalyticsEngine
from app.analytics.intent_detector import AnalyticsIntentDetector
from app.analytics.models import (
    AnalyticsIntent,
    AnalyticsResult,
    DataShape,
    VisualizationRecommendation,
    VisualizationType,
)
from app.analytics.visualization_selector import VisualizationSelector

__all__ = [
    "AnalyticsEngine",
    "AnalyticsIntentDetector",
    "AnalyticsIntent",
    "AnalyticsResult",
    "DataShape",
    "VisualizationRecommendation",
    "VisualizationType",
    "VisualizationSelector",
]
