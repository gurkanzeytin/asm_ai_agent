"""Typed LLM-facing view over the canonical schema intelligence catalogs."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, Field

from app.semantics import catalog, view_mapping


class ColumnKnowledge(BaseModel):
    name: str
    business_name: str
    description: str
    data_role: str
    semantic_type: str
    synonyms: list[str] = Field(default_factory=list)
    supported_operations: list[str] = Field(default_factory=list)
    related_columns: list[str] = Field(default_factory=list)
    related_metrics: list[str] = Field(default_factory=list)
    relationship_ids: list[str] = Field(default_factory=list)
    business_rules: list[str] = Field(default_factory=list)
    known_values: list[str] = Field(default_factory=list)
    value_grounding: Literal["verified", "partial", "live_db_required", "not_applicable"]
    value_notes: str = ""
    pii: bool = False
    selectable: bool = True
    filterable: bool = True
    groupable: bool = False
    aggregatable: str = "none"


class MetricKnowledge(BaseModel):
    id: str
    name: str
    description: str
    analysis_type: str
    required_columns: list[str]
    formula_type: str
    result_type: str
    synonyms: list[str] = Field(default_factory=list)
    null_behavior: str = ""


class RelationshipKnowledge(BaseModel):
    id: str
    name: str
    columns: list[str]
    dimensions: list[str]
    metrics: list[str]
    supported_analyses: list[str]
    warnings: list[str]


class SchemaKnowledge(BaseModel):
    view: str
    purpose: str
    row_grain: str
    columns: list[ColumnKnowledge]
    metrics: list[MetricKnowledge]
    relationships: list[RelationshipKnowledge]
    unavailable_concepts: list[str]

    def render_for_llm(self) -> str:
        """Renders compact semantic cards without copying catalog business logic."""
        lines = [
            f"VIEW {self.view}",
            f"PURPOSE {self.purpose}",
            f"ROW_GRAIN {self.row_grain}",
            "COLUMNS",
        ]
        for column in self.columns:
            rules = " | ".join(column.business_rules) or "none"
            values = ", ".join(column.known_values) or "none"
            lines.append(
                f"- {column.name}: {column.business_name}; {column.description}; "
                f"role={column.data_role}; type={column.semantic_type}; "
                f"operations={','.join(column.supported_operations) or 'none'}; "
                f"groupable={column.groupable}; filterable={column.filterable}; "
                f"selectable={column.selectable}; pii={column.pii}; "
                f"related_metrics={','.join(column.related_metrics) or 'none'}; "
                f"known_values={values}; value_grounding={column.value_grounding}; "
                f"rules={rules}"
            )
        lines.append("METRICS")
        for metric in self.metrics:
            lines.append(
                f"- {metric.id}: {metric.name}; {metric.description}; "
                f"analysis={metric.analysis_type}; formula_type={metric.formula_type}; "
                f"columns={','.join(metric.required_columns)}; result={metric.result_type}"
            )
        lines.append("RELATIONSHIPS")
        for relationship in self.relationships:
            lines.append(
                f"- {relationship.id}: {relationship.name}; "
                f"dimensions={','.join(relationship.dimensions) or 'none'}; "
                f"metrics={','.join(relationship.metrics) or 'none'}; "
                f"analyses={','.join(relationship.supported_analyses) or 'none'}"
            )
        return "\n".join(lines)


def _value_grounding(spec: catalog.ColumnSpec) -> str:
    categorical = "categorical" in spec.semantic_type or spec.semantic_type.endswith("_code")
    if not categorical:
        return "not_applicable"
    if spec.known_values and spec.values_verified:
        return "verified"
    if spec.known_values:
        return "partial"
    return "live_db_required"


@lru_cache(maxsize=1)
def load_schema_knowledge() -> SchemaKnowledge:
    """Composes catalogs at runtime so no second hand-maintained dictionary drifts."""
    column_catalog = catalog.load_column_catalog()
    metric_catalog = catalog.load_metric_catalog()
    relationship_catalog = catalog.load_relationship_catalog()
    view_entry = view_mapping.get_view_entry(column_catalog.view)

    concept_rules: dict[str, list[str]] = {}
    for concept in view_entry.get("concepts", {}).values():
        column = concept.get("column")
        note = concept.get("note")
        if column and note:
            concept_rules.setdefault(column, []).append(note)

    metrics_by_column: dict[str, list[str]] = {}
    for metric in metric_catalog.metrics:
        for column in metric.required_columns:
            metrics_by_column.setdefault(column, []).append(metric.id)

    relationships_by_column: dict[str, list[str]] = {}
    for relationship in relationship_catalog.relationships:
        for column in relationship.columns:
            relationships_by_column.setdefault(column, []).append(relationship.id)

    semantic_descriptions = view_entry.get("columns", {})
    columns = [
        ColumnKnowledge(
            name=spec.column,
            business_name=spec.business_name,
            description=semantic_descriptions.get(spec.column) or spec.description,
            data_role=spec.data_role,
            semantic_type=spec.semantic_type,
            synonyms=list(spec.synonyms),
            supported_operations=list(spec.supported_operations),
            related_columns=list(spec.related_columns),
            related_metrics=metrics_by_column.get(spec.column, []),
            relationship_ids=relationships_by_column.get(spec.column, []),
            business_rules=[*spec.common_mistakes, *concept_rules.get(spec.column, [])],
            known_values=list(spec.known_values),
            value_grounding=_value_grounding(spec),
            value_notes=spec.value_notes,
            pii=spec.pii,
            selectable=spec.selectable,
            filterable=spec.filterable,
            groupable=spec.groupable,
            aggregatable=spec.aggregatable,
        )
        for spec in column_catalog.columns
    ]
    metrics = [
        MetricKnowledge(
            id=metric.id,
            name=metric.name,
            description=metric.description,
            analysis_type=metric.analysis_type,
            required_columns=list(metric.required_columns),
            formula_type=metric.formula_type,
            result_type=metric.result_type,
            synonyms=list(metric.synonyms),
            null_behavior=metric.null_behavior,
        )
        for metric in metric_catalog.metrics
    ]
    relationships = [
        RelationshipKnowledge(
            id=relationship.id,
            name=relationship.name,
            columns=list(relationship.columns),
            dimensions=list(relationship.dimensions),
            metrics=list(relationship.metrics),
            supported_analyses=list(relationship.supported_analyses),
            warnings=list(relationship.warnings),
        )
        for relationship in relationship_catalog.relationships
    ]
    unavailable = [
        f"{', '.join(item.terms)}: {item.reason} {item.alternative}".strip()
        for item in column_catalog.unanswerable_concepts
    ]
    return SchemaKnowledge(
        view=column_catalog.view,
        purpose=view_entry.get("comment") or "Salt-okunur randevu analitiği",
        row_grain="Her satır bir randevu kaydıdır.",
        columns=columns,
        metrics=metrics,
        relationships=relationships,
        unavailable_concepts=unavailable,
    )
