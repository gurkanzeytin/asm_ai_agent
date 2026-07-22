from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.application_models import GeneratedReport, GeneratedSQL
from app.application_models.workflow_models import QueryResult
from app.database_intelligence.cache import SchemaCache
from app.database_intelligence.interfaces import ISchemaRetriever
from app.database_intelligence.models import (
    ColumnMetadata,
    DatabaseContext,
    DatabaseSchema,
    ForeignKeyMetadata,
    TableMetadata,
)
from app.llm.interfaces import ILLMProvider
from app.llm.schemas import LLMResponse
from app.parsers import IOutputParser, OutputParser
from app.prompts.loader import PromptLoader
from app.prompts.renderer import IPromptRenderer
from app.services import (
    PromptService,
    PromptServiceException,
    ReportService,
    ReportServiceException,
    SQLService,
    SQLServiceException,
    WorkflowService,
    WorkflowServiceException,
)
from app.sql_validator import ISQLValidator, SQLValidationResult


def test_constructor_dependency_injection():
    # Verify we can inject mock dependencies into services successfully
    schema_cache = MagicMock(spec=SchemaCache)
    schema_retriever = MagicMock(spec=ISchemaRetriever)
    prompt_loader = MagicMock(spec=PromptLoader)
    prompt_renderer = MagicMock(spec=IPromptRenderer)
    llm_provider = MagicMock(spec=ILLMProvider)
    output_parser = MagicMock(spec=IOutputParser)
    sql_validator = MagicMock(spec=ISQLValidator)

    p_service = PromptService(schema_cache, schema_retriever, prompt_loader, prompt_renderer)
    assert p_service.schema_cache == schema_cache

    sql_service = SQLService(llm_provider, output_parser, sql_validator)
    assert sql_service.llm_provider == llm_provider

    r_service = ReportService(p_service, llm_provider)
    assert r_service.prompt_service == p_service

    w_service = WorkflowService(p_service, sql_service, r_service)
    assert w_service.prompt_service == p_service


def test_output_parser():
    parser = OutputParser()

    # Markdown block SQL extraction
    res1 = parser.parse_sql("```sql\nSELECT * FROM users;\n```")
    assert res1 == "SELECT * FROM users;"

    # Markdown block SQL with case variation
    res2 = parser.parse_sql("```SQL\nSELECT 1;\n```")
    assert res2 == "SELECT 1;"

    # Plain text extraction
    res3 = parser.parse_sql("SELECT * FROM log")
    assert res3 == "SELECT * FROM log"

    # Quotes extraction
    res4 = parser.parse_sql('"SELECT 2"')
    assert res4 == "SELECT 2"


@pytest.mark.asyncio
async def test_prompt_service_context_formatting():
    # Setup mocks
    schema_cache = AsyncMock(spec=SchemaCache)
    schema_retriever = MagicMock(spec=ISchemaRetriever)
    prompt_loader = MagicMock(spec=PromptLoader)
    prompt_renderer = MagicMock(spec=IPromptRenderer)

    schema_cache.get_schema.return_value = MagicMock(spec=DatabaseSchema)
    prompt_loader.get_prompt.return_value = "Parameters:\n{schema}\nQuestion:\n{question}"
    prompt_renderer.render.side_effect = lambda template, vars: template.format(**vars)

    # Mock DatabaseContext data
    mock_table = TableMetadata(
        name="users",
        comment="System users",
        columns=[
            ColumnMetadata(
                name="id",
                type_name="INTEGER",
                primary_key=True,
                nullable=False,
                default=None,
                comment=None,
            ),
            ColumnMetadata(
                name="role_id",
                type_name="INTEGER",
                primary_key=False,
                nullable=True,
                default=None,
                comment="User role reference",
            ),
        ],
        foreign_keys=[
            ForeignKeyMetadata(
                constrained_columns=["role_id"],
                referred_table="roles",
                referred_columns=["id"],
            )
        ],
        primary_keys=["id"],
        indexes=[],
    )
    mock_context = DatabaseContext(tables=[mock_table], views=[])
    schema_retriever.retrieve_context.return_value = mock_context

    p_service = PromptService(schema_cache, schema_retriever, prompt_loader, prompt_renderer)

    rendered = await p_service.render_prompt("sql_generation.md", "Who are the admins?", {})

    assert "Table: users" in rendered
    assert "Columns: id (INTEGER) [PK], role_id (INTEGER)" in rendered
    assert "Foreign Keys: (role_id)->roles(id)" in rendered


@pytest.mark.asyncio
async def test_prompt_service_render_failures():
    schema_cache = AsyncMock(spec=SchemaCache)
    schema_retriever = MagicMock(spec=ISchemaRetriever)
    prompt_loader = MagicMock(spec=PromptLoader)
    prompt_renderer = MagicMock(spec=IPromptRenderer)

    prompt_loader.get_prompt.side_effect = Exception("File missing")

    p_service = PromptService(schema_cache, schema_retriever, prompt_loader, prompt_renderer)

    with pytest.raises(PromptServiceException):
        await p_service.render_prompt("nonexistent.md", "query", {})


