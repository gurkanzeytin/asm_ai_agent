"""Response Intelligence package — Layer 4 (Observations).

Transforms analytics and insight metadata into noteworthy, evidence-based
observations. No SQL, no analytics calculations, no recommendations.
"""

from app.intelligence.models import Observation, ObservationCategory, ObservationResult
from app.intelligence.observation_engine import ObservationEngine

__all__ = [
    "Observation",
    "ObservationCategory",
    "ObservationResult",
    "ObservationEngine",
]
