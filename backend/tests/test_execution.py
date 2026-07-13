from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from langgraph.graph.state import CompiledStateGraph

from app.agent import AgentGraphBuilder, AgentState
from app.agent.nodes.execute_sql import ExecuteSQLNode
from app.application_models.generated_sql import GeneratedSQL
from app.application_models.workflow_models import QueryResult
from app.database_intelligence.models import DatabaseContext
from app.repositories.interfaces import IAnalyticalRepository
from app.services.exceptions import QueryExecutionException
from app.services.execution_service import ExecutionService
from app.services.interfaces import IPromptService, IWorkflowService
from app.sql_validator import ISQLValidator, SQLValidationResult


@pytest.mark.asyncio
async def test_execution_service_success():
    # Setup mocks
    repository = AsyncMock(spec=IAnalyticalRepository)
    sql_validator = MagicMock(spec=ISQLValidator)

    # Mock output returned by database query
    mock_rows = [{"id": 1, "name": "Dr. John"}, {"id": 2, "name": "Dr. Alice"}]
    repository.execute_readonly_query.return_value = mock_rows

    # Mock validation safety assertion success
    sql_validator.validate.return_value = SQLValidationResult(valid=True)

    service = ExecutionService(repository, sql_validator)
    sql = "SELECT * FROM doctors;"
    
    result = await service.execute_sql(sql)

    # Assertions
    assert isinstance(result, QueryResult)
    assert result.success is True
    assert result.columns == ["id", "name"]
    assert result.rows == mock_rows
    assert result.row_count == 2
    assert result.execution_time_ms > 0
    assert isinstance(result.executed_at, datetime)
    assert result.database_provider == "sqlite"  # from settings default in tests config

    sql_validator.validate.assert_called_once_with(sql)
    repository.execute_readonly_query.assert_called_once_with(sql)


@pytest.mark.asyncio
async def test_execution_service_safety_check_failure():
    repository = AsyncMock(spec=IAnalyticalRepository)
    sql_validator = MagicMock(spec=ISQLValidator)

    # Mock validation safety failure
    sql_validator.validate.return_value = SQLValidationResult(
        valid=False, reason="Unsafe DELETE command statement detected."
    )

    service = ExecutionService(repository, sql_validator)
    sql = "DELETE FROM doctors;"

    with pytest.raises(QueryExecutionException) as exc_info:
        await service.execute_sql(sql)

    assert "Read-only safety assertion failed" in str(exc_info.value)
    repository.execute_readonly_query.assert_not_called()


@pytest.mark.asyncio
async def test_execution_service_empty_results():
    repository = AsyncMock(spec=IAnalyticalRepository)
    sql_validator = MagicMock(spec=ISQLValidator)

    repository.execute_readonly_query.return_value = []
    sql_validator.validate.return_value = SQLValidationResult(valid=True)

    service = ExecutionService(repository, sql_validator)
    result = await service.execute_sql("SELECT * FROM doctors WHERE id = -1;")

    assert result.success is True
    assert result.columns == []
    assert result.rows == []
    assert result.row_count == 0


@pytest.mark.asyncio
async def test_execution_service_exception_translation():
    repository = AsyncMock(spec=IAnalyticalRepository)
    sql_validator = MagicMock(spec=ISQLValidator)

    # Mock database error
    repository.execute_readonly_query.side_effect = Exception("Database connection timeout")
    sql_validator.validate.return_value = SQLValidationResult(valid=True)

    service = ExecutionService(repository, sql_validator)

    with pytest.raises(QueryExecutionException) as exc_info:
        await service.execute_sql("SELECT * FROM doctors;")

    assert "Query execution failed" in str(exc_info.value)


@pytest.mark.asyncio
async def test_execute_sql_node_immutability():
    workflow_service = AsyncMock(spec=IWorkflowService)
    
    mock_query_result = QueryResult(
        columns=["id"],
        rows=[{"id": 1}],
        row_count=1,
        execution_time_ms=10.0,
        success=True,
        executed_at=datetime.now(),
        database_provider="sqlite",
    )
    workflow_service.execute_query.return_value = mock_query_result

    node = ExecuteSQLNode(workflow_service)
    
    state = AgentState(
        question="List data",
        generated_sql=GeneratedSQL(
            sql="SELECT 1;",
            normalized_sql="SELECT 1",
            validation_result=SQLValidationResult(valid=True),
            provider="ollama",
            model="qwen",
            latency_ms=10.0,
        ),
    )

    updated_state = await node.execute(state)

    # Immutability assertions
    assert updated_state is not state
    assert updated_state.query_result == mock_query_result
    assert state.query_result is None

    # Tracing metadata updates
    assert updated_state.current_node == "execute_sql"
    assert "execute_sql" in updated_state.completed_nodes
    assert updated_state.duration_ms > 0


@pytest.mark.asyncio
async def test_graph_builder_with_execution_node():
    prompt_service = MagicMock(spec=IPromptService)
    workflow_service = AsyncMock(spec=IWorkflowService)

    prompt_service.retrieve_schema_context.return_value = DatabaseContext(tables=[], views=[])
    prompt_service.render_sql_prompt.return_value = "Rendered Prompt"
    
    mock_generated_sql = GeneratedSQL(
        sql="SELECT * FROM doctors;",
        normalized_sql="SELECT * FROM doctors",
        validation_result=SQLValidationResult(valid=True),
        provider="ollama",
        model="qwen",
        latency_ms=10.0,
    )
    workflow_service.execute_sql_generation.return_value = mock_generated_sql

    mock_query_result = QueryResult(
        columns=["name"],
        rows=[{"name": "Dr. Smith"}],
        row_count=1,
        execution_time_ms=5.0,
        success=True,
        executed_at=datetime.now(),
        database_provider="sqlite",
    )
    workflow_service.execute_query.return_value = mock_query_result

    from app.application_models.generated_report import GeneratedReport
    mock_report = GeneratedReport(
        title="Title",
        markdown="Report text",
        provider="ollama",
        model="qwen",
        latency_ms=10.0,
    )
    workflow_service.execute_report_generation.return_value = mock_report

    # Build E2E graph
    builder = AgentGraphBuilder(prompt_service, workflow_service)
    graph = builder.build()

    assert isinstance(graph, CompiledStateGraph)

    initial_state = AgentState(question="Who is the doctor?")
    final_state_dict = await graph.ainvoke(initial_state)

    # Check complete node lifecycle
    assert final_state_dict["current_node"] == "generate_report"
    assert final_state_dict["completed_nodes"] == [
        "analyze_intent",
        "retrieve_context",
        "generate_sql",
        "validate_sql",
        "execute_sql",
        "analyze_results",
        "generate_insights",
        "generate_observations",
        "generate_report",
    ]
    assert final_state_dict["query_result"] == mock_query_result
    assert len(final_state_dict["errors"]) == 0
