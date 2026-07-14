import logging
import re
import time
from collections import deque
from typing import TYPE_CHECKING

from app.application_models.query_analysis import QueryAnalysis
from app.context.extractor import ContextExtractor
from app.planning.models import DateFilterPlan, JoinStep, QueryPlan

if TYPE_CHECKING:  # avoid importing the database_intelligence package at runtime
    from app.database_intelligence.models import TableMetadata
    from app.semantics.models import SemanticFrame

logger = logging.getLogger(__name__)

# Canonical entity type -> backing table in the hospital schema.
_ENTITY_TABLES = {
    "Doctor": "doktorlar",
    "Patient": "hastalar",
    "Appointment": "randevular",
    "Department": "bolumler",
    "Prescription": "receteler",
    "Diagnosis": "tanilar",
    "Invoice": "faturalar",
    "LaboratoryTest": "laboratuvar_testleri",
    "Hospitalization": "yatislar",
}

_DEPARTMENT_TABLE = "bolumler"

# "en yoğun X" means volume of appointments in this domain — when no fact
# entity is mentioned explicitly, appointment volume is the implied fact.
_VOLUME_RANKING_MARKERS = ("yogun", "en cok randevu", "en fazla randevu")

_NEGATION_PATTERN = re.compile(r"\b(olmayan|bulunmayan|almayan|gelmeyen)\w*\b|\bhic\b")

_ASCENDING_MARKERS = ("en az", "en dusuk", "en seyrek")

_DESCRIPTIVE_PRIORITY = ("ad_soyad", "bolum_adi", "sirket_adi", "test_adi", "name", "title")


