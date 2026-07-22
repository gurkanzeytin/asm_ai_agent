"""Golden dataset loading and deterministic few-shot example retrieval.

The golden dataset (resources/golden_dataset.json) doubles as the planner
evaluation set and the few-shot example pool for SQL generation. Retrieval is
pure metadata matching — no embeddings, no LLM — so it is deterministic and
testable: same plan in, same examples out.
"""

import json
import logging
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field

from app.semantics.catalog import (
    CatalogValidationError,
    load_column_catalog,
    load_metric_catalog,
    stem_text,
)

logger = logging.getLogger(__name__)

_DATASET_PATH = Path(__file__).resolve().parent.parent / "resources" / "golden_dataset.json"

MAX_EXAMPLES = 3


class ExpectedPlan(BaseModel):
    answerable: bool = True
    clarification_required: bool = False


class ExpectedSqlFeatures(BaseModel):
    must_include_concepts: list[str] = Field(default_factory=list)
    must_not_use_columns: list[str] = Field(default_factory=list)


class GoldenExample(BaseModel):
    id: str
    question: str
    analysis_type: str | None = None
    metrics: list[str] = Field(default_factory=list)
    dimensions: list[str] = Field(default_factory=list)
    required_columns: list[str] = Field(default_factory=list)
    date_context: dict | None = None
    expected_plan: ExpectedPlan = Field(default_factory=ExpectedPlan)
    expected_sql_features: ExpectedSqlFeatures = Field(default_factory=ExpectedSqlFeatures)
    result_shape: str = ""
    numerator: str | None = None
    denominator: str | None = None
    unanswerable_reason_hint: str | None = None
    ambiguous_phrase: str | None = None
    # ── AI-INTELLIGENCE-008: blind real-world evaluation expectations ──
    blind: bool = False
    must_use_columns: list[str] = Field(default_factory=list)
    must_produce_metrics: list[str] = Field(default_factory=list)
    must_not_return: str | None = None
    expected_cohort: str | None = None
    expected_baseline: str | None = None
    expected_aggregation: str | None = None


class GoldenDataset(BaseModel):
    view: str
    version: int = 1
    description: str = ""
    questions: list[GoldenExample]


@lru_cache(maxsize=1)
def load_golden_dataset() -> GoldenDataset:
    """Loads and validates the golden dataset against the live catalogs."""
    try:
        raw = json.loads(_DATASET_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise CatalogValidationError(f"Golden dataset missing: {_DATASET_PATH.name}") from e
    except json.JSONDecodeError as e:
        raise CatalogValidationError(f"Golden dataset is not valid JSON: {e}") from e

    dataset = GoldenDataset(**raw)
    known_columns = load_column_catalog().column_names()
    known_metrics = set(load_metric_catalog().by_id())
    seen_ids: set[str] = set()
    for example in dataset.questions:
        if example.id in seen_ids:
            raise CatalogValidationError(f"Duplicate golden dataset id: {example.id}")
        seen_ids.add(example.id)
        unknown_metrics = set(example.metrics) - known_metrics
        if unknown_metrics:
            raise CatalogValidationError(
                f"Golden example '{example.id}' uses unknown metrics: {sorted(unknown_metrics)}"
            )
        unknown_metrics = set(example.must_produce_metrics) - known_metrics
        if unknown_metrics:
            raise CatalogValidationError(
                f"Golden example '{example.id}' expects unknown metrics: {sorted(unknown_metrics)}"
            )
        unknown_columns = (
            set(example.dimensions)
            | set(example.required_columns)
            | set(example.must_use_columns)
        ) - known_columns
        if unknown_columns:
            raise CatalogValidationError(
                f"Golden example '{example.id}' uses unknown columns: {sorted(unknown_columns)}"
            )
    return dataset


def retrieve_examples(
    question: str,
    analysis_type: str | None,
    metrics: list[str],
    dimensions: list[str],
    has_date_filter: bool = False,
    max_examples: int = MAX_EXAMPLES,
) -> list[GoldenExample]:
    """Returns the most relevant answerable golden examples for a resolved plan.

    Scoring is deterministic metadata overlap: analysis type, shared metrics,
    shared dimensions, temporal shape, and stemmed keyword overlap as a
    tiebreak. Unanswerable and clarification examples are never few-shot
    material — they would teach the SQL model the wrong move.
    """
    try:
        dataset = load_golden_dataset()
    except CatalogValidationError as error:
        logger.error("Few-shot retrieval degraded to no examples: %s", error)
        return []

    question_tokens = set(stem_text(question).split())
    metric_set = set(metrics)
    metric_families = {metric.rsplit("_", 1)[0] for metric in metrics}
    dimension_set = set(dimensions)

    scored: list[tuple[float, str, GoldenExample]] = []
    for example in dataset.questions:
        if not example.expected_plan.answerable or example.expected_plan.clarification_required:
            continue
        if example.blind:
            # Blind real-world evaluation questions never leak into few-shot
            # context — they must keep measuring untrained behavior.
            continue
        score = 0.0
        if analysis_type and example.analysis_type == analysis_type:
            score += 3.0
        shared_metrics = metric_set & set(example.metrics)
        score += 2.0 * len(shared_metrics)
        if not shared_metrics and metric_families & {
            metric.rsplit("_", 1)[0] for metric in example.metrics
        }:
            score += 1.0  # same metric family (e.g. cancelled count vs cancelled rate)
        score += 1.0 * len(dimension_set & set(example.dimensions))
        if has_date_filter == bool(example.date_context):
            score += 0.5
        example_tokens = set(stem_text(example.question).split())
        if question_tokens:
            score += len(question_tokens & example_tokens) / len(question_tokens)
        if score > 0:
            scored.append((score, example.id, example))

    scored.sort(key=lambda item: (-item[0], item[1]))
    selected: list[GoldenExample] = []
    seen: set[str] = set()
    for _, example_id, example in scored:
        if example_id in seen:
            continue
        seen.add(example_id)
        selected.append(example)
        if len(selected) >= max_examples:
            break
    return selected


def format_examples_for_prompt(examples: list[GoldenExample]) -> str:
    """Compact verified-example lines for the SQL generation prompt."""
    if not examples:
        return ""
    lines = ["Similar verified questions (follow the same analytical shape):"]
    for example in examples:
        parts = []
        if example.analysis_type:
            parts.append(f"type={example.analysis_type}")
        if example.metrics:
            parts.append(f"metrics={','.join(example.metrics)}")
        if example.dimensions:
            parts.append(f"group_by={','.join(example.dimensions)}")
        if example.numerator and example.denominator:
            parts.append(f"ratio={example.numerator}/{example.denominator}")
        if example.expected_sql_features.must_include_concepts:
            parts.append(
                f"concepts={','.join(example.expected_sql_features.must_include_concepts)}"
            )
        lines.append(f"- [{example.id}] \"{example.question}\" -> {'; '.join(parts)}")
    return "\n".join(lines)
