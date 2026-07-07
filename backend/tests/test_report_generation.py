from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from langgraph.graph.state import CompiledStateGraph

from app.agent.graph import AgentGraphBuilder
from app.agent.nodes.generate_report import GenerateReportNode
from app.agent.state import AgentState
from app.application_models.generated_report import GeneratedReport, ReportPromptContext
from app.application_models.generated_sql import GeneratedSQL
from app.application_models.workflow_models import QueryResult
from app.core.config import settings
from app.llm.interfaces import ILLMProvider
from app.llm.schemas import LLMResponse
from app.database_intelligence.models import DatabaseContext
from app.services.interfaces import IPromptService, IWorkflowService
from app.services.prompt_service import PromptService
from app.services.report_generator import IReportGenerator
from app.services.report_service import ReportService
from app.sql_validator import SQLValidationResult


@pytest.mark.asyncio
async def test_prompt_service_render_report_prompt_truncation():
    # Setup mocks
    schema_cache = MagicMock()
    schema_retriever = MagicMock()
    prompt_loader = MagicMock()
    prompt_renderer = MagicMock()

    prompt_loader.get_prompt.side_effect = lambda name: (
        "System Template" if name == "system_prompt.md" else "Report Template {query} {results}"
    )
    prompt_renderer.render.side_effect = lambda template, vars: template.format(**vars)

    prompt_service = PromptService(
        schema_cache=schema_cache,
        schema_retriever=schema_retriever,
        prompt_loader=prompt_loader,
        prompt_renderer=prompt_renderer,
    )

    # Test rendering within limit
    rows = [{"id": i} for i in range(10)]
    query_result = QueryResult(
        columns=["id"],
        rows=rows,
        row_count=10,
        execution_time_ms=1.5,
        success=True,
        executed_at=datetime.now(),
        database_provider="sqlite",
    )

    # Backup and set max rows config
    original_max = getattr(settings, "REPORT_MAX_ROWS", 100)
    settings.REPORT_MAX_ROWS = 5

    try:
        rendered = await prompt_service.render_report_prompt(
            question="What is the count?", sql="SELECT * FROM table", query_result=query_result
        )

        assert "System Template" in rendered
        assert "Report Template" in rendered
        assert "SELECT * FROM table" in rendered
        # Assert serialization happened and truncation applied (only 5 rows in results)
        assert '"original_row_count": 10' in rendered
        assert '"truncated_row_count": 5' in rendered
        assert '"rows":' in rendered
    finally:
        settings.REPORT_MAX_ROWS = original_max


@pytest.mark.asyncio
async def test_report_service_generate_report_metadata():
    # Setup mocks
    prompt_service = AsyncMock(spec=IPromptService)
    prompt_service.render_report_prompt.return_value = "Rendered Prompt"

    llm_provider = AsyncMock(spec=ILLMProvider)
    llm_provider.get_metadata.return_value = {"provider": "mock-ollama"}

    llm_response = LLMResponse(
        content="# Test Report Title\n\nExecutive Summary content.",
        model="qwen3:8b",
        latency_ms=120.5,
        prompt_tokens=50,
        completion_tokens=100,
    )

    # Custom strategy mock
    strategy = AsyncMock(spec=IReportGenerator)
    strategy.generate.return_value = llm_response

    report_service = ReportService(
        prompt_service=prompt_service, llm_provider=llm_provider, generator=strategy
    )

    query_result = QueryResult(
        columns=["id"],
        rows=[],
        row_count=0,
        execution_time_ms=1.0,
        success=True,
        executed_at=datetime.now(),
        database_provider="sqlite",
    )

    report = await report_service.generate_report(
        question="Select all", sql="SELECT 1", query_result=query_result, execution_id="exec-123"
    )

    assert isinstance(report, GeneratedReport)
    assert report.title == "Test Report Title"
    assert report.markdown == llm_response.content
    assert report.provider == "mock-ollama"
    assert report.model == "qwen3:8b"
    assert report.latency_ms == 120.5
    assert report.prompt_tokens == 50
    assert report.completion_tokens == 100
    assert report.execution_id == "exec-123"
    assert report.generated_at is not None
    strategy.generate.assert_called_once_with("Rendered Prompt", llm_provider)


@pytest.mark.asyncio
async def test_generate_report_node_execute():
    workflow_service = AsyncMock(spec=IWorkflowService)
    node = GenerateReportNode(workflow_service)

    # 1. Test skip execution on errors
    state_with_errors = AgentState(question="Select count", errors=["Existing error"])
    output_state = await node.execute(state_with_errors)
    assert output_state is not state_with_errors
    assert output_state.current_node == "generate_report"
    assert "generate_report" not in output_state.completed_nodes

    # 2. Test missing query result
    state_no_result = AgentState(question="Select count")
    output_state = await node.execute(state_no_result)
    assert len(output_state.errors) == 1
    assert "SQL query result is missing" in output_state.errors[0]

    # 3. Test missing generated SQL DTO
    query_result = QueryResult(
        columns=["id"],
        rows=[],
        row_count=0,
        execution_time_ms=1.0,
        success=True,
        executed_at=datetime.now(),
        database_provider="sqlite",
    )
    state_no_sql = AgentState(question="Select count", query_result=query_result)
    output_state = await node.execute(state_no_sql)
    assert len(output_state.errors) == 1
    assert "Generated SQL statement is missing" in output_state.errors[0]

    # 4. Test successful report node execution
    generated_sql = GeneratedSQL(
        sql="SELECT 1",
        validation_result=SQLValidationResult(valid=True),
        provider="ollama",
        model="qwen",
        latency_ms=10.0,
    )
    state_valid = AgentState(
        question="Select count",
        query_result=query_result,
        generated_sql=generated_sql,
        workflow_id="exec-456",
    )

    mock_report = GeneratedReport(
        title="Valid Report",
        markdown="# Valid Report\nSummary text",
        provider="ollama",
        model="qwen",
        latency_ms=15.0,
        generated_at=datetime.now(),
        execution_id="exec-456",
    )
    workflow_service.execute_report_generation.return_value = mock_report

    output_state = await node.execute(state_valid)
    assert output_state is not state_valid
    assert output_state.generated_report == mock_report
    assert output_state.current_node == "generate_report"
    assert "generate_report" in output_state.completed_nodes
    assert output_state.duration_ms > 0.0


