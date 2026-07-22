from __future__ import annotations

# ruff: noqa: E501
import asyncio
import statistics
import time
from datetime import UTC, datetime
from uuid import uuid4

from tools.evaluation.dataset import load_evaluation_dataset, select_cases
from tools.evaluation.models import (
    CaseResult,
    EvaluationMode,
    EvaluationRun,
    EvaluationStage,
    EvaluationSummary,
    FailureCode,
    FailureRecord,
    StageResult,
)
from tools.evaluation.scorers import (
    score_final_answer,
    score_query_plan,
    score_result_contract,
    score_routing,
    score_sql_generation,
    score_sql_semantics,
)

from app.analytics.result_contracts import TypedResultNormalizer
from app.application_models.workflow_models import QueryResult
from app.core.config import settings
from app.database_intelligence.models import ViewMetadata
from app.planning.models import QueryPlan
from app.planning.planner import QueryPlanner
from app.services.deterministic_sql_builder import (
    DeterministicSQL,
    DeterministicSQLBuilder,
    UnsupportedPlan,
)
from app.services.query_analyzer import QueryAnalyzer
from app.sql_validator.validator import SQLValidator

VIEW = ViewMetadata(name="dbo.vw_RandevuRaporu", columns=[])


class EvaluationRunner:
    def __init__(self) -> None:
        self.analyzer = QueryAnalyzer()
        self.planner = QueryPlanner()
        self.builder = DeterministicSQLBuilder()
        self.validator = SQLValidator()
        self.normalizer = TypedResultNormalizer()

    def run(
        self,
        *,
        suite: str = "blind",
        case_id: str | None = None,
        mode: EvaluationMode = EvaluationMode.SQL_GENERATION,
        limit: int | None = None,
    ) -> EvaluationRun:
        dataset = load_evaluation_dataset()
        cases = select_cases(dataset, suite=suite, case_id=case_id, limit=limit)
        results = [self.run_case(case, mode=mode) for case in cases]
        run = EvaluationRun(
            run_id=datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8],
            generated_at=datetime.now(UTC).isoformat(),
            suite=suite if not case_id else case_id,
            mode=mode,
            environment={
                "sql_dialect": getattr(settings, "SQL_DIALECT", "tsql"),
                "database_provider": "mssql" if (settings.DATABASE_URL or "").startswith("mssql") else "unknown",
                "live_db_available": self._live_db_available(),
            },
            summary=summarize_results(results),
            results=results,
        )
        return run

    def run_case(self, case, *, mode: EvaluationMode) -> CaseResult:
        start = time.perf_counter()
        stages: list[StageResult] = []
        plan: QueryPlan | None = None
        sql: str | None = None
        sql_source: str | None = None
        contract: str | None = None
        aliases: list[str] = []
        normalized = None

        if mode in {EvaluationMode.LIVE_DB, EvaluationMode.FULL_ENDPOINT} and not self._live_db_available():
            return CaseResult(
                case_id=case.id,
                question=case.question,
                category=case.category,
                mode=mode,
                skipped=True,
                skip_reason="live database is not configured",
            )

        ambiguity = self.analyzer.detect_ambiguity(case.question)
        stages.append(score_routing(case, clarification_required=ambiguity is not None))

        if ambiguity is None:
            analysis = self.analyzer.analyze(case.question)
            plan = self.planner.build_plan(case.question, analysis, tables=[], views=[VIEW])
        stages.append(score_query_plan(case, plan))

        if mode == EvaluationMode.PLANNER_ONLY or ambiguity is not None or plan is None:
            return self._finish(case, mode, stages, start, plan=plan)

        built = self.builder.build(plan)
        validation = None
        if isinstance(built, DeterministicSQL):
            sql = built.sql
            sql_source = "deterministic"
            contract = built.result_schema
            aliases = built.expected_aliases
            validation = self.validator.validate(sql)
        elif isinstance(built, UnsupportedPlan):
            sql_source = "llm"
            if case.expected.sql_source == "deterministic":
                sql = None
            else:
                sql = None

        stages.append(
            score_sql_generation(
                case,
                sql=sql,
                sql_source=sql_source,
                result_contract=contract,
                aliases=aliases,
                validation=validation,
                plan=plan,
            )
        )
        stages.append(score_sql_semantics(case, sql, plan=plan))

        if mode == EvaluationMode.SQL_GENERATION:
            return self._finish(
                case,
                mode,
                stages,
                start,
                plan=plan,
                sql=sql,
                sql_source=sql_source,
                result_contract=contract,
            )

        if mode == EvaluationMode.MOCKED_EXECUTION and contract:
            query_result = _mock_query_result(contract, aliases)
            normalized = self.normalizer.normalize(
                query_result,
                plan=plan,
                schema_name=contract,
                expected_aliases=aliases,
            )
            stages.append(score_result_contract(case, normalized, plan=plan, sql=sql))
            answer = _mock_answer(case, plan, normalized)
            stages.append(score_final_answer(case, answer))
        elif mode == EvaluationMode.MOCKED_EXECUTION:
            skipped = StageResult(
                stage=EvaluationStage.RESULT_CONTRACT,
                skipped=True,
                passed=True,
            )
            stages.append(skipped)
        elif mode == EvaluationMode.LIVE_DB and contract and sql:
            execution_start = time.perf_counter()
            try:
                query_result = asyncio.run(_execute_live_sql(sql, self.validator))
                stages.append(
                    StageResult(
                        stage=EvaluationStage.EXECUTION,
                        duration_ms=(time.perf_counter() - execution_start) * 1000,
                    )
                )
                normalized = self.normalizer.normalize(
                    query_result,
                    plan=plan,
                    schema_name=contract,
                    expected_aliases=aliases,
                )
                stages.append(score_result_contract(case, normalized, plan=plan, sql=sql))
                stages.append(score_final_answer(case, _mock_answer(case, plan, normalized)))
            except Exception as error:
                stages.append(_execution_failure(case, plan, sql, error, execution_start))
        elif mode == EvaluationMode.FULL_ENDPOINT:
            execution_start = time.perf_counter()
            try:
                response = asyncio.run(_call_full_endpoint(case.question))
                endpoint_sql = response.get("generated_sql")
                endpoint_result = response.get("query_result")
                if not endpoint_sql or not endpoint_result:
                    raise RuntimeError("endpoint did not return SQL and query_result")
                sql = endpoint_sql
                query_result = QueryResult(
                    columns=endpoint_result.get("columns", []),
                    rows=endpoint_result.get("rows", []),
                    row_count=endpoint_result.get("row_count", 0),
                    execution_time_ms=float(
                        (response.get("timing") or {}).get("execute_sql_ms") or 0.0
                    ),
                    success=True,
                    executed_at=datetime.now(UTC),
                    database_provider="mssql",
                )
                stages.append(
                    StageResult(
                        stage=EvaluationStage.EXECUTION,
                        duration_ms=(time.perf_counter() - execution_start) * 1000,
                    )
                )
                normalized = self.normalizer.normalize(
                    query_result,
                    plan=plan,
                    schema_name=contract,
                    expected_aliases=aliases,
                )
                stages.append(score_result_contract(case, normalized, plan=plan, sql=sql))
                answer = (response.get("report") or {}).get("markdown", "")
                stages.append(score_final_answer(case, answer))
            except Exception as error:
                stages.append(_execution_failure(case, plan, sql, error, execution_start))

        return self._finish(
            case,
            mode,
            stages,
            start,
            plan=plan,
            sql=sql,
            sql_source=sql_source,
            result_contract=contract,
            row_count=len(normalized.rows) if normalized else None,
        )

    def _finish(
        self,
        case,
        mode: EvaluationMode,
        stages: list[StageResult],
        start: float,
        *,
        plan: QueryPlan | None = None,
        sql: str | None = None,
        sql_source: str | None = None,
        result_contract: str | None = None,
        row_count: int | None = None,
    ) -> CaseResult:
        failures = [failure for stage in stages for failure in stage.failures]
        return CaseResult(
            case_id=case.id,
            question=case.question,
            category=case.category,
            mode=mode,
            passed=not failures,
            sql_source=sql_source,
            result_contract=result_contract,
            row_count=row_count,
            total_ms=(time.perf_counter() - start) * 1000,
            stage_results=stages,
            failures=failures,
            generated_sql=sql,
            plan_summary=_plan_summary(plan),
        )

    def _live_db_available(self) -> bool:
        url = settings.DATABASE_URL or ""
        return bool(url and url.startswith("mssql"))


