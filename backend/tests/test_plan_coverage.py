"""Question→plan coverage detector (app.planning.coverage).

PlanComplianceValidator proves SQL implements the PLAN. Nothing proved the plan
implements the QUESTION, so a constraint dropped during planning left no trace
and the agent answered a different question at full confidence. These tests pin
both directions of the detector: it must fire on a genuinely partial reading,
and must stay silent on every question the deterministic path already answers
correctly.
"""

import json
from pathlib import Path

import pytest

from app.agent.nodes.resolve_filter_values import ResolveFilterValuesNode
from app.agent.state import AgentState
from app.database_intelligence.models import ViewMetadata
from app.database_intelligence.value_catalog import ValueCatalog
from app.planning.coverage import (
    partial_reading_reasons,
    ratio_without_ratio_metric,
    unconsumed_columns,
)
from app.planning.models import QueryPlan
from app.planning.planner import QueryPlanner
from app.planning.value_resolver import ValueResolver
from app.services.query_analyzer import QueryAnalyzer

VIEW = ViewMetadata(name="dbo.vw_RandevuRaporu", columns=[])
RESOURCES = Path(__file__).resolve().parents[1] / "app" / "resources"

_GROUNDED_VALUES = {
    "department": [
        "Kardiyoloji",
        "Radyoloji",
        "Ortopedi",
        "Nöroloji",
        "Genel Cerrahi",
        "Kadın Hastalıkları ve Doğum",
        "Göz Hastalıkları",
        "Dahiliye",
        "Üroloji",
        "Onkoloji",
        "Psikiyatri",
        "Kulak Burun Boğaz",
        "Çocuk Sağlığı",
    ],
    "branch": ["Gebze Şubesi", "Kadıköy Şubesi"],
    "gender": ["E", "K", "D"],
    "nationality": ["Türkiye", "Suriye", "Almanya"],
    "appointment_status": ["Gerçekleşti", "Gelmedi", "Beklemede"],
    "appointment_type": ["Poliklinik", "Ameliyat"],
    "category": ["Genel"],
    "service": ["Muayene"],
}


class _FakeValueCatalog(ValueCatalog):
    def __init__(self) -> None:  # noqa: D107 - deliberately skips the DB engine
        pass

    async def get_distinct_values(self, field_name: str) -> list[str]:
        return _GROUNDED_VALUES.get(field_name, [])

    async def search_candidates(self, field_name: str, _text: str) -> list[str]:
        return _GROUNDED_VALUES.get(field_name, [])


def _plan(question: str) -> QueryPlan:
    return QueryPlanner().build_plan(
        question, QueryAnalyzer().analyze(question), tables=[], views=[VIEW]
    )


async def _resolved_plan(question: str) -> QueryPlan:
    node = ResolveFilterValuesNode(resolver=ValueResolver(catalog=_FakeValueCatalog()))
    state = await node.execute(
        AgentState(question=question, raw_question=question, query_plan=_plan(question))
    )
    return state.query_plan


def _working_questions() -> list[str]:
    questions = [
        case["question"]
        for case in json.loads(
            (RESOURCES / "asm_24_column_golden_eval.json").read_text(encoding="utf-8")
        )["cases"]
    ]
    for scenario in json.loads(
        (RESOURCES / "asm_multi_turn_golden_eval.json").read_text(encoding="utf-8")
    )["scenarios"]:
        questions.extend(turn["question"] for turn in scenario["turns"])
    return questions


# ---------------------------------------------------------------------------
# Precision: never fire on a question the deterministic path answers correctly
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("question", _working_questions())
async def test_detector_is_silent_on_every_golden_question(question):
    assert partial_reading_reasons(await _resolved_plan(question)) == []


# ---------------------------------------------------------------------------
# Recall: fire on a genuinely partial reading
# ---------------------------------------------------------------------------


def test_ratio_question_answered_with_a_plain_aggregate_is_reported():
    """"...oranı nedir?" planned as an average is a different question, not a
    narrower one, and the answer carries no sign of the substitution."""
    plan = _plan("Randevu süresi 30 dakikadan uzun olanların oranı nedir?")

    assert plan.analysis_type == "ratio"
    assert ratio_without_ratio_metric(plan) is True
    assert "ratio_requested_without_ratio_metric" in partial_reading_reasons(plan)


@pytest.mark.parametrize(
    "question,expected_metric",
    [
        # Found BY this detector: both planned the *_count sibling, so the share
        # was never computed. "Gelmeyenlerin payı" additionally counted no-shows
        # inside an already no-show-filtered set — a share that is always 100%.
        # (BLIND-RATE-002 / BLIND-RATE-007 in evaluation_cases.json.)
        ("Gelmeyenlerin payi ne durumda?", "no_show_rate"),
        ("Ayni gun alinan randevularin payi nedir?", "same_day_booking_rate"),
        ("Gerceklesen randevularin payi", "completed_appointment_rate"),
        ("Bekleyenlerin yuzdesi nedir?", "waiting_rate"),
    ],
)
def test_share_wording_selects_the_rate_metric(question, expected_metric):
    plan = _plan(question)

    assert plan.metrics == [expected_metric]
    assert ratio_without_ratio_metric(plan) is False


@pytest.mark.parametrize(
    "question,expected_metric",
    [
        ("Gelmeyen randevu sayisi nedir?", "no_show_count"),
        ("Ayni gun alinan randevu sayisi", "same_day_booking_count"),
    ],
)
def test_count_wording_still_selects_the_count_metric(question, expected_metric):
    """The share promotion must not swallow a genuine count request."""
    assert _plan(question).metrics == [expected_metric]


def test_unconsumed_column_is_reported():
    """A column the question names that the plan uses nowhere."""
    plan = _plan("Bölüm bazında randevu sayısı").model_copy(
        update={"dimensions": [], "projection": [], "required_columns": ["Id"]}
    )

    assert unconsumed_columns(plan) == ["GenelRandevuBolumAdi"]


# ---------------------------------------------------------------------------
# Known blind spot — documented, not silently tolerated
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wording_no_layer_parses_is_a_documented_blind_spot():
    """"kadın hasta oranı" matches no catalog term at all, so there is nothing
    for a coverage check to find. This test exists so the limit is explicit: if
    a future vocabulary change makes it detectable, this test fails and the
    blind spot gets removed from the module docstring.
    """
    plan = await _resolved_plan("Hangi bölümde kadın hasta oranı en yüksek?")

    assert partial_reading_reasons(plan) == []