@pytest.mark.asyncio
async def test_full_graph_execution_with_report():
    prompt_service = AsyncMock(spec=IPromptService)
    workflow_service = AsyncMock(spec=IWorkflowService)

    prompt_service.retrieve_schema_context.return_value = DatabaseContext(tables=[], views=[])
    prompt_service.render_sql_prompt.return_value = "Rendered SQL Prompt"

    mock_generated_sql = GeneratedSQL(
        sql="SELECT * FROM doctors;",
        normalized_sql="SELECT * FROM doctors",
        validation_result=SQLValidationResult(
            valid=True,
            normalized_sql="SELECT * FROM doctors",
            statement_type="Select",
        ),
        provider="ollama",
        model="qwen3:8b",
        latency_ms=80.0,
    )
    workflow_service.execute_sql_generation.return_value = mock_generated_sql

    mock_query_result = QueryResult(
        columns=["id", "name"],
        rows=[{"id": 1, "name": "Dr. Smith"}],
        row_count=1,
        execution_time_ms=4.5,
        success=True,
        executed_at=datetime.now(),
        database_provider="sqlite",
    )
    workflow_service.execute_query.return_value = mock_query_result

    mock_report = GeneratedReport(
        title="Highest Number of Appointments Report",
        markdown="# Highest Number of Appointments Report\n\nExecutive Summary details here.",
        provider="ollama",
        model="qwen3:8b",
        latency_ms=250.0,
        generated_at=datetime.now(),
        execution_id="exec-789",
    )
    workflow_service.execute_report_generation.return_value = mock_report

    builder = AgentGraphBuilder(prompt_service, workflow_service)
    graph = builder.build()
    assert isinstance(graph, CompiledStateGraph)

    initial_state = AgentState(question="Which doctor has the highest number of appointments?", workflow_id="exec-789")
    final_state_dict = await graph.ainvoke(initial_state)

    assert final_state_dict["generated_report"] == mock_report
    assert final_state_dict["current_node"] == "generate_report"
    assert "retrieve_context" in final_state_dict["completed_nodes"]
    assert "generate_sql" in final_state_dict["completed_nodes"]
    assert "validate_sql" in final_state_dict["completed_nodes"]
    assert "execute_sql" in final_state_dict["completed_nodes"]
    assert "generate_report" in final_state_dict["completed_nodes"]
    assert len(final_state_dict["errors"]) == 0


@pytest.mark.asyncio
async def test_report_generation_values_originating_from_query_result():
    import json
    import re

    # Define dynamic mock strategy matching mock LLM behavior
    class TestDynamicMockReportGenerator(IReportGenerator):
        async def generate(self, prompt: str, llm_provider: ILLMProvider) -> LLMResponse:
            rows = []
            json_match = re.search(r"\{.*\}", prompt, re.DOTALL)
            if json_match:
                try:
                    data = json.loads(json_match.group(0))
                    rows = data.get("rows", [])
                except Exception:
                    pass

            doctor_name = "Bilinmeyen Doktor"
            appointments = 0
            if rows:
                row = rows[0]
                doctor_name = row.get("ad_soyad", row.get("name", "Bilinmeyen Doktor"))
                appointments = row.get("randevu_sayisi", row.get("id", 0))

            markdown = f"# Rapor\nName: {doctor_name}\nCount: {appointments}"
            return LLMResponse(
                content=markdown,
                model="mock-qwen3:8b",
                latency_ms=100.0,
            )

    # Setup prompt service and mock renderer
    prompt_service = PromptService(
        schema_cache=MagicMock(),
        schema_retriever=MagicMock(),
        prompt_loader=MagicMock(),
        prompt_renderer=MagicMock(),
    )
    prompt_service.prompt_loader.get_prompt.side_effect = lambda name: (
        "System template" if name == "system_prompt.md" else "{results}"
    )
    prompt_service.prompt_renderer.render.side_effect = lambda template, vars: template.format(**vars)

    llm_provider = AsyncMock(spec=ILLMProvider)
    llm_provider.get_metadata.return_value = {"provider": "mock-ollama"}

    dynamic_mock_generator = TestDynamicMockReportGenerator()
    report_service = ReportService(
        prompt_service=prompt_service,
        llm_provider=llm_provider,
        generator=dynamic_mock_generator,
    )

    query_result = QueryResult(
        columns=["ad_soyad", "randevu_sayisi"],
        rows=[{"ad_soyad": "Dr. Mehmet Öz", "randevu_sayisi": 999}],
        row_count=1,
        execution_time_ms=10.0,
        success=True,
        executed_at=datetime.now(),
        database_provider="sqlite",
    )

    report = await report_service.generate_report(
        question="Which doctor has the highest number of appointments?",
        sql="SELECT * FROM doktorlar",
        query_result=query_result,
        execution_id="test-exec-id"
    )

    # Assertions
    assert isinstance(report, GeneratedReport)
    assert "Dr. Mehmet Öz" in report.markdown
    assert "999" in report.markdown