class QueryPlanner:
    """Deterministic planner organizing NLU output into a QueryPlan (AG-022).

    Only arranges information already extracted by the NLU and the schema
    retriever — it never generates SQL and never calls an LLM.
    """

    def __init__(self, context_extractor: ContextExtractor | None = None) -> None:
        self._extractor = context_extractor or ContextExtractor()

    def build_plan(
        self,
        question: str,
        analysis: QueryAnalysis,
        tables: list["TableMetadata"],
        semantic_frame: "SemanticFrame | None" = None,
    ) -> QueryPlan:
        start = time.perf_counter()
        folded = self._extractor.fold(question)
        signals = self._extractor.extract(question)
        table_map = {table.name: table for table in tables}

        # REASONING-001: when a semantic frame is provided it is the
        # authoritative interpretation — the planner organizes, it does not
        # re-derive what the user meant.
        if semantic_frame is not None and semantic_frame.primary_subject:
            output_entity = semantic_frame.primary_subject
            fact_entity = semantic_frame.fact_subject or output_entity
        else:
            output_entity, fact_entity = self._entities(analysis, folded)
        output_table = self._entity_table(output_entity, table_map)
        fact_table = self._entity_table(fact_entity, table_map) or output_table

        date_filters = self._date_filters(analysis, fact_table or output_table, table_map)
        aggregation = self._aggregation(analysis)
        ranking, order = self._ranking(analysis, signals.analysis_type, folded)
        extra_filters = self._extra_filters(folded)

        join_path = self._join_path(
            fact_table,
            output_table,
            signals.department,
            table_map,
        )
        # Pure aggregate questions over a single entity ("Bugün kaç randevu?")
        # return a scalar — requiring a descriptive projection would be wrong.
        if aggregation and (output_table == fact_table or output_table is None):
            projection: list[str] = []
        else:
            projection = self._projection(output_table, table_map)
        distinct = bool(
            output_table and fact_table and output_table != fact_table and not aggregation
        )

        plan = QueryPlan(
            question=question,
            output_entity=output_entity,
            fact_entity=fact_entity,
            output_table=output_table,
            fact_table=fact_table,
            date_filters=date_filters,
            department_filter=signals.department,
            extra_filters=extra_filters,
            aggregation=aggregation,
            ranking=ranking,
            limit=analysis.detected_limit,
            order=order,
            analysis_type=signals.analysis_type,
            join_path=join_path,
            projection=projection,
            distinct=distinct,
            planner_ms=(time.perf_counter() - start) * 1000,
        )
        self._log_plan(plan)
        return plan

    # ── Entity resolution ────────────────────────────────────────────────

    def _entities(
        self, analysis: QueryAnalysis, folded_question: str
    ) -> tuple[str | None, str | None]:
        """Determines output and fact entities from mention order.

        Turkish is verb-final: the requested object sits closest to the action
        verb at the end, so the LAST mentioned non-department entity is the
        output and the FIRST mentioned one is the fact being filtered over.
        """
        positioned: list[tuple[int, str]] = []
        for entity in analysis.entities:
            position = folded_question.find(entity.normalized_text)
            positioned.append((position if position >= 0 else 0, entity.entity_type))
        positioned.sort()

        non_department = [name for _, name in positioned if name != "Department"]
        has_department = any(name == "Department" for _, name in positioned)

        if non_department:
            output = non_department[-1]
            fact = non_department[0]
        elif has_department:
            output = "Department"
            fact = "Department"
        else:
            return None, None

        # "En yoğun bölüm/doktor" ranks by appointment volume — when no fact
        # entity is stated, appointments are the implied fact.
        if fact == output and any(m in folded_question for m in _VOLUME_RANKING_MARKERS):
            if output != "Appointment":
                fact = "Appointment"
        return output, fact

    def _entity_table(
        self, entity: str | None, table_map: dict[str, "TableMetadata"]
    ) -> str | None:
        if entity is None:
            return None
        table_name = _ENTITY_TABLES.get(entity)
        if table_name and table_name in table_map:
            return table_name
        return table_name  # keep the mapping even if the retriever omitted it

    # ── Constraints ──────────────────────────────────────────────────────

    def _date_filters(
        self,
        analysis: QueryAnalysis,
        anchor_table: str | None,
        table_map: dict[str, "TableMetadata"],
    ) -> list[DateFilterPlan]:
        column = self._date_column(anchor_table, table_map)
        return [
            DateFilterPlan(
                expression=date_range.expression,
                start_date=date_range.start_date.isoformat(),
                end_date=date_range.end_date.isoformat(),
                column=column,
            )
            for date_range in analysis.detected_dates
        ]

    def _date_column(
        self, table_name: str | None, table_map: dict[str, "TableMetadata"]
    ) -> str | None:
        table = table_map.get(table_name or "")
        if not table:
            return None
        for col in table.columns:
            lowered = col.name.lower()
            if "tarih" in lowered or "date" in lowered:
                return col.name
        return None

    def _aggregation(self, analysis: QueryAnalysis) -> str | None:
        for operation in ("COUNT", "SUM", "AVG"):
            if operation in analysis.detected_operations:
                return operation
        return None

    def _ranking(
        self,
        analysis: QueryAnalysis,
        analysis_type: str | None,
        folded_question: str,
    ) -> tuple[str | None, str | None]:
        order = analysis.detected_order
        if analysis_type == "ranking":
            direction = (
                "ASC"
                if any(marker in folded_question for marker in _ASCENDING_MARKERS)
                else "DESC"
            )
            return direction, order
        return (order, order) if order else (None, None)

    def _extra_filters(self, folded_question: str) -> list[str]:
        filters: list[str] = []
        if _NEGATION_PATTERN.search(folded_question):
            filters.append(
                "NEGATION: exclude matching rows (NOT EXISTS or LEFT JOIN ... IS NULL)"
            )
        return filters

    # ── Relationship planning ────────────────────────────────────────────

    def _join_path(
        self,
        fact_table: str | None,
        output_table: str | None,
        department_filter: str | None,
        table_map: dict[str, "TableMetadata"],
    ) -> list[JoinStep]:
        """Minimal FK path: fact -> output, extended to bolumler for department filters.

        Paths come only from declared foreign keys — joins are never guessed.
        """
        steps: list[JoinStep] = []
        adjacency = self._fk_adjacency(table_map)

        if fact_table and output_table and fact_table != output_table:
            steps.extend(self._shortest_path(fact_table, output_table, adjacency))

        if department_filter and _DEPARTMENT_TABLE in table_map:
            covered = {fact_table, output_table}
            covered.update(step.from_table for step in steps)
            covered.update(step.to_table for step in steps)
            if _DEPARTMENT_TABLE not in covered:
                for anchor in (output_table, fact_table):
                    if not anchor:
                        continue
                    extension = self._shortest_path(anchor, _DEPARTMENT_TABLE, adjacency)
                    if extension:
                        steps.extend(extension)
                        break
        return steps

    def _fk_adjacency(
        self, table_map: dict[str, "TableMetadata"]
    ) -> dict[str, list[JoinStep]]:
        """Undirected FK adjacency; each edge keeps the true FK owner direction."""
        adjacency: dict[str, list[JoinStep]] = {name: [] for name in table_map}
        for table in table_map.values():
            for fk in table.foreign_keys:
                if fk.referred_table not in table_map:
                    continue
                step = JoinStep(
                    from_table=table.name,
                    from_column=fk.constrained_columns[0] if fk.constrained_columns else "",
                    to_table=fk.referred_table,
                    to_column=fk.referred_columns[0] if fk.referred_columns else "id",
                )
                adjacency[table.name].append(step)
                adjacency[fk.referred_table].append(step)
        return adjacency

    def _shortest_path(
        self,
        source: str,
        target: str,
        adjacency: dict[str, list[JoinStep]],
    ) -> list[JoinStep]:
        if source not in adjacency or target not in adjacency:
            return []
        queue: deque[str] = deque([source])
        parents: dict[str, tuple[str, JoinStep]] = {}
        visited = {source}
        while queue:
            current = queue.popleft()
            if current == target:
                break
            for step in adjacency.get(current, []):
                neighbor = step.to_table if step.from_table == current else step.from_table
                if neighbor in visited:
                    continue
                visited.add(neighbor)
                parents[neighbor] = (current, step)
                queue.append(neighbor)
        if target not in parents and source != target:
            return []
        path: list[JoinStep] = []
        node = target
        while node != source:
            parent, step = parents[node]
            path.append(step)
            node = parent
        path.reverse()
        return path

    # ── Projection ───────────────────────────────────────────────────────

    def _projection(
        self, output_table: str | None, table_map: dict[str, "TableMetadata"]
    ) -> list[str]:
        table = table_map.get(output_table or "")
        if not table:
            return []
        column_names = [col.name for col in table.columns]
        for candidate in _DESCRIPTIVE_PRIORITY:
            if candidate in column_names:
                return [candidate]
        for name in column_names:
            if name.lower().endswith("_adi"):
                return [name]
        non_ids = [n for n in column_names if n != "id" and not n.endswith("_id")]
        return non_ids[:1]

    # ── Logging ──────────────────────────────────────────────────────────

    def _log_plan(self, plan: QueryPlan) -> None:
        logger.info(
            "\n================ QUERY PLAN (AG-022) ================\n"
            f"Question   : {plan.question}\n"
            f"Output     : {plan.output_entity} ({plan.output_table})\n"
            f"Fact       : {plan.fact_entity} ({plan.fact_table})\n"
            f"Dates      : {[f'{d.expression} {d.start_date}..{d.end_date}' for d in plan.date_filters] or 'none'}\n"
            f"Department : {plan.department_filter or 'none'}\n"
            f"Extra      : {plan.extra_filters or 'none'}\n"
            f"Aggregation: {plan.aggregation or 'none'}  Ranking: {plan.ranking or 'none'}  "
            f"Limit: {plan.limit or 'none'}\n"
            f"Join Path  : {' | '.join(s.render() for s in plan.join_path) or 'none'}\n"
            f"Projection : {plan.projection or 'none'}  Distinct: {plan.distinct}\n"
            f"Planner    : {plan.planner_ms:.2f} ms  Constraints: {plan.constraint_count()}\n"
            "=====================================================",
            extra={
                "query_plan": plan.model_dump(),
                "planner_ms": plan.planner_ms,
                "constraint_count": plan.constraint_count(),
            },
        )


