from unittest.mock import AsyncMock, MagicMock

import pytest
from langgraph.graph.state import CompiledStateGraph

from app.agent.graph import AgentGraphBuilder
from app.agent.nodes.generate_sql import GenerateSQLNode
from app.agent.nodes.retrieve_context import RetrieveContextNode
from app.agent.nodes.validate_sql import ValidateSQLNode
from app.agent.state import AgentState
from app.application_models.generated_sql import GeneratedSQL
from app.database_intelligence.models import DatabaseContext
from app.services import IPromptService, IWorkflowService
from app.sql_validator import SQLValidationResult


def test_agent_state_typed_fields_and_metadata():
    # Verify that AgentState has the required Pydantic configuration, fields, and metadata tracing fields
    state = AgentState(question="List users", workflow_id="wf-123", started_at="2026-07-07T12:00:00Z")
    assert state.question == "List users"
    assert state.database_context is None
    assert state.sql_prompt is None
    assert state.generated_sql is None
    assert isinstance(state.errors, list)
    
    # Metadata fields
    assert state.workflow_id == "wf-123"
    assert state.started_at == "2026-07-07T12:00:00Z"
    assert state.current_node is None
    assert state.completed_nodes == []
    assert state.duration_ms == 0.0


def test_graph_builder_compilation():
    # Setup mocks
    prompt_service = MagicMock(spec=IPromptService)
    workflow_service = MagicMock(spec=IWorkflowService)

    # Use builder class
    builder = AgentGraphBuilder(prompt_service, workflow_service)
    graph = builder.build()
    assert isinstance(graph, CompiledStateGraph)


@pytest.mark.asyncio
async def test_successful_workflow_execution():
    # Setup dependencies
    prompt_service = AsyncMock(spec=IPromptService)
    workflow_service = AsyncMock(spec=IWorkflowService)

    # Mock outputs
    mock_context = DatabaseContext(tables=[], views=[])
    prompt_service.retrieve_schema_context.return_value = mock_context
    prompt_service.render_sql_prompt.return_value = "Rendered prompt text"
    
    mock_generated_sql = GeneratedSQL(
        sql="SELECT * FROM users;",
        normalized_sql="SELECT * FROM users",
        validation_result=SQLValidationResult(
            valid=True,
            normalized_sql="SELECT * FROM users",
            statement_type="Select",
        ),
        provider="ollama",
        model="qwen3:8b",
        latency_ms=100.0,
        rendered_prompt="Rendered prompt text",
    )
    workflow_service.execute_sql_generation.return_value = mock_generated_sql
    from datetime import datetime
    from app.application_models.workflow_models import QueryResult
    mock_query = QueryResult(
        columns=["id"],
        rows=[],
        row_count=0,
        execution_time_ms=5.0,
        success=True,
        executed_at=datetime.now(),
        database_provider="sqlite"
    )
    workflow_service.execute_query.return_value = mock_query

    from app.application_models.generated_report import GeneratedReport
    mock_report = GeneratedReport(
        title="Title",
        markdown="Report text",
        provider="ollama",
        model="qwen3:8b",
        latency_ms=250.0,
    )
    workflow_service.execute_report_generation.return_value = mock_report

    # Build and compile graph
    builder = AgentGraphBuilder(prompt_service, workflow_service)
    graph = builder.build()

    # Run graph execution
    # Must carry a domain signal ("patients") so the AG-022 answerability
    # guard keeps it on the SQL pipeline.
    initial_state = AgentState(question="List all active patients")
    final_state_dict = await graph.ainvoke(initial_state)

    # Check state updates
    assert final_state_dict["database_context"] == mock_context
    assert final_state_dict["sql_prompt"] == "Rendered prompt text"
    assert final_state_dict["generated_sql"] == mock_generated_sql
    assert len(final_state_dict["errors"]) == 0
    assert final_state_dict["current_node"] == "generate_report"
    assert "retrieve_context" in final_state_dict["completed_nodes"]
    assert "generate_sql" in final_state_dict["completed_nodes"]
    assert "validate_sql" in final_state_dict["completed_nodes"]
    assert "execute_sql" in final_state_dict["completed_nodes"]
    assert "generate_report" in final_state_dict["completed_nodes"]
    assert final_state_dict["duration_ms"] > 0.0
    
    # Verify node_timings are tracked
    assert "retrieve_context" in final_state_dict["node_timings"]
    assert "generate_sql" in final_state_dict["node_timings"]
    assert "validate_sql" in final_state_dict["node_timings"]
    assert "execute_sql" in final_state_dict["node_timings"]
    assert "generate_report" in final_state_dict["node_timings"]


