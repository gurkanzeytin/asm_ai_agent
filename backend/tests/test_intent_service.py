import asyncio
from datetime import datetime
from pathlib import Path
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from langgraph.graph.state import CompiledStateGraph

from app.agent.graph import AgentGraphBuilder
from app.agent.state import AgentState
from app.application_models.intent import IntentResult, IntentType
from app.application_models.workflow_models import QueryResult
from app.core.config import settings
from app.llm.interfaces import ILLMProvider, LLMResponse
from app.services.interfaces import IPromptService, IWorkflowService
from app.services.help_service import HelpService
from app.services.intent_classifier import IntentClassifier


@pytest.fixture
def temp_keywords_file(tmp_path):
    config_data = {
        "help": {
            "keywords": ["help", "guidance"],
            "base_confidence": 1.0,
            "priority": 1
        },
        "general_chat": {
            "keywords": ["hello", "hi", "who are you"],
            "base_confidence": 1.0,
            "priority": 2
        },
        "database_query": {
            "keywords": ["doctor", "appointment", "patient"],
            "base_confidence": 0.9,
            "priority": 3
        }
    }
    file_path = tmp_path / "intent_keywords.json"
    file_path.write_text(json_encode(config_data), encoding="utf-8")
    return file_path


def json_encode(obj):
    import json
    return json.dumps(obj)


@pytest.fixture
def temp_help_file(tmp_path):
    file_path = tmp_path / "help.md"
    file_path.write_text("### System Help Guidance Information", encoding="utf-8")
    return file_path


@pytest.fixture
def temp_greetings_file(tmp_path):
    file_path = tmp_path / "greetings.md"
    file_path.write_text("Hello there! Welcome.", encoding="utf-8")
    return file_path


def test_intent_classifier_direct_matches(temp_keywords_file):
    classifier = IntentClassifier(config_file_path=temp_keywords_file)

    # 1. HELP match
    res_help = classifier.classify("Please give me some help")
    assert res_help.intent == IntentType.HELP
    assert res_help.confidence == 1.0
    assert "help" in res_help.matched_keywords

    # 2. GENERAL_CHAT match
    res_chat = classifier.classify("Hello to you")
    assert res_chat.intent == IntentType.GENERAL_CHAT
    assert res_chat.confidence == 1.0
    assert "hello" in res_chat.matched_keywords

    # 3. DATABASE_QUERY match
    res_db = classifier.classify("Find a doctor details")
    assert res_db.intent == IntentType.DATABASE_QUERY
    assert res_db.confidence == 0.9
    assert "doctor" in res_db.matched_keywords


def test_intent_classifier_dynamic_confidence(temp_keywords_file):
    classifier = IntentClassifier(config_file_path=temp_keywords_file)

    # Length independent check: matching a single keyword yields base_confidence * 1.0
    res_long = classifier.classify("Could you please search if there is any doctor in the clinic")
    assert res_long.intent == IntentType.DATABASE_QUERY
    assert res_long.confidence == 0.9  # 0.9 base_confidence * min(1.0, 1/1.0) = 0.9
    assert "doctor" in res_long.matched_keywords


def test_intent_classifier_greeting_reason(temp_keywords_file):
    classifier = IntentClassifier(config_file_path=temp_keywords_file)

    res_greeting = classifier.classify("hello there")
    assert res_greeting.intent == IntentType.GENERAL_CHAT
    assert res_greeting.metadata.get("sub_intent") == "greeting"

    res_non_greeting = classifier.classify("who are you")
    assert res_non_greeting.intent == IntentType.GENERAL_CHAT
    assert "sub_intent" not in res_non_greeting.metadata


def test_intent_classifier_caching(temp_keywords_file):
    classifier = IntentClassifier(config_file_path=temp_keywords_file)

    # Force production mode settings to check caching
    with patch.object(settings, "DEBUG", False):
        res1 = classifier.classify("hello")
        res2 = classifier.classify("hello")
        assert res1 == res2
        # Verify lru_cache hits
        info = classifier._classify_cached.cache_info()
        assert info.hits >= 1


def test_help_service_caching_and_reload(temp_help_file):
    # Test with DEBUG = True
    with patch.object(settings, "DEBUG", True):
        service = HelpService(help_file_path=temp_help_file)
        assert service.get_help_markdown() == "### System Help Guidance Information"

        # Update file on disk
        temp_help_file.write_text("### Updated Help Guidance", encoding="utf-8")
        # Should reload instantly
        assert service.get_help_markdown() == "### Updated Help Guidance"

    # Test with DEBUG = False (Caching active)
    with patch.object(settings, "DEBUG", False):
        service_cached = HelpService(help_file_path=temp_help_file)
        assert service_cached.get_help_markdown() == "### Updated Help Guidance"

        # Update file on disk again
        temp_help_file.write_text("### Stale Help Guidance", encoding="utf-8")
        # Should return cached value
        assert service_cached.get_help_markdown() == "### Updated Help Guidance"


