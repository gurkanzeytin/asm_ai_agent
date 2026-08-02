"""Bounded LLM fallback for schema-domain answerability decisions."""

from __future__ import annotations

import json
import logging

from app.application_models.schema_reasoning import SchemaReasoningDecision
from app.llm.interfaces import ILLMProvider
from app.prompts.loader import prompt_loader
from app.prompts.renderer import prompt_renderer
from app.semantics import catalog
from app.semantics.schema_knowledge import load_schema_knowledge

logger = logging.getLogger(__name__)

SchemaAnswerabilityDecision = SchemaReasoningDecision


class SchemaAnswerabilityService:
    """Asks the configured provider only after deterministic coverage says unknown.

    The provider cannot expand the database boundary: an affirmative answer is
    accepted only when it cites real catalog columns and optional real metric ids.
    Malformed output, hallucinated identifiers, low confidence, or provider failure
    degrades to ``None`` so the caller keeps the existing safe out-of-scope verdict.
    """

    def __init__(self, llm_provider: ILLMProvider) -> None:
        self._llm_provider = llm_provider

    async def assess(self, question: str) -> SchemaAnswerabilityDecision | None:
        try:
            response = await self._llm_provider.generate(
                self._render_prompt(question),
                think=False,
                options={"num_predict": 220},
            )
            decision = self._parse(response.content)
            if decision is None:
                return None

            column_catalog = catalog.load_column_catalog()
            metric_catalog = catalog.load_metric_catalog()
            column_ids = column_catalog.column_names()
            metric_by_id = metric_catalog.by_id()
            metric_ids = set(metric_by_id)
            unknown_columns = set(decision.supporting_columns) - column_ids
            unknown_metrics = set(decision.supporting_metrics) - metric_ids
            if unknown_columns or unknown_metrics:
                logger.warning(
                    "Schema reasoning cited unknown catalog identifiers; rejecting decision.",
                    extra={
                        "unknown_columns": sorted(unknown_columns),
                        "unknown_metrics": sorted(unknown_metrics),
                    },
                )
                return None
            column_by_id = {spec.column: spec for spec in column_catalog.columns}
            invalid_dimensions = [
                column
                for column in decision.dimension_columns
                if column not in column_by_id or not column_by_id[column].groupable
            ]
            if invalid_dimensions:
                logger.warning(
                    "Schema reasoning cited non-groupable dimensions; rejecting decision.",
                    extra={"invalid_dimensions": invalid_dimensions},
                )
                return None
            pattern_ids = {
                pattern.id for pattern in catalog.load_pattern_catalog().patterns
            }
            if decision.analysis_type and decision.analysis_type not in pattern_ids:
                logger.warning(
                    "Schema reasoning cited unknown analysis type; rejecting decision.",
                    extra={"analysis_type": decision.analysis_type},
                )
                return None
            if decision.time_column:
                time_spec = column_by_id.get(decision.time_column)
                if time_spec is None or time_spec.semantic_type not in {"date", "datetime"}:
                    logger.warning(
                        "Schema reasoning cited a non-temporal time column; rejecting decision.",
                        extra={"time_column": decision.time_column},
                    )
                    return None
            if decision.time_scope not in {None, "all_time"} and not decision.time_column:
                logger.warning(
                    "Schema reasoning supplied a time scope without a time column; "
                    "rejecting decision."
                )
                return None
            dimension_required = {
                "distribution",
                "ranking",
                "top_n",
                "bottom_n",
                "cross_analysis",
            }
            if (
                decision.analysis_type in dimension_required
                and not decision.dimension_columns
            ):
                logger.warning(
                    "Schema reasoning analysis requires a dimension; rejecting decision.",
                    extra={"analysis_type": decision.analysis_type},
                )
                return None
            if (
                decision.analysis_type == "cross_analysis"
                and len(decision.dimension_columns) != 2
            ):
                logger.warning(
                    "Schema reasoning cross analysis requires two dimensions; rejecting decision."
                )
                return None
            if decision.status == "answerable" and not decision.supporting_columns:
                logger.warning("Schema reasoning answerable decision had no supporting column.")
                return None
            required_columns = list(decision.supporting_columns)
            for metric_id in decision.supporting_metrics:
                compatible = set(metric_by_id[metric_id].compatible_dimensions)
                if compatible and not set(decision.dimension_columns).issubset(compatible):
                    logger.warning(
                        "Schema reasoning selected an incompatible metric/dimension pair; "
                        "rejecting decision.",
                        extra={
                            "metric": metric_id,
                            "dimensions": decision.dimension_columns,
                        },
                    )
                    return None
                for column in metric_by_id[metric_id].required_columns:
                    if column not in required_columns:
                        required_columns.append(column)
            for column in [*decision.dimension_columns, decision.time_column]:
                if column and column not in required_columns:
                    required_columns.append(column)
            return decision.model_copy(update={"supporting_columns": required_columns})
        except Exception as error:
            logger.warning("Schema answerability fallback failed closed: %s", error)
            return None

    @staticmethod
    def _parse(content: str) -> SchemaAnswerabilityDecision | None:
        start = content.find("{")
        end = content.rfind("}")
        if start < 0 or end < start:
            return None
        try:
            payload = json.loads(content[start : end + 1])
            return SchemaReasoningDecision.model_validate(payload)
        except (json.JSONDecodeError, ValueError):
            return None

    @staticmethod
    def _render_prompt(question: str) -> str:
        schema_knowledge = load_schema_knowledge()
        template = prompt_loader.get_prompt("schema_answerability")
        return prompt_renderer.render(
            template,
            {
                "schema_knowledge": schema_knowledge.render_for_llm(),
                "unavailable_concepts": (
                    "\n".join(f"- {item}" for item in schema_knowledge.unavailable_concepts)
                    or "- none"
                ),
                "question": question,
            },
        )