def summarize_results(results: list[CaseResult]) -> EvaluationSummary:
    completed = [result for result in results if not result.skipped]
    failed = [result for result in completed if not result.passed]
    durations = sorted(result.total_ms for result in completed)
    by_stage: dict[str, list[bool]] = {}
    for result in completed:
        for stage in result.stage_results:
            if stage.skipped:
                continue
            by_stage.setdefault(stage.stage.value, []).append(stage.passed)

    failure_counts: dict[str, int] = {}
    for result in failed:
        for failure in result.failures:
            failure_counts[failure.failure_code.value] = (
                failure_counts.get(failure.failure_code.value, 0) + 1
            )
    execution_durations = [
        stage.duration_ms
        for result in completed
        for stage in result.stage_results
        if stage.stage == EvaluationStage.EXECUTION and not stage.skipped
    ]
    timeout_count = sum(
        1
        for result in completed
        if any(failure.failure_code == FailureCode.TIMEOUT for failure in result.failures)
    )

    return EvaluationSummary(
        total_cases=len(results),
        passed=len([result for result in completed if result.passed]),
        failed=len(failed),
        skipped=len([result for result in results if result.skipped]),
        layer_accuracy={
            stage: round(100.0 * sum(values) / len(values), 2)
            for stage, values in by_stage.items()
            if values
        },
        failure_counts=dict(sorted(failure_counts.items(), key=lambda item: (-item[1], item[0]))),
        p50_ms=_percentile(durations, 50),
        p95_ms=_percentile(durations, 95),
        max_ms=max(durations) if durations else 0.0,
        deterministic_sql_avg_ms=_avg(
            result.total_ms for result in completed if result.sql_source == "deterministic"
        ),
        llm_sql_avg_ms=_avg(result.total_ms for result in completed if result.sql_source == "llm"),
        live_execution_avg_ms=_avg(execution_durations),
        timeout_rate=(timeout_count / len(completed)) if completed else 0.0,
    )


