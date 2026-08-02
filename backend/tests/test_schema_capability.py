import pytest

from app.agent.graph import route_by_intent
from app.agent.nodes.analyze_intent import AnalyzeIntentNode
from app.agent.nodes.generate_schema_capability import GenerateSchemaCapabilityNode
from app.agent.state import AgentState
from app.semantics import catalog
from app.semantics.schema_knowledge import load_schema_knowledge
from app.services.schema_capability import SchemaCapabilityService


class _ClassifierMustNotRun:
    def classify(self, question):
        raise AssertionError(f"intent classifier should not run for capability: {question}")


def _question(business_name: str) -> str:
    return f"{business_name} alanını kullanarak hangi analizi yapabilirsin?"


def test_service_answers_every_catalog_column_probe():
    service = SchemaCapabilityService()

    answers = [
        service.answer(_question(column.business_name))
        for column in catalog.load_column_catalog().columns
    ]

    assert all(answer is not None for answer in answers)
    assert {answer.column for answer in answers if answer} == (
        catalog.load_column_catalog().column_names()
    )
    assert all(len(answer.example_questions) >= 2 for answer in answers if answer)


def test_service_recognizes_natural_example_question_request():
    answer = SchemaCapabilityService().answer(
        "Randevu süresi sütunuyla hangi soruları sorabilirim?"
    )

    assert answer is not None
    assert "## Örnek sorular" in answer.markdown
    assert "ortalama randevu süresi" in answer.markdown.casefold()


def test_llm_schema_context_contains_examples_for_every_column():
    knowledge = load_schema_knowledge()

    assert len(knowledge.columns) == 24
    assert all(len(column.example_questions) >= 2 for column in knowledge.columns)
    rendered = knowledge.render_for_llm()
    assert rendered.count("examples=") == len(knowledge.columns)


@pytest.mark.parametrize(
    "question",
    [
        "2024 yılında bölüm bazında randevu sayısını göster.",
        "Randevu durumuna göre dağılımı getir.",
        "Ortalama randevu süresi nedir?",
    ],
)
def test_service_ignores_ordinary_analytical_questions(question):
    assert SchemaCapabilityService().answer(question) is None


def test_pii_capability_answer_never_offers_raw_values():
    answer = SchemaCapabilityService().answer(
        "Hasta adı alanını kullanarak hangi analizi yapabilirsin?"
    )

    assert answer is not None
    assert answer.protected
    assert "Ham değerleri" in answer.markdown
    assert "kişi listesini göstermem" in answer.markdown
    assert all("listele" not in question.casefold() for question in answer.example_questions)


def test_unverified_metrics_are_not_advertised_as_supported():
    answer = SchemaCapabilityService().answer(
        "Protokol işlem durumu alanını kullanarak hangi analizi yapabilirsin?"
    )

    assert answer is not None
    assert "Protokol durumuna göre tamamlanma" not in answer.markdown
    assert "Protokol durum tutarsızlığı" not in answer.markdown


@pytest.mark.asyncio
async def test_analyze_intent_short_circuits_before_classifier_and_sql_path():
    node = AnalyzeIntentNode(_ClassifierMustNotRun())
    state = AgentState(
        question="Randevu kimliği alanını kullanarak hangi analizi yapabilirsin?",
        raw_question="Randevu kimliği alanını kullanarak hangi analizi yapabilirsin?",
    )

    result = await node.execute(state)

    assert result.schema_capability_answer is not None
    assert result.intent is None
    assert route_by_intent(result) == "schema_capability"


@pytest.mark.asyncio
async def test_schema_capability_node_returns_report_without_sql_or_database_result():
    capability = SchemaCapabilityService().answer(
        "Oluşturulma tarihi alanını kullanarak hangi analizi yapabilirsin?"
    )
    assert capability is not None
    result = await GenerateSchemaCapabilityNode().execute(
        AgentState(question="q", schema_capability_answer=capability)
    )

    assert result.generated_report is not None
    assert result.generated_report.model == "schema_capability_service"
    assert result.generated_sql is None
    assert result.query_result is None
    assert result.response_mode == "answer"
