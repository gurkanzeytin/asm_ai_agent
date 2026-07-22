import json
from functools import lru_cache
from pathlib import Path

from tools.evaluation.models import EvaluationCase, EvaluationDataset

from app.analytics.result_contracts import (
    AnomalyResult,
    CohortResult,
    CountResult,
    DistributionResult,
    PeriodComparisonResult,
    RatioResult,
    TrendResult,
    VarianceResult,
)
from app.semantics.catalog import CatalogValidationError, load_column_catalog, load_metric_catalog
from app.services.deterministic_sql_builder import SUPPORTED_ANALYSIS_TYPES

_DATASET_PATH = Path(__file__).resolve().parents[2] / "app" / "resources" / "evaluation_cases.json"

RESULT_CONTRACTS = {
    cls.__name__
    for cls in (
        CountResult,
        DistributionResult,
        RatioResult,
        PeriodComparisonResult,
        CohortResult,
        AnomalyResult,
        VarianceResult,
        TrendResult,
    )
}

EXTRA_ANALYSIS_TYPES = {
    "conversion",
    "multi_metric_performance",
    "lead_time_analysis",
}


@lru_cache(maxsize=1)
def load_evaluation_dataset(path: str | Path | None = None) -> EvaluationDataset:
    dataset_path = Path(path) if path else _DATASET_PATH
    try:
        raw = json.loads(dataset_path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise CatalogValidationError(f"Evaluation dataset missing: {dataset_path}") from error
    except json.JSONDecodeError as error:
        raise CatalogValidationError(f"Evaluation dataset is not valid JSON: {error}") from error

    dataset = EvaluationDataset(**raw)
    validate_evaluation_dataset(dataset)
    return dataset


def validate_evaluation_dataset(dataset: EvaluationDataset) -> None:
    known_columns = load_column_catalog().column_names()
    known_metrics = set(load_metric_catalog().by_id())
    known_analysis = SUPPORTED_ANALYSIS_TYPES | EXTRA_ANALYSIS_TYPES
    seen_ids: set[str] = set()

    for case in dataset.cases:
        if case.id in seen_ids:
            raise CatalogValidationError(f"Duplicate evaluation case id: {case.id}")
        seen_ids.add(case.id)

        unknown_metrics = set(case.expected.metrics) - known_metrics
        if unknown_metrics:
            raise CatalogValidationError(
                f"Evaluation case '{case.id}' uses unknown metrics: {sorted(unknown_metrics)}"
            )
        unknown_columns = (
            set(case.expected.dimensions)
            | set(case.sql_requirements.must_use_columns)
            | set(case.sql_requirements.must_not_use_columns)
        ) - known_columns
        if unknown_columns:
            raise CatalogValidationError(
                f"Evaluation case '{case.id}' uses unknown columns: {sorted(unknown_columns)}"
            )
        if case.expected.analysis_type and case.expected.analysis_type not in known_analysis:
            raise CatalogValidationError(
                f"Evaluation case '{case.id}' has unknown analysis type: "
                f"{case.expected.analysis_type}"
            )
        if case.expected.result_contract and case.expected.result_contract not in RESULT_CONTRACTS:
            raise CatalogValidationError(
                f"Evaluation case '{case.id}' has unknown result contract: "
                f"{case.expected.result_contract}"
            )


def select_cases(
    dataset: EvaluationDataset,
    *,
    suite: str = "blind",
    case_id: str | None = None,
    limit: int | None = None,
) -> list[EvaluationCase]:
    if case_id:
        return [case for case in dataset.cases if case.id == case_id]
    if suite == "all":
        selected = list(dataset.cases)
    elif suite == "acceptance":
        selected = [case for case in dataset.cases if case.id.startswith("E2E-RW-")]
    elif suite == "deterministic":
        selected = [
            case
            for case in dataset.cases
            if case.expected.sql_source == "deterministic"
        ]
    elif suite == "live":
        selected = [case for case in dataset.cases if case.requires_live_db]
    else:
        selected = [case for case in dataset.cases if case.blind]
    return selected[:limit] if limit else selected