def _mock_query_result(contract: str, aliases: list[str]) -> QueryResult:
    row = {alias: _sample_value(alias) for alias in aliases}
    if not row and contract == "PeriodComparisonResult":
        row = {
            "current_period_count": 120,
            "baseline_period_count": 100,
            "absolute_change": 20,
            "percentage_change": 20.0,
        }
    return QueryResult(
        columns=list(row),
        rows=[row],
        row_count=1,
        execution_time_ms=1.0,
        success=True,
        executed_at=datetime.now(UTC),
        database_provider="mock",
    )


def _sample_value(alias: str) -> int | float | str:
    lowered = alias.lower()
    if lowered.endswith("_period_label"):
        return "sample_period"
    if lowered in {"subeadi", "genelrandevubolumadi", "genelrandevukaynakadi", "randevudurumu"}:
        return "sample_group"
    if any(marker in lowered for marker in ("rate", "percentage", "share")):
        return 25.0
    if "ratio" in lowered:
        return 2.0
    return 10


def _mock_answer(case, plan: QueryPlan, normalized) -> str:
    assumptions = " ".join(plan.assumptions)
    return (
        f"Varsayimlar yorumlandi: {assumptions} {case.question} icin "
        f"{normalized.schema_name} sonuc sekliyle "
        f"{len(normalized.rows)} aggregate satir ozetlendi."
    ).strip()


def _plan_summary(plan: QueryPlan | None) -> dict | None:
    if not plan:
        return None
    return {
        "analysis_type": plan.analysis_type,
        "metrics": plan.metrics,
        "dimensions": plan.dimensions,
        "answerable": plan.answerable,
        "current_period": plan.current_period,
        "baseline_period": plan.baseline_period,
        "cohort": plan.cohort,
        "minimum_sample_size": plan.minimum_sample_size,
        "periods": [period.model_dump() for period in plan.periods],
    }


async def _execute_live_sql(sql: str, validator: SQLValidator) -> QueryResult:
    from app.database.session import SessionLocal, engine
    from app.repositories.base import ScopedAnalyticalRepository
    from app.services.execution_service import ExecutionService

    repository = ScopedAnalyticalRepository(SessionLocal)
    try:
        return await ExecutionService(repository, validator).execute_sql(sql)
    finally:
        await engine.dispose()


async def _call_full_endpoint(question: str) -> dict:
    from httpx import ASGITransport, AsyncClient

    from app.database.session import engine
    from app.main import app

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://evaluation") as client:
            response = await client.post(
                "/api/v1/report/",
                json={"question": question, "session_id": f"evaluation-{uuid4().hex}"},
                timeout=120.0,
            )
        response.raise_for_status()
        return response.json()
    finally:
        await engine.dispose()


def _execution_failure(case, plan, sql, error, start) -> StageResult:
    duration = (time.perf_counter() - start) * 1000
    code = FailureCode.TIMEOUT if isinstance(error, TimeoutError) else FailureCode.RESULT_NORMALIZATION_FAILURE
    return StageResult(
        stage=EvaluationStage.EXECUTION,
        passed=False,
        duration_ms=duration,
        failures=[
            FailureRecord(
                case_id=case.id,
                stage=EvaluationStage.EXECUTION,
                failure_code=code,
                expected="successful SQL execution",
                actual=str(error),
                component="ExecutionService/FastAPI endpoint",
                generated_plan=plan.model_dump() if plan else None,
                generated_sql=sql,
                exception_type=type(error).__name__,
                duration_ms=duration,
            )
        ],
    )


def _percentile(values: list[float], percentile: int) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    index = round((percentile / 100) * (len(values) - 1))
    return values[index]


def _avg(values) -> float:
    materialized = list(values)
    return statistics.mean(materialized) if materialized else 0.0
