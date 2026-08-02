from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agent.nodes.analyze_intent import AnalyzeIntentNode
from app.agent.nodes.retrieve_context import RetrieveContextNode
from app.agent.state import AgentState
from app.application_models.intent import IntentResult, IntentType
from app.application_models.schema_reasoning import SchemaReasoningDecision
from app.database_intelligence.models import DatabaseContext, ViewMetadata
from app.llm.interfaces import ILLMProvider
from app.llm.schemas import LLMResponse
from app.semantics.schema_knowledge import load_schema_knowledge
from app.services.interfaces import IIntentClassifier, IPromptService
from app.services.schema_answerability import SchemaAnswerabilityService


def _response(content: str) -> LLMResponse:
    return LLMResponse(content=content, model="fake", latency_ms=1.0)


def _provider(content: str):
    provider = AsyncMock(spec=ILLMProvider)
    provider.generate.return_value = _response(content)
    return provider


def _classifier():
    classifier = MagicMock(spec=IIntentClassifier)
    classifier.classify.return_value = IntentResult(
        intent=IntentType.UNKNOWN,
        confidence=0.0,
        reason="no_keywords_matched",
        matched_keywords=[],
        metadata={},
    )
    return classifier


def test_schema_knowledge_composes_every_column_metric_and_value_policy():
    knowledge = load_schema_knowledge()
    columns = {column.name: column for column in knowledge.columns}

    assert len(knowledge.columns) == 24
    assert len(knowledge.metrics) == 48
    assert len(knowledge.relationships) >= 20
    assert columns["RandevuDurumu"].value_grounding == "verified"
    assert "Gelmedi" in columns["RandevuDurumu"].known_values
    assert columns["ProtokolIslemState"].value_grounding == "live_db_required"
    assert columns["HastaAdi"].pii is True
    assert columns["HastaAdi"].selectable is False
    assert "appointment_duration_average" in columns["RandevuSuresi"].related_metrics


@pytest.mark.asyncio
async def test_schema_reasoning_accepts_unknown_paraphrase_with_real_column_support():
    provider = _provider(
        '{"status":"answerable","confidence":0.92,'
        '"reason":"Süre alanından hesaplanabilir",'
        '"supporting_columns":["RandevuSuresi"],'
        '"supporting_metrics":["appointment_duration_average"]}'
    )
    service = SchemaAnswerabilityService(provider)

    decision = await service.assess("Geçen seneki görüşmeler ne kadar vakit almış?")

    assert decision is not None
    assert decision.approved
    assert decision.supporting_columns == ["RandevuSuresi"]
    prompt = provider.generate.await_args.args[0]
    assert "ROW_GRAIN Her satır bir randevu kaydıdır" in prompt
    assert "RandevuSuresi" in prompt
    assert "appointment_duration_average" in prompt


@pytest.mark.asyncio
async def test_schema_reasoning_rejects_hallucinated_column():
    provider = _provider(
        '{"status":"answerable","confidence":0.99,"reason":"uydurma",'
        '"supporting_columns":["DolulukOrani"],"supporting_metrics":[]}'
    )

    assert await SchemaAnswerabilityService(provider).assess("Doluluk nasıl?") is None


@pytest.mark.asyncio
async def test_unknown_in_domain_wording_is_promoted_to_database_pipeline():
    provider = _provider(
        '{"status":"answerable","confidence":0.88,"reason":"hesaplanabilir",'
        '"supporting_columns":["RandevuSuresi"],'
        '"supporting_metrics":["appointment_duration_average"],'
        '"dimension_columns":[],"analysis_type":"average",'
        '"time_column":"BaslangicTarihi","time_scope":"previous_year"}'
    )
    node = AnalyzeIntentNode(
        _classifier(),
        schema_answerability_service=SchemaAnswerabilityService(provider),
    )

    state = await node.execute(
        AgentState(question="Geçen seneki görüşmeler ne kadar vakit almış?")
    )

    assert state.answerable is True
    assert "schema_reasoning:answerable" in state.answerability_signals
    assert "schema_column:RandevuSuresi" in state.answerability_signals
    assert state.schema_reasoning_decision is not None
    assert state.schema_reasoning_decision.typed_plan_ready
    assert "BaslangicTarihi" in state.schema_reasoning_decision.supporting_columns


