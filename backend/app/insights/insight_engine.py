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
from dataclasses import dataclass

from app.analytics.models import AnalyticsResult, DataShape
from app.insights import templates
from app.insights.models import InsightConfidence, InsightNarrative, InsightResult, InsightRule
from app.insights.output_validation import validate_and_repair
from app.insights.prompt_builder import InsightPromptBuilder
from app.insights.routing import InsightGenerationMode, InsightRouter, RoutingDecision
from app.insights.rules_engine import InsightRulesEngine
from app.llm.interfaces import ILLMProvider

logger = logging.getLogger(__name__)

_THINK_BLOCK_PATTERN = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_CODE_FENCE_PATTERN = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)


@dataclass
class _LLMAttemptOutcome:
    """Internal result of one routed LLM attempt chain (primary + at most one fallback)."""

    narrative: InsightNarrative | None
    llm_generated: bool
    provider_name: str
    model_name: str
    llm_latency_ms: float | None
    prompt_tokens: int | None
    completion_tokens: int | None
    finish_reason: str | None
    fallback_used: bool
    fallback_reason: str | None
    attempts: int
    requested_provider: str
    requested_model: str | None
    thinking_enabled: bool
    remote_attempted: bool
    fallback_provider: str | None
    provider_duration_ms: float | None
    fallback_duration_ms: float | None


