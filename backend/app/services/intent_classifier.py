from functools import lru_cache
import json
import logging
from pathlib import Path
import re
from typing import Any, Dict, List, Set

from app.application_models.intent import IntentResult, IntentType
from app.core.config import settings
from app.services.interfaces import IIntentClassifier

logger = logging.getLogger(__name__)


class IntentClassifier(IIntentClassifier):
    """IntentClassifier implementation providing rule-based keyword classification.

    Decoupled caching logic via a private lru_cache method. Supports config hot-reloading
    during development mode (settings.DEBUG = True).
    """

    def __init__(self, config_file_path: Path | None = None):
        """Initializes the classifier with the path to the keywords configuration resource.

        Args:
            config_file_path: Optional custom path to intent_keywords.json.
        """
        if config_file_path is None:
            config_file_path = Path(__file__).parent.parent / "resources" / "intent_keywords.json"
        self._config_file_path = config_file_path
        self._cached_config = None

    def classify(self, question: str) -> IntentResult:
        """Analyzes a natural language question and returns the classified IntentResult.

        In development mode (settings.DEBUG = True), it loads config dynamically
        on every execution for hot-reloading. In production, it routes requests
        through the private lru_cache method.
        """
        normalized_q = question.strip().lower()

        # Resilient empty check
        if not normalized_q or not re.search(r"[a-zA-Z0-9]", normalized_q):
            return IntentResult(
                intent=IntentType.UNKNOWN,
                confidence=1.0,
                reason="empty_input",
                matched_keywords=[],
                metadata={},
            )

        if settings.DEBUG:
            config = self._load_config()
            result_dict = self._classify_logic(normalized_q, config)
        else:
            result_dict = self._classify_cached(normalized_q)

        return IntentResult(**result_dict)

    @lru_cache(maxsize=128)
    def _classify_cached(self, normalized_q: str) -> dict:
        """Private cached helper to execute query classification and return result dict."""
        config = self._load_config()
        return self._classify_logic(normalized_q, config)

    def _load_config(self) -> dict:
        """Reads configuration keywords JSON from disk with caching in production."""
        if not settings.DEBUG and self._cached_config is not None:
            return self._cached_config

        try:
            content = self._config_file_path.read_text(encoding="utf-8")
            config = json.loads(content)
            if not settings.DEBUG:
                self._cached_config = config
            return config
        except Exception as e:
            logger.error(f"Failed to load intent keywords configuration: {e}")
            return {}

    def _classify_logic(self, query: str, config: dict) -> dict:
        """Core rule-based classification algorithm mapping keywords to intent types."""
        # Split into alphanumeric word tokens
        query_words: Set[str] = set(re.findall(r"\b\w+\b", query))

        best_intent = IntentType.UNKNOWN
        best_confidence = 0.0
        best_matched_keywords: List[str] = []
        best_priority = 999
        matched_metadata: Dict[str, Any] = {}

        # Greet-keywords for check greeting logic (all matching query word greetings mapped)
        greetings = {"hello", "hi", "merhaba", "selam", "hey", "good morning", "gunaydin", "günaydın"}

        for intent_name, intent_meta in config.items():
            try:
                type_enum = IntentType(intent_name)
            except ValueError:
                continue

            keywords = intent_meta.get("keywords", [])
            base_confidence = intent_meta.get("base_confidence", 1.0)
            priority = intent_meta.get("priority", 10)

            # Match keywords respecting word boundaries
            matched: List[str] = []
            for kw in keywords:
                kw_lower = kw.lower()
                if " " in kw_lower:
                    # Multi-word match via regex word boundary
                    if re.search(r"\b" + re.escape(kw_lower) + r"\b", query):
                        matched.append(kw)
                else:
                    # Single word match via exact token lookups
                    if kw_lower in query_words:
                        matched.append(kw)

            if not matched:
                continue

            # Length-independent confidence scoring: full confidence at 1 keyword
            confidence = base_confidence * min(1.0, len(matched) / 1.0)

            # Keep the highest scoring intent (respecting priority for tie breakers)
            is_better = (
                confidence > best_confidence
                or (confidence == best_confidence and priority < best_priority)
            )

            if is_better:
                best_intent = type_enum
                best_confidence = confidence
                best_matched_keywords = matched
                best_priority = priority

        # Fallback to UNKNOWN if no matches found
        if best_intent == IntentType.UNKNOWN:
            return {
                "intent": IntentType.UNKNOWN,
                "confidence": 0.0,
                "reason": "no_keywords_matched",
                "matched_keywords": [],
                "metadata": {},
            }

        # Sub-intent evaluation for greetings
        if best_intent == IntentType.GENERAL_CHAT:
            matched_lower = {kw.lower() for kw in best_matched_keywords}
            if matched_lower.intersection(greetings):
                matched_metadata["sub_intent"] = "greeting"

        return {
            "intent": best_intent,
            "confidence": best_confidence,
            "reason": f"Matched keywords: {', '.join(best_matched_keywords)}",
            "matched_keywords": best_matched_keywords,
            "metadata": matched_metadata,
        }
