"""Insight Intelligence Engine — turns deterministic analytics into insights.

Flow: rules engine (deterministic) → confidence (deterministic) → LLM narrative
(structured JSON, validated) → InsightResult. The LLM never calculates: it only
verbalizes the analytics payload it is given. On any LLM failure — or when
evidence is insufficient — the engine falls back to deterministic templates, so
a structurally valid, fully grounded insight is always produced.
"""

import json
import logging
import re
import time

from app.analytics.models import AnalyticsResult, DataShape
from app.insights import templates
from app.insights.models import InsightConfidence, InsightNarrative, InsightResult
from app.insights.prompt_builder import InsightPromptBuilder
from app.insights.rules_engine import InsightRulesEngine
from app.llm.interfaces import ILLMProvider

logger = logging.getLogger(__name__)

_THINK_BLOCK_PATTERN = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_CODE_FENCE_PATTERN = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)


class InsightEngine:
    """Generates executive-level structured insights grounded in analytics."""

    def __init__(
        self,
        llm_provider: ILLMProvider | None = None,
        rules_engine: InsightRulesEngine | None = None,
        prompt_builder: InsightPromptBuilder | None = None,
    ) -> None:
        self.llm_provider = llm_provider
        self.rules_engine = rules_engine or InsightRulesEngine()
        self.prompt_builder = prompt_builder or InsightPromptBuilder()

    async def generate(self, analytics: AnalyticsResult) -> InsightResult:
        start_time = time.perf_counter()

        rules = self.rules_engine.evaluate(analytics)
        confidence = self.rules_engine.compute_confidence(analytics, rules)

        narrative: InsightNarrative
        llm_generated = False
        provider_name = "deterministic"
        model_name = "templates"
        llm_latency_ms: float | None = None
        prompt_tokens: int | None = None
        completion_tokens: int | None = None

        if confidence == InsightConfidence.LOW:
            # Part 6: no LLM call without analytical evidence.
            narrative = templates.build_insufficient_evidence_narrative(analytics)
        elif analytics.data_shape in (
            DataShape.SINGLE_VALUE,
            DataShape.SINGLE_ROW,
            DataShape.EMPTY,
        ):
            # A single value or row needs no executive narrative; deterministic
            # templates say everything an LLM could without the latency.
            narrative = templates.build_deterministic_narrative(analytics, rules)
        elif self.llm_provider is None:
            narrative = templates.build_deterministic_narrative(analytics, rules)
        else:
            try:
                prompt = self.prompt_builder.build(analytics, rules)
                response = await self.llm_provider.generate(prompt, think=False)
                narrative = self._parse_narrative(response.content)
                llm_generated = True
                model_name = response.model
                provider_name = type(self.llm_provider).__name__
                llm_latency_ms = response.latency_ms
                prompt_tokens = response.prompt_tokens
                completion_tokens = response.completion_tokens
                if not narrative.title:
                    narrative = narrative.model_copy(
                        update={"title": templates.build_title(analytics)}
                    )
            except Exception as e:
                logger.warning(
                    f"Insight LLM narrative failed; using deterministic templates: {e}"
                )
                narrative = templates.build_deterministic_narrative(analytics, rules)

        duration_ms = (time.perf_counter() - start_time) * 1000
        result = InsightResult(
            title=narrative.title,
            summary=narrative.summary,
            highlights=narrative.highlights,
            observations=narrative.observations,
            considerations=narrative.considerations,
            rules=rules,
            confidence=confidence,
            llm_generated=llm_generated,
            provider=provider_name,
            model=model_name,
            duration_ms=duration_ms,
            llm_latency_ms=llm_latency_ms,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
        self._log_result(result)
        return result

    def _parse_narrative(self, content: str) -> InsightNarrative:
        """Extracts and validates the LLM's JSON output against the narrative schema."""
        cleaned = _THINK_BLOCK_PATTERN.sub("", content).strip()
        fenced = _CODE_FENCE_PATTERN.search(cleaned)
        if fenced:
            cleaned = fenced.group(1).strip()
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start == -1 or end <= start:
            raise ValueError("LLM response contains no JSON object.")
        payload = json.loads(cleaned[start : end + 1])
        if not isinstance(payload, dict):
            raise ValueError("LLM response JSON is not an object.")
        # Confidence is computed, never accepted from the LLM (Part 5).
        payload.pop("confidence", None)
        return InsightNarrative(**{
            key: payload.get(key)
            for key in ("title", "summary", "highlights", "observations", "considerations")
            if payload.get(key) is not None
        })

    def _log_result(self, result: InsightResult) -> None:
        logger.info(
            "\n================ INSIGHT ENGINE ================\n"
            f"Title\n{result.title}\n\n"
            f"Confidence (computed)\n{result.confidence.value}\n\n"
            f"Rules ({len(result.rules)})\n"
            f"{', '.join(rule.value for rule in result.rules) or 'None'}\n\n"
            f"LLM Generated: {'Yes' if result.llm_generated else 'No (deterministic templates)'}\n"
            f"LLM Duration: "
            f"{result.llm_latency_ms if result.llm_latency_ms is not None else '—'} ms\n"
            f"Prompt Tokens: {result.prompt_tokens if result.prompt_tokens is not None else '—'}\n"
            f"Completion Tokens: "
            f"{result.completion_tokens if result.completion_tokens is not None else '—'}\n\n"
            f"Insight Generation Time\n{result.duration_ms:.2f} ms\n"
            "================================================",
            extra={
                "insight_title": result.title,
                "insight_confidence": result.confidence.value,
                "insight_rules": [rule.value for rule in result.rules],
                "insight_rule_count": len(result.rules),
                "insight_llm_generated": result.llm_generated,
                "insight_llm_latency_ms": result.llm_latency_ms,
                "insight_prompt_tokens": result.prompt_tokens,
                "insight_completion_tokens": result.completion_tokens,
                "insight_duration_ms": result.duration_ms,
            },
        )