@pytest.mark.asyncio
async def test_sql_service_orchestration():
    llm_provider = AsyncMock(spec=ILLMProvider)
    output_parser = MagicMock(spec=IOutputParser)
    sql_validator = MagicMock(spec=ISQLValidator)

    llm_provider.generate.return_value = LLMResponse(
        content="```sql\nSELECT * FROM users;\n```",
        model="qwen3:8b",
        latency_ms=120.0,
        prompt_tokens=15,
        completion_tokens=20,
    )
    llm_provider.get_metadata.return_value = {"provider": "ollama"}
    output_parser.parse_sql.return_value = "SELECT * FROM users;"
    sql_validator.validate.return_value = SQLValidationResult(
        valid=True,
        normalized_sql="SELECT * FROM users",
        statement_type="Select",
    )

    sql_service = SQLService(llm_provider, output_parser, sql_validator)

    res = await sql_service.generate_sql("Prompt context")

    assert isinstance(res, GeneratedSQL)
    assert res.sql == "SELECT * FROM users;"
    assert res.normalized_sql == "SELECT * FROM users"
    assert res.validation_result.valid is True
    assert res.provider == "ollama"
    assert res.model == "qwen3:8b"
    assert res.latency_ms == 120.0
    llm_provider.generate.assert_called_once_with("Prompt context", think=False, options={"num_predict": 400})


@pytest.mark.asyncio
async def test_sql_service_failures():
    llm_provider = AsyncMock(spec=ILLMProvider)
    output_parser = MagicMock(spec=IOutputParser)
    sql_validator = MagicMock(spec=ISQLValidator)

    llm_provider.generate.side_effect = Exception("Timeout calling Ollama")

    sql_service = SQLService(llm_provider, output_parser, sql_validator)

    with pytest.raises(SQLServiceException):
        await sql_service.generate_sql("Prompt context")


@pytest.mark.asyncio
async def test_report_service_orchestration():
    prompt_service = AsyncMock(spec=PromptService)
    llm_provider = AsyncMock(spec=ILLMProvider)

    prompt_service.render_report_prompt.return_value = "Rendered prompt text"
    llm_provider.get_metadata.return_value = {"provider": "mock-provider"}
    llm_provider.generate.return_value = LLMResponse(
        content="# Kullanıcı Raporu\nBu, yönetici anlatı özetidir.",
        model="qwen3:8b",
        latency_ms=250.0,
    )

    r_service = ReportService(prompt_service, llm_provider)
    rows = [{"id": i} for i in range(21)]
    query_result = QueryResult(
        columns=["id"],
        rows=rows,
        row_count=len(rows),
        execution_time_ms=1.0,
        success=True,
        executed_at=datetime.now(),
        database_provider="mssql",
    )

    res = await r_service.generate_report(
        "Analyze user trends",
        "SELECT role, COUNT(*) AS user_count FROM users GROUP BY role",
        query_result,
    )

    assert isinstance(res, GeneratedReport)
    assert res.title == "Kullanıcı Raporu"
    assert "Bu, yönetici anlatı özetidir." in res.markdown


@pytest.mark.asyncio
async def test_report_service_failures():
    prompt_service = AsyncMock(spec=PromptService)
    llm_provider = AsyncMock(spec=ILLMProvider)

    prompt_service.render_report_prompt.side_effect = Exception("Rendering error")

    r_service = ReportService(prompt_service, llm_provider)
    rows = [{"id": i} for i in range(21)]
    query_result = QueryResult(
        columns=["id"],
        rows=rows,
        row_count=len(rows),
        execution_time_ms=1.0,
        success=True,
        executed_at=datetime.now(),
        database_provider="mssql",
    )

    with pytest.raises(ReportServiceException):
        await r_service.generate_report(
            "Analyze user trends",
            "SELECT role, COUNT(*) AS user_count FROM users GROUP BY role",
            query_result,
        )


@pytest.mark.asyncio
async def test_workflow_service_orchestration():
    prompt_service = AsyncMock(spec=PromptService)
    sql_service = AsyncMock(spec=SQLService)
    report_service = AsyncMock(spec=ReportService)

    prompt_service.render_sql_prompt.return_value = "Rendered prompt context"
    sql_service.generate_sql.return_value = GeneratedSQL(
        sql="SELECT 1",
        normalized_sql="SELECT 1",
        validation_result=None,
        provider="ollama",
        model="qwen",
        latency_ms=10.0,
    )
    report_service.generate_report.return_value = GeneratedReport(
        title="Title",
        markdown="MD",
    )

    w_service = WorkflowService(prompt_service, sql_service, report_service)

    sql_dto = await w_service.execute_sql_generation("Test question")
    assert sql_dto.sql == "SELECT 1"
    assert sql_dto.rendered_prompt == "Rendered prompt context"

    report_dto = await w_service.execute_report_generation("Test question", "SELECT 1", [])
    assert report_dto.markdown == "MD"


