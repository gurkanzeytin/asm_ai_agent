"""Observation Engine — Layer 4 of the response intelligence package.

Deterministic first: observations are always produced by rules and templates.
The LLM is used ONLY to reword the deterministic texts (when enabled), and its
output is rejected unless it preserves the observation count, every number and
category name, and contains no directive/recommendation language.
"""

import json
import logging
import re
import time

from app.analytics.models import AnalyticsResult
from app.insights.models import InsightConfidence, InsightResult
from app.insights.rules_engine import InsightRulesEngine
from app.intelligence import observation_rules, templates
from app.intelligence.models import Observation, ObservationResult
from app.llm.interfaces import ILLMProvider
from app.prompts.loader import prompt_loader
from app.prompts.renderer import prompt_renderer

logger = logging.getLogger(__name__)

_PROMPT_NAME = "observation_wording"
_NUMBER_PATTERN = re.compile(r"-?\d+(?:\.\d+)?")


class ObservationEngine:
    """Transforms analytics + insight metadata into evidence-based observations."""

    def __init__(
        self,
        llm_provider: ILLMProvider | None = None,
        rules_engine: InsightRulesEngine | None = None,
        use_llm_wording: bool = False,
    ) -> None:
        self.llm_provider = llm_provider
        self.rules_engine = rules_engine or InsightRulesEngine()
        self.use_llm_wording = use_llm_wording

    async def generate(
        self,
        analytics: AnalyticsResult,
        insights: InsightResult | None = None,
    ) -> ObservationResult:
        start_time = time.perf_counter()

        # Reuse insight rules/confidence when available; recompute otherwise.
        if insights is not None:
            rules = list(insights.rules)
            confidence = insights.confidence
        else:
            rules = self.rules_engine.evaluate(analytics)
            confidence = self.rules_engine.compute_confidence(analytics, rules)

        observations = observation_rules.build_observations(analytics, rules)
        if not observations:
            confidence = InsightConfidence.LOW

        llm_worded = False
        llm_latency_ms: float | None = None
        if (
            self.use_llm_wording
            and self.llm_provider is not None
            and observations
            and confidence != InsightConfidence.LOW
        ):
            reworded, llm_latency_ms = await self._reword_with_llm(observations)
            if reworded is not None:
                observations = reworded
                llm_worded = True

        duration_ms = (time.perf_counter() - start_time) * 1000
        result = ObservationResult(
            observations=observations,
            confidence=confidence,
            llm_worded=llm_worded,
            rule_count=len(rules),
            duration_ms=duration_ms,
            llm_latency_ms=llm_latency_ms,
        )
        self._log_result(result)
        return result

    # ── LLM rewording (optional, validated) ────────────────────────────────────

    async def _reword_with_llm(
        self, observations: list[Observation]
    ) -> tuple[list[Observation] | None, float | None]:
        """Asks the LLM to reword texts; returns None when validation fails."""
        try:
            template = prompt_loader.get_prompt(_PROMPT_NAME)
            prompt = prompt_renderer.render(
                template,
                {
                    "observations_json": json.dumps(
                        [obs.text for obs in observations], ensure_ascii=False, indent=2
                    ),
                    "count": len(observations),
                },
            )
            response = await self.llm_provider.generate(prompt, think=False)
            texts = self._parse_texts(response.content)
            if not self._valid_rewording(observations, texts):
                logger.warning("Observation LLM rewording rejected by validation.")
                return None, response.latency_ms
            reworded = [
                obs.model_copy(update={"text": text})
                for obs, text in zip(observations, texts, strict=True)
            ]
            return reworded, response.latency_ms
        except Exception as e:
            logger.warning(f"Observation LLM rewording failed; keeping templates: {e}")
            return None, None

    def _parse_texts(self, content: str) -> list[str]:
        cleaned = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL | re.IGNORECASE)
        fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", cleaned, re.DOTALL | re.IGNORECASE)
        if fenced:
            cleaned = fenced.group(1)
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start == -1 or end <= start:
            return []
        payload = json.loads(cleaned[start : end + 1])
        texts = payload.get("observations", [])
        return [str(text) for text in texts] if isinstance(texts, list) else []

    def _valid_rewording(self, observations: list[Observation], texts: list[str]) -> bool:
        """The LLM may only change wording — never facts, count, or intent."""
        if len(texts) != len(observations):
            return False
        for original, reworded in zip(observations, texts, strict=True):
            lowered = reworded.lower()
            if not reworded.strip():
                return False
            if any(pattern in lowered for pattern in templates.FORBIDDEN_WORDING_PATTERNS):
                return False
            # Every number in the original must survive; no new numbers may appear.
            if set(_NUMBER_PATTERN.findall(reworded)) != set(
                _NUMBER_PATTERN.findall(original.text)
            ):
                return False
            # Category / period names in the evidence must be preserved verbatim.
            for value in original.evidence.values():
                if isinstance(value, str) and value not in reworded:
                    return False
        return True

    # ── Observability ──────────────────────────────────────────────────────────

    def _log_result(self, result: ObservationResult) -> None:
        logger.info(
            "\n================ OBSERVATION ENGINE ================\n"
            f"Observations ({len(result.observations)})\n"
            + ("\n".join(f"- {obs.text}" for obs in result.observations) or "None")
            + "\n\n"
            f"Observation Rule Count: {result.rule_count}\n"
            f"Observation Confidence: {result.confidence.value}\n"
            f"LLM Worded: {'Yes' if result.llm_worded else 'No'}\n"
            f"LLM Duration: "
            f"{result.llm_latency_ms if result.llm_latency_ms is not None else '—'} ms\n\n"
            f"Observation Engine Time\n{result.duration_ms:.2f} ms\n"
            "====================================================",
            extra={
                "observation_count": len(result.observations),
                "observation_rule_count": result.rule_count,
                "observation_confidence": result.confidence.value,
                "observation_llm_worded": result.llm_worded,
                "observation_llm_latency_ms": result.llm_latency_ms,
                "observation_duration_ms": result.duration_ms,
            },
        )