@pytest.mark.asyncio
async def test_workflow_routing_database_query(temp_keywords_file):
    from app.database_intelligence.models import DatabaseContext
    from app.application_models.generated_sql import GeneratedSQL
    from app.sql_validator.models import SQLValidationResult
    from app.application_models.generated_report import GeneratedReport

    prompt_service = AsyncMock(spec=IPromptService)
    prompt_service.retrieve_schema_context.return_value = DatabaseContext(tables=[], views=[])
    prompt_service.render_sql_prompt.return_value = "Rendered SQL Prompt"

    workflow_service = AsyncMock(spec=IWorkflowService)
    intent_classifier = IntentClassifier(config_file_path=temp_keywords_file)

    mock_generated_sql = GeneratedSQL(
        sql="SELECT * FROM doctors;",
        normalized_sql="SELECT * FROM doctors",
        validation_result=SQLValidationResult(valid=True),
        provider="ollama",
        model="qwen",
        latency_ms=10.0,
        rendered_prompt="Rendered SQL Prompt",
    )
    workflow_service.execute_sql_generation.return_value = mock_generated_sql

    mock_query = QueryResult(
        columns=["id"], rows=[], row_count=0, execution_time_ms=1.0,
        success=True, executed_at=datetime.now(), database_provider="mssql"
    )
    workflow_service.execute_query.return_value = mock_query

    mock_report = GeneratedReport(
        title="Title",
        markdown="Report text",
        provider="ollama",
        model="qwen",
        latency_ms=10.0,
    )
    workflow_service.execute_report_generation.return_value = mock_report

    builder = AgentGraphBuilder(
        prompt_service=prompt_service,
        workflow_service=workflow_service,
        intent_classifier=intent_classifier,
    )
    graph = builder.build()

    state = AgentState(question="doctor list")
    final_state = await graph.ainvoke(state)

    assert final_state["intent"].intent == IntentType.DATABASE_QUERY
    assert "retrieve_context" in final_state["completed_nodes"]
    assert "generate_report" in final_state["completed_nodes"]
    assert "generate_chat_response" not in final_state["completed_nodes"]


@pytest.mark.asyncio
async def test_workflow_routing_general_chat_greeting(temp_keywords_file, temp_greetings_file):
    prompt_service = AsyncMock(spec=IPromptService)
    workflow_service = AsyncMock(spec=IWorkflowService)
    intent_classifier = IntentClassifier(config_file_path=temp_keywords_file)

    builder = AgentGraphBuilder(
        prompt_service=prompt_service,
        workflow_service=workflow_service,
        intent_classifier=intent_classifier,
    )
    # Patch path inside building block
    with patch("app.agent.nodes.generate_chat_response.GenerateChatResponseNode._get_greeting_text", return_value="Hello there! Welcome."):
        graph = builder.build()
        state = AgentState(question="hello")
        final_state = await graph.ainvoke(state)

        # Greeting bypasses LLM
        assert final_state["intent"].intent == IntentType.GENERAL_CHAT
        assert final_state["intent"].metadata.get("sub_intent") == "greeting"
        assert final_state["generated_report"].markdown == "Hello there! Welcome."
        assert "generate_chat_response" in final_state["completed_nodes"]
        assert "retrieve_context" not in final_state["completed_nodes"]


@pytest.mark.asyncio
async def test_workflow_routing_general_chat_llm(temp_keywords_file):
    prompt_service = AsyncMock(spec=IPromptService)
    workflow_service = AsyncMock(spec=IWorkflowService)
    intent_classifier = IntentClassifier(config_file_path=temp_keywords_file)
    llm_provider = AsyncMock(spec=ILLMProvider)

    # General chat not matching greetings calls LLM
    llm_provider.generate.return_value = LLMResponse(
        content="I am a chatbot model.", model="mock-qwen", latency_ms=10.0
    )
    llm_provider.get_metadata.return_value = {"provider": "mock"}

    builder = AgentGraphBuilder(
        prompt_service=prompt_service,
        workflow_service=workflow_service,
        intent_classifier=intent_classifier,
        llm_provider=llm_provider,
    )
    graph = builder.build()

    state = AgentState(question="who are you")
    final_state = await graph.ainvoke(state)

    assert final_state["intent"].intent == IntentType.GENERAL_CHAT
    assert final_state["generated_report"].markdown == "I am a chatbot model."
    assert "generate_chat_response" in final_state["completed_nodes"]