@pytest.mark.asyncio
async def test_workflow_validation_failure():
    # Setup dependencies
    prompt_service = AsyncMock(spec=IPromptService)
    workflow_service = AsyncMock(spec=IWorkflowService)

    # Mock outputs with failed safety check validation
    prompt_service.retrieve_schema_context.return_value = DatabaseContext(tables=[], views=[])
    prompt_service.render_sql_prompt.return_value = "Rendered prompt"
    
    mock_invalid_sql = GeneratedSQL(
        sql="DELETE FROM users;",
        validation_result=SQLValidationResult(
            valid=False,
            reason="Unsafe command 'Delete' detected.",
        ),
        provider="ollama",
        model="qwen3:8b",
        latency_ms=80.0,
        rendered_prompt="Rendered prompt text",
    )
    workflow_service.execute_sql_generation.return_value = mock_invalid_sql

    # Build and compile graph
    builder = AgentGraphBuilder(prompt_service, workflow_service)
    graph = builder.build()

    # Run graph execution
    initial_state = AgentState(question="Delete all patients")
    final_state_dict = await graph.ainvoke(initial_state)

    assert len(final_state_dict["errors"]) > 0
    assert "SQL Safety validation failed" in final_state_dict["errors"][0]
    assert final_state_dict["generated_sql"] == mock_invalid_sql
    assert final_state_dict["current_node"] == "generate_report"
    assert "validate_sql" not in final_state_dict["completed_nodes"]
    assert "execute_sql" not in final_state_dict["completed_nodes"]
    assert "generate_report" not in final_state_dict["completed_nodes"]


@pytest.mark.asyncio
async def test_state_immutability():
    # Verify that nodes return a copied/updated state instance instead of mutating shared state
    prompt_service = AsyncMock(spec=IPromptService)
    mock_context = DatabaseContext(tables=[], views=[])
    prompt_service.retrieve_schema_context.return_value = mock_context

    node = RetrieveContextNode(prompt_service)
    state = AgentState(question="Find users")

    updated_state = await node.execute(state)

    # The returned state must be a separate instance
    assert updated_state is not state
    assert updated_state.database_context == mock_context
    # The original state must remain unchanged
    assert state.database_context is None


@pytest.mark.asyncio
async def test_node_execution_order_tracing():
    execution_order = []

    # Custom node wrappers to trace execution
    class TraceRetrieveNode(RetrieveContextNode):
        async def execute(self, state: AgentState) -> AgentState:
            execution_order.append("retrieve")
            return await super().execute(state)

    class TraceGenerateNode(GenerateSQLNode):
        async def execute(self, state: AgentState) -> AgentState:
            execution_order.append("generate")
            return await super().execute(state)

    class TraceValidateNode(ValidateSQLNode):
        async def execute(self, state: AgentState) -> AgentState:
            execution_order.append("validate")
            return await super().execute(state)

    # Setup dependencies
    prompt_service = AsyncMock(spec=IPromptService)
    workflow_service = AsyncMock(spec=IWorkflowService)

    prompt_service.retrieve_schema_context.return_value = DatabaseContext(tables=[], views=[])
    prompt_service.render_sql_prompt.return_value = "Prompt"
    workflow_service.execute_sql_generation.return_value = GeneratedSQL(
        sql="SELECT 1",
        validation_result=SQLValidationResult(valid=True),
        provider="ollama",
        model="qwen",
        latency_ms=10.0,
        rendered_prompt="Prompt",
    )

    retrieve_node = TraceRetrieveNode(prompt_service)
    generate_node = TraceGenerateNode(workflow_service)
    validate_node = TraceValidateNode()

    # Compile custom traced graph
    from langgraph.graph import END, START, StateGraph
    workflow = StateGraph(AgentState)
    workflow.add_node("retrieve_context", retrieve_node.execute)
    workflow.add_node("generate_sql", generate_node.execute)
    workflow.add_node("validate_sql", validate_node.execute)
    workflow.add_edge(START, "retrieve_context")
    workflow.add_edge("retrieve_context", "generate_sql")
    workflow.add_edge("generate_sql", "validate_sql")
    workflow.add_edge("validate_sql", END)
    graph = workflow.compile()

    initial_state = AgentState(question="Trace run")
    await graph.ainvoke(initial_state)

    assert execution_order == ["retrieve", "generate", "validate"]