@pytest.mark.asyncio
async def test_workflow_service_failures():
    prompt_service = AsyncMock(spec=PromptService)
    sql_service = AsyncMock(spec=SQLService)
    report_service = AsyncMock(spec=ReportService)

    prompt_service.render_sql_prompt.side_effect = Exception("Prompt error")

    w_service = WorkflowService(prompt_service, sql_service, report_service)

    with pytest.raises(WorkflowServiceException):
        await w_service.execute_sql_generation("Test question")


def test_sql_parser_extraction_cases():
    parser = OutputParser()

    # Case 1: Plain SQL output
    case1 = "SELECT name FROM doctors;"
    assert parser.parse_sql(case1) == "SELECT name FROM doctors;"

    # Case 2: Markdown code fences
    case2 = "```sql\nSELECT name FROM doctors;\n```"
    assert parser.parse_sql(case2) == "SELECT name FROM doctors;"

    # Case 2b: Code fences without sql identifier
    case2b = "```\nSELECT name FROM doctors;\n```"
    assert parser.parse_sql(case2b) == "SELECT name FROM doctors;"

    # Case 3: Conversational wrappers (preceding and concluding text)
    case3 = "Sure, here is the query: SELECT name FROM doctors; Hope this helps!"
    assert parser.parse_sql(case3) == "SELECT name FROM doctors;"

    # Case 3b: Text with CTE (WITH)
    case3b = "Let's write a CTE:\nWITH doctors_cte AS (SELECT * FROM doctors) SELECT * FROM doctors_cte;\nThis solves it."
    assert parser.parse_sql(case3b) == "WITH doctors_cte AS (SELECT * FROM doctors) SELECT * FROM doctors_cte;"


@pytest.mark.asyncio
async def test_sql_service_repair_success():
    llm_provider = AsyncMock(spec=ILLMProvider)
    output_parser = OutputParser()
    sql_validator = MagicMock(spec=ISQLValidator)

    # First attempt: returns bad conversational text with no SQL
    # Second attempt: returns correct SQL query
    llm_provider.generate.side_effect = [
        LLMResponse(
            content="I cannot help directly without more query instructions.",
            model="qwen3:8b",
            latency_ms=100.0,
            prompt_tokens=10,
            completion_tokens=20,
        ),
        LLMResponse(
            content="SELECT * FROM patients;",
            model="qwen3:8b",
            latency_ms=120.0,
            prompt_tokens=40,
            completion_tokens=10,
        )
    ]
    llm_provider.get_metadata.return_value = {"provider": "ollama"}
    sql_validator.validate.return_value = SQLValidationResult(
        valid=True,
        normalized_sql="SELECT * FROM patients",
        statement_type="Select",
    )

    sql_service = SQLService(llm_provider, output_parser, sql_validator)

    res = await sql_service.generate_sql("Prompt context")

    # Verify success after exactly one repair attempt
    assert res.sql == "SELECT * FROM patients;"
    assert llm_provider.generate.call_count == 2

    # Verify the repair prompt contains the original prompt, previous response, and instruction
    first_call_args = llm_provider.generate.call_args_list[0]
    second_call_args = llm_provider.generate.call_args_list[1]

    assert first_call_args[0][0] == "Prompt context"
    assert "--- Previous response ---" in second_call_args[0][0]
    assert "I cannot help directly" in second_call_args[0][0]
    assert "The previous response was not valid SQL." in second_call_args[0][0]


@pytest.mark.asyncio
async def test_sql_service_non_sql_failure():
    llm_provider = AsyncMock(spec=ILLMProvider)
    output_parser = OutputParser()
    sql_validator = MagicMock(spec=ISQLValidator)

    # Both attempts return non-SQL text
    llm_provider.generate.return_value = LLMResponse(
        content="This is conversational text explaining doctors.",
        model="qwen3:8b",
        latency_ms=100.0,
        prompt_tokens=10,
        completion_tokens=20,
    )
    llm_provider.get_metadata.return_value = {"provider": "ollama"}

    sql_service = SQLService(llm_provider, output_parser, sql_validator)

    # Should raise SQLServiceException immediately before any sql_validator calls
    with pytest.raises(SQLServiceException) as exc_info:
        await sql_service.generate_sql("Prompt context")

    assert "does not start with SELECT or WITH" in str(exc_info.value)
    sql_validator.validate.assert_not_called()
    assert llm_provider.generate.call_count == 2