@pytest.mark.asyncio
async def test_schema_reasoning_keeps_unrelated_question_out_of_scope():
    provider = _provider(
        '{"status":"out_of_scope","confidence":0.98,'
        '"reason":"Hava verisi yok","supporting_columns":[],'
        '"supporting_metrics":[]}'
    )
    node = AnalyzeIntentNode(
        _classifier(),
        schema_answerability_service=SchemaAnswerabilityService(provider),
    )

    state = await node.execute(AgentState(question="Yarın yağmur yağacak mı?"))

    assert state.answerable is False
    assert "schema_reasoning:answerable" not in state.answerability_signals


@pytest.mark.asyncio
async def test_unsafe_write_never_calls_schema_reasoning():
    provider = _provider(
        '{"status":"answerable","confidence":1,'
        '"reason":"wrong","supporting_columns":["Id"],'
        '"supporting_metrics":[]}'
    )
    node = AnalyzeIntentNode(
        _classifier(),
        schema_answerability_service=SchemaAnswerabilityService(provider),
    )

    state = await node.execute(
        AgentState(question="Randevu tablosundaki kayıtları sil")
    )

    assert state.answerable is False
    provider.generate.assert_not_awaited()


@pytest.mark.asyncio
async def test_schema_reasoning_signal_releases_weak_query_plan_for_llm_sql():
    prompt_service = AsyncMock(spec=IPromptService)
    prompt_service.retrieve_schema_context.return_value = DatabaseContext(
        tables=[],
        views=[ViewMetadata(name="dbo.vw_RandevuRaporu", columns=[])],
    )
    node = RetrieveContextNode(prompt_service)

    state = await node.execute(
        AgentState(
            question="Geçen seneki görüşmeler ne kadar vakit almış?",
            answerable=True,
            answerability_signals=[
                "schema_reasoning:answerable",
                "schema_column:RandevuSuresi",
            ],
        )
    )

    assert state.database_context is not None
    assert state.query_plan is None


@pytest.mark.asyncio
async def test_typed_schema_reasoning_builds_validated_metric_dimension_and_time_plan():
    prompt_service = AsyncMock(spec=IPromptService)
    prompt_service.retrieve_schema_context.return_value = DatabaseContext(
        tables=[],
        views=[ViewMetadata(name="dbo.vw_RandevuRaporu", columns=[])],
    )
    node = RetrieveContextNode(prompt_service)
    decision = SchemaReasoningDecision(
        status="answerable",
        confidence=0.94,
        reason="Planlanan süre metriği",
        supporting_columns=["RandevuSuresi", "BaslangicTarihi"],
        supporting_metrics=["appointment_duration_average"],
        analysis_type="average",
        time_column="BaslangicTarihi",
        time_scope="previous_year",
    )

    state = await node.execute(
        AgentState(
            question="Geçen seneki görüşmeler ne kadar vakit almış?",
            answerable=True,
            answerability_signals=["schema_reasoning:answerable"],
            schema_reasoning_decision=decision,
        )
    )

    plan = state.query_plan
    assert plan is not None
    assert plan.planning_source == "llm_schema_reasoning"
    assert plan.metrics == ["appointment_duration_average"]
    assert plan.analysis_type == "average"
    assert set(plan.required_columns) == {"RandevuSuresi", "BaslangicTarihi"}
    assert plan.date_filters[0].start_date == f"{date.today().year - 1}-01-01"
    assert plan.date_filters[0].end_date == f"{date.today().year - 1}-12-31"
    assert plan.date_filters[0].column == "BaslangicTarihi"