class InsightEngine:
    """Generates executive-level structured insights grounded in analytics.

    Two operating modes:

    - Legacy single-provider mode (``llm_provider`` only, no router/local/remote
      providers configured): behavior is byte-identical to the pre-routing
      engine — every call still resolves through ``self.llm_provider`` with the
      original shape/confidence branching. This is what every existing caller
      that constructs ``InsightEngine(llm_provider=...)`` gets, unchanged.
    - Routing-aware mode (``local_llm_provider``/``remote_llm_provider``/``router``
      supplied): a small explicit router (``app.insights.routing.InsightRouter``)
      decides deterministic vs. local (Ollama/qwen3) vs. remote (NVIDIA/DeepSeek)
      per call from structured analytics signals, with bounded one-shot fallback.
    """

    def __init__(
        self,
        llm_provider: ILLMProvider | None = None,
        rules_engine: InsightRulesEngine | None = None,
        prompt_builder: InsightPromptBuilder | None = None,
        local_llm_provider: ILLMProvider | None = None,
        remote_llm_provider: ILLMProvider | None = None,
        router: InsightRouter | None = None,
    ) -> None:
        self.llm_provider = llm_provider
        self.rules_engine = rules_engine or InsightRulesEngine()
        self.prompt_builder = prompt_builder or InsightPromptBuilder()
        self.local_llm_provider = local_llm_provider
        self.remote_llm_provider = remote_llm_provider
        self.router = router

    def _routing_active(self) -> bool:
        return (
            self.local_llm_provider is not None
            or self.remote_llm_provider is not None
            or self.router is not None
        )

    async def generate(self, analytics: AnalyticsResult) -> InsightResult:
        start_time = time.perf_counter()

        rules = self.rules_engine.evaluate(analytics)
        confidence = self.rules_engine.compute_confidence(analytics, rules)

        if self._routing_active():
            result = await self._generate_routed(analytics, rules, confidence, start_time)
        else:
            result = await self._generate_legacy(analytics, rules, confidence, start_time)
        self._log_result(result)
        return result

    async def _generate_legacy(
        self,
        analytics: AnalyticsResult,
        rules: list,
        confidence: InsightConfidence,
        start_time: float,
    ) -> InsightResult:
        """Unmodified pre-routing behavior — preserved exactly for backward compatibility."""
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
                narrative, verdict = validate_and_repair(narrative, analytics, rules)
                self._log_narrative_validation(verdict)
            except Exception as e:
                logger.warning(f"Insight LLM narrative failed; using deterministic templates: {e}")
                narrative = templates.build_deterministic_narrative(analytics, rules)

        duration_ms = (time.perf_counter() - start_time) * 1000
        return InsightResult(
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

    async def _generate_routed(
        self,
        analytics: AnalyticsResult,
        rules: list,
        confidence: InsightConfidence,
        start_time: float,
    ) -> InsightResult:
        from app.core.config import settings

        router = self.router or InsightRouter(
            enabled=settings.INSIGHT_ROUTING_ENABLED,
            deterministic_enabled=settings.INSIGHT_DETERMINISTIC_ENABLED,
            remote_complexity_threshold=settings.INSIGHT_REMOTE_COMPLEXITY_THRESHOLD,
            remote_available=self.remote_llm_provider is not None,
            deterministic_max_rows=settings.INSIGHT_DETERMINISTIC_MAX_ROWS,
        )

        # Insufficient-evidence narratives never need the prompt (and never
        # need policy screening — no LLM-bound payload exists at all).
        if confidence == InsightConfidence.LOW:
            decision = RoutingDecision(
                deterministic_candidate=True,
                deterministic_reason="insufficient_evidence",
                mode=InsightGenerationMode.DETERMINISTIC,
                selected_provider="deterministic",
                selected_model="templates",
                routing_reason="insufficient_evidence",
            )
        else:
            prompt = self.prompt_builder.build(analytics, rules)
            decision = router.decide(analytics, rules, confidence, remote_texts=(prompt,))

        self._log_routing_decision(decision)

        if decision.mode == InsightGenerationMode.DETERMINISTIC:
            narrative = (
                templates.build_insufficient_evidence_narrative(analytics)
                if confidence == InsightConfidence.LOW
                else templates.build_deterministic_narrative(analytics, rules)
            )
            duration_ms = (time.perf_counter() - start_time) * 1000
            return InsightResult(
                title=narrative.title,
                summary=narrative.summary,
                highlights=narrative.highlights,
                observations=narrative.observations,
                considerations=narrative.considerations,
                rules=rules,
                confidence=confidence,
                llm_generated=False,
                provider="deterministic",
                model="templates",
                duration_ms=duration_ms,
                llm_latency_ms=0.0,
                attempts=0,
                fallback_used=False,
                routing_mode=decision.mode.value,
                routing_reason=decision.routing_reason,
                remote_data_policy=decision.remote_policy_status,
                requested_provider="deterministic",
                requested_model="templates",
                resolved_provider="deterministic",
                resolved_model="templates",
                complexity_score=decision.complexity_score,
                thinking_enabled=False,
                remote_attempted=False,
                provider_duration_ms=0.0,
                total_llm_duration_ms=0.0,
            )

        outcome = await self._attempt_with_fallback(decision, analytics, rules)
        if outcome.narrative is None:
            # Both the selected provider and its one fallback failed: sufficient
            # analytics evidence already established above, so degrade to the
            # same grounded deterministic narrative rather than failing the request.
            narrative = templates.build_deterministic_narrative(analytics, rules)
            outcome.provider_name = "deterministic"
            outcome.model_name = "templates"
            outcome.llm_latency_ms = 0.0
        else:
            narrative = outcome.narrative

        duration_ms = (time.perf_counter() - start_time) * 1000
        return InsightResult(
            title=narrative.title,
            summary=narrative.summary,
            highlights=narrative.highlights,
            observations=narrative.observations,
            considerations=narrative.considerations,
            rules=rules,
            confidence=confidence,
            llm_generated=outcome.llm_generated,
            provider=outcome.provider_name,
            model=outcome.model_name,
            duration_ms=duration_ms,
            llm_latency_ms=outcome.llm_latency_ms,
            prompt_tokens=outcome.prompt_tokens,
            completion_tokens=outcome.completion_tokens,
            finish_reason=outcome.finish_reason,
            attempts=outcome.attempts,
            routing_mode=decision.mode.value,
            routing_reason=decision.routing_reason,
            fallback_used=outcome.fallback_used,
            fallback_reason=outcome.fallback_reason,
            remote_data_policy=decision.remote_policy_status,
            requested_provider=outcome.requested_provider,
            requested_model=outcome.requested_model,
            resolved_provider=outcome.provider_name,
            resolved_model=outcome.model_name,
            complexity_score=decision.complexity_score,
            thinking_enabled=outcome.thinking_enabled,
            remote_attempted=outcome.remote_attempted,
            fallback_provider=outcome.fallback_provider,
            provider_duration_ms=outcome.provider_duration_ms,
            fallback_duration_ms=outcome.fallback_duration_ms,
            total_llm_duration_ms=(
                (outcome.provider_duration_ms or 0.0) + (outcome.fallback_duration_ms or 0.0)
                if outcome.provider_duration_ms is not None
                else None
            ),
        )

    def _log_routing_decision(self, decision: RoutingDecision) -> None:
        """Logs the routing diagnostic. Never includes prompts, rows, or PII —
        only structural signals (shape/rule/count-derived booleans and labels)."""
        logger.info(
            "Insight routing decision.",
            extra={
                "deterministic_candidate": decision.deterministic_candidate,
                "deterministic_reason": decision.deterministic_reason,
                "complexity_score": decision.complexity_score,
                "complexity_factors": decision.complexity_factors,
                "blocking_factors": decision.blocking_factors,
                "final_mode": decision.final_mode.value,
                "final_provider": decision.final_provider,
                "final_model": decision.final_model,
                "remote_policy_status": decision.remote_policy_status,
            },
        )

    async def _attempt_with_fallback(
        self,
        decision: RoutingDecision,
        analytics: AnalyticsResult,
        rules: list,
    ) -> _LLMAttemptOutcome:
        """Executes the routed provider with at most one bounded, one-directional
        fallback (remote -> local). Never retries the same provider, never bounces
        back from local to remote, and never loops.
        """
        prompt = self.prompt_builder.build(analytics, rules)

        requested_provider = decision.selected_provider
        remote_attempted = (
            decision.mode == InsightGenerationMode.REMOTE_LLM
            and self.remote_llm_provider is not None
        )

        primary_provider = (
            self.remote_llm_provider
            if decision.mode == InsightGenerationMode.REMOTE_LLM
            else self.local_llm_provider
        )
        primary_label = decision.selected_provider
        pre_fallback_used = False
        pre_fallback_reason = None
        if primary_provider is None:
            # Router selected a leg that isn't actually wired (e.g. remote chosen
            # but no NVIDIA provider configured) — go straight to local.
            primary_provider = self.local_llm_provider
            primary_label = "ollama"
            pre_fallback_used = True
            pre_fallback_reason = "selected_provider_unavailable"

        requested_model = getattr(primary_provider, "model", None) if primary_provider else None

        if primary_provider is None:
            return _LLMAttemptOutcome(
                narrative=None,
                llm_generated=False,
                provider_name="deterministic",
                model_name="templates",
                llm_latency_ms=None,
                prompt_tokens=None,
                completion_tokens=None,
                finish_reason=None,
                fallback_used=True,
                fallback_reason="no_provider_available",
                attempts=0,
                requested_provider=requested_provider,
                requested_model=None,
                thinking_enabled=False,
                remote_attempted=False,
                fallback_provider=None,
                provider_duration_ms=None,
                fallback_duration_ms=None,
            )

        attempt_start = time.perf_counter()
        try:
            narrative, response = await self._call_provider(
                primary_provider, prompt, analytics, rules
            )
            provider_duration_ms = (time.perf_counter() - attempt_start) * 1000
            return _LLMAttemptOutcome(
                narrative=narrative,
                llm_generated=True,
                provider_name=primary_label,
                model_name=response.model,
                llm_latency_ms=response.latency_ms,
                prompt_tokens=response.prompt_tokens,
                completion_tokens=response.completion_tokens,
                finish_reason=response.finish_reason,
                fallback_used=pre_fallback_used,
                fallback_reason=pre_fallback_reason,
                attempts=1,
                requested_provider=requested_provider,
                requested_model=requested_model,
                thinking_enabled=False,
                remote_attempted=remote_attempted,
                fallback_provider=(primary_label if pre_fallback_used else None),
                provider_duration_ms=provider_duration_ms,
                fallback_duration_ms=None,
            )
        except Exception as primary_error:
            provider_duration_ms = (time.perf_counter() - attempt_start) * 1000
            if primary_label == "ollama" or self.local_llm_provider is None:
                # Already local, or no local leg to fall back to.
                logger.warning(
                    f"Insight LLM ({primary_label}) failed with no further fallback "
                    f"available: {type(primary_error).__name__}: {primary_error}"
                )
                return _LLMAttemptOutcome(
                    narrative=None,
                    llm_generated=False,
                    provider_name="deterministic",
                    model_name="templates",
                    llm_latency_ms=None,
                    prompt_tokens=None,
                    completion_tokens=None,
                    finish_reason=None,
                    fallback_used=True,
                    fallback_reason=f"{primary_label}_{type(primary_error).__name__}",
                    attempts=1,
                    requested_provider=requested_provider,
                    requested_model=requested_model,
                    thinking_enabled=False,
                    remote_attempted=remote_attempted,
                    fallback_provider=None,
                    provider_duration_ms=provider_duration_ms,
                    fallback_duration_ms=None,
                )

            # Bounded, one-directional fallback: remote -> local only. Never
            # tries another remote model (DeepSeek/GPT-OSS/GLM) — the router
            # already selected the single remote leg for this request.
            logger.warning(
                f"Remote insight LLM failed ({type(primary_error).__name__}); "
                "falling back once to the local provider."
            )
            fallback_start = time.perf_counter()
            try:
                narrative, response = await self._call_provider(
                    self.local_llm_provider, prompt, analytics, rules
                )
                fallback_duration_ms = (time.perf_counter() - fallback_start) * 1000
                return _LLMAttemptOutcome(
                    narrative=narrative,
                    llm_generated=True,
                    provider_name="ollama",
                    model_name=response.model,
                    llm_latency_ms=response.latency_ms,
                    prompt_tokens=response.prompt_tokens,
                    completion_tokens=response.completion_tokens,
                    finish_reason=response.finish_reason,
                    fallback_used=True,
                    fallback_reason=f"remote_{type(primary_error).__name__}",
                    attempts=2,
                    requested_provider=requested_provider,
                    requested_model=requested_model,
                    thinking_enabled=False,
                    remote_attempted=remote_attempted,
                    fallback_provider="ollama",
                    provider_duration_ms=provider_duration_ms,
                    fallback_duration_ms=fallback_duration_ms,
                )
            except Exception as local_error:
                fallback_duration_ms = (time.perf_counter() - fallback_start) * 1000
                logger.warning(
                    f"Local insight LLM fallback also failed: "
                    f"{type(local_error).__name__}: {local_error}"
                )
                return _LLMAttemptOutcome(
                    narrative=None,
                    llm_generated=False,
                    provider_name="deterministic",
                    model_name="templates",
                    llm_latency_ms=None,
                    prompt_tokens=None,
                    completion_tokens=None,
                    finish_reason=None,
                    fallback_used=True,
                    fallback_reason=(
                        f"remote_{type(primary_error).__name__}_"
                        f"then_local_{type(local_error).__name__}"
                    ),
                    attempts=2,
                    requested_provider=requested_provider,
                    requested_model=requested_model,
                    thinking_enabled=False,
                    remote_attempted=remote_attempted,
                    fallback_provider="ollama",
                    provider_duration_ms=provider_duration_ms,
                    fallback_duration_ms=fallback_duration_ms,
                )

    async def _call_provider(
        self,
        provider: ILLMProvider,
        prompt: str,
        analytics: AnalyticsResult,
        rules: list[InsightRule],
    ):
        response = await provider.generate(prompt, think=False)
        narrative = self._parse_narrative(response.content)
        if not narrative.title:
            narrative = narrative.model_copy(update={"title": templates.build_title(analytics)})
        narrative, verdict = validate_and_repair(narrative, analytics, rules)
        self._log_narrative_validation(verdict)
        return narrative, response

    def _log_narrative_validation(self, verdict) -> None:
        if verdict.title_replaced or verdict.narrative_replaced or not verdict.language_ok:
            logger.info(
                "Insight narrative validation repaired output.",
                extra={
                    "language_ok": verdict.language_ok,
                    "title_replaced": verdict.title_replaced,
                    "narrative_replaced": verdict.narrative_replaced,
                    "missing_limitations_added": verdict.missing_limitations_added,
                    "causal_certainty_dropped": verdict.causal_certainty_dropped,
                    "reason": verdict.reason,
                },
            )

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
        return InsightNarrative(
            **{
                key: payload.get(key)
                for key in ("title", "summary", "highlights", "observations", "considerations")
                if payload.get(key) is not None
            }
        )

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
                "routing_mode": result.routing_mode,
                "routing_reason": result.routing_reason,
                "complexity_score": result.complexity_score,
                "resolved_provider": result.resolved_provider,
                "fallback_used": result.fallback_used,
                "fallback_reason": result.fallback_reason,
            },
        )