def format_plan_for_prompt(plan: QueryPlan) -> str:
    """Renders the QueryPlan as a compact contract section for the SQL prompt."""
    lines: list[str] = ["Plan (implement every item):"]
    if plan.output_table:
        projection = f".{plan.projection[0]}" if plan.projection else ""
        distinct = " DISTINCT" if plan.distinct else ""
        lines.append(f"- Output:{distinct} {plan.output_table}{projection}")
    if plan.fact_table and plan.fact_table != plan.output_table:
        lines.append(f"- From: {plan.fact_table}")
    if plan.join_path:
        joins = "; ".join(step.render() for step in plan.join_path)
        lines.append(f"- Joins: {joins}")
    for date_filter in plan.date_filters:
        column = date_filter.column or "the date column"
        if date_filter.start_date == date_filter.end_date:
            lines.append(f"- Filter: {column} = '{date_filter.start_date}'")
        else:
            lines.append(
                f"- Filter: {column} BETWEEN '{date_filter.start_date}' "
                f"AND '{date_filter.end_date}'"
            )
    if plan.department_filter:
        lines.append(f"- Filter: department name = '{plan.department_filter}'")
    for extra in plan.extra_filters:
        lines.append(f"- Filter: {extra}")
    if plan.aggregation:
        lines.append(f"- Aggregate: {plan.aggregation}")
    if plan.ranking:
        lines.append(f"- Order: {plan.ranking} (ORDER BY required)")
    if plan.limit:
        lines.append(f"- Limit: {plan.limit}")
    return "\n".join(lines) if len(lines) > 1 else ""
