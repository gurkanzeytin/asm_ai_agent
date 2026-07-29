"""Meta-conversation memory (2026-07-29): questions ABOUT the chat itself are
answered deterministically from retained context, never via SQL."""

import pytest

from app.agent.graph import route_by_intent
from app.agent.nodes.generate_conversation_memory import GenerateConversationMemoryNode
from app.agent.state import AgentState
from app.context.conversation_memory import (
    build_conversation_memory_answer,
    detect_conversation_memory_question,
)
from app.context.models import ConversationContext, ConversationTurn


@pytest.mark.parametrize(
    "folded,expected",
    [
        ("son uc sorumda hangi kirilimi istemistim", "dimension"),
        ("onceki cevabinda hangi metrik vardi", "metric"),
        ("bu sohbet icinde benden gelen son veri yili hangisiydi", "date"),
        ("az once ne sordum", "recap"),
        ("bu konusmada ne istedim", "recap"),
    ],
)
def test_detects_meta_question_category(folded, expected):
    assert detect_conversation_memory_question(folded) == expected


@pytest.mark.parametrize(
    "folded",
    [
        "2024 yilinda kac randevu var",
        "bir onceki ay kac randevu",  # relative date, NOT a memory reference
        "bolum bazinda randevu sayisi",
        "gelmeme oranini goster",
    ],
)
def test_ignores_ordinary_data_questions(folded):
    assert detect_conversation_memory_question(folded) is None


def _context() -> ConversationContext:
    return ConversationContext(
        session_id="s",
        dimensions=["department"],
        metrics=["no_show_rate"],
        date_expression="2024",
        turns=[
            ConversationTurn(question="2024 bolum bazinda gelmeme orani", resolved_question="x"),
            ConversationTurn(question="ilk 5 bolumu goster", resolved_question="y"),
        ],
    )


def test_answer_reports_latest_dimension():
    answer = build_conversation_memory_answer(_context(), "dimension")
    assert "Bölüm" in answer


def test_answer_reports_latest_metric():
    answer = build_conversation_memory_answer(_context(), "metric")
    assert "Gelmeme Oranı" in answer


def test_answer_reports_latest_date():
    answer = build_conversation_memory_answer(_context(), "date")
    assert "2024" in answer


def test_recap_lists_recent_questions():
    answer = build_conversation_memory_answer(_context(), "recap")
    assert "ilk 5 bolumu goster" in answer
    assert "2024 bolum bazinda gelmeme orani" in answer


def test_answer_is_none_without_history():
    empty = ConversationContext(session_id="s")
    assert build_conversation_memory_answer(empty, "dimension") is None


def test_route_short_circuits_to_conversation_memory_node():
    state = AgentState(
        question="son sorumda hangi kirilim vardi",
        raw_question="son sorumda hangi kirilim vardi",
        conversation_memory_answer="# Sohbet Hafızası\n\nSon kırılım: Bölüm.",
    )
    assert route_by_intent(state) == "conversation_memory"


@pytest.mark.asyncio
async def test_node_wraps_answer_in_report_without_sql():
    node = GenerateConversationMemoryNode()
    state = AgentState(
        question="q",
        raw_question="q",
        conversation_memory_answer="# Sohbet Hafızası\n\nSon kırılım: Bölüm.",
    )
    result = await node.execute(state)
    assert result.generated_report is not None
    assert "Son kırılım: Bölüm." in result.generated_report.markdown
    assert result.generated_sql is None