@pytest.mark.asyncio
async def test_workflow_routing_help(temp_keywords_file, temp_help_file):
    prompt_service = AsyncMock(spec=IPromptService)
    workflow_service = AsyncMock(spec=IWorkflowService)
    intent_classifier = IntentClassifier(config_file_path=temp_keywords_file)
    help_service = HelpService(help_file_path=temp_help_file)

    builder = AgentGraphBuilder(
        prompt_service=prompt_service,
        workflow_service=workflow_service,
        intent_classifier=intent_classifier,
        help_service=help_service,
    )
    graph = builder.build()

    state = AgentState(question="please help me")
    final_state = await graph.ainvoke(state)

    assert final_state["intent"].intent == IntentType.HELP
    assert final_state["generated_report"].markdown == "### System Help Guidance Information"
    assert "generate_help" in final_state["completed_nodes"]
    assert "retrieve_context" not in final_state["completed_nodes"]


@pytest.mark.asyncio
async def test_workflow_routing_unknown_low_confidence(temp_keywords_file):
    from app.database_intelligence.models import DatabaseContext
    from app.application_models.generated_sql import GeneratedSQL
    from app.sql_validator.models import SQLValidationResult
    from app.application_models.generated_report import GeneratedReport

    prompt_service = AsyncMock(spec=IPromptService)
    prompt_service.retrieve_schema_context.return_value = DatabaseContext(tables=[], views=[])
    prompt_service.render_sql_prompt.return_value = "Rendered SQL Prompt"

    workflow_service = AsyncMock(spec=IWorkflowService)
    intent_classifier = IntentClassifier(config_file_path=temp_keywords_file)

    mock_generated_sql = GeneratedSQL(
        sql="SELECT * FROM patients;",
        normalized_sql="SELECT * FROM patients",
        validation_result=SQLValidationResult(valid=True),
        provider="ollama",
        model="qwen",
        latency_ms=10.0,
        rendered_prompt="Rendered SQL Prompt",
    )
    workflow_service.execute_sql_generation.return_value = mock_generated_sql

    mock_query = QueryResult(
        columns=["id"], rows=[], row_count=0, execution_time_ms=1.0,
        success=True, executed_at=datetime.now(), database_provider="mssql"
    )
    workflow_service.execute_query.return_value = mock_query

    mock_report = GeneratedReport(
        title="Title",
        markdown="Report text",
        provider="ollama",
        model="qwen",
        latency_ms=10.0,
    )
    workflow_service.execute_report_generation.return_value = mock_report

    builder = AgentGraphBuilder(
        prompt_service=prompt_service,
        workflow_service=workflow_service,
        intent_classifier=intent_classifier,
    )
    graph = builder.build()

    # Query matching no intent keywords (low confidence UNKNOWN) but carrying
    # a domain entity ("randevu") so the answerability guard keeps it on SQL.
    state = AgentState(question="Dün kaç randevu oldu?")
    final_state = await graph.ainvoke(state)

    # UNKNOWN with confidence 0.0 -> routes to database_query workflow!
    assert final_state["intent"].intent == IntentType.UNKNOWN
    assert final_state["intent"].confidence == 0.0
    assert "retrieve_context" in final_state["completed_nodes"]
    assert "generate_report" in final_state["completed_nodes"]


@pytest.mark.asyncio
async def test_workflow_routing_unknown_high_confidence(temp_keywords_file):
    prompt_service = AsyncMock(spec=IPromptService)
    workflow_service = AsyncMock(spec=IWorkflowService)
    intent_classifier = IntentClassifier(config_file_path=temp_keywords_file)

    builder = AgentGraphBuilder(
        prompt_service=prompt_service,
        workflow_service=workflow_service,
        intent_classifier=intent_classifier,
    )
    graph = builder.build()

    # Empty question (high confidence UNKNOWN)
    state = AgentState(question="   ")
    final_state = await graph.ainvoke(state)

    # UNKNOWN with confidence 1.0 -> routes to generate_clarification!
    assert final_state["intent"].intent == IntentType.UNKNOWN
    assert final_state["intent"].confidence == 1.0
    assert "generate_clarification" in final_state["completed_nodes"]
    assert "retrieve_context" not in final_state["completed_nodes"]
