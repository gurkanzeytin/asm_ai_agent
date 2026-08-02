from app.application_models.outcome import AgentOutcome
from app.application_models.schema_capability import SchemaCapabilityAnswer
from app.services.question_suggestions import build_suggested_questions


def test_clarification_options_become_bounded_clickable_replies():
    suggestions = build_suggested_questions(
        outcome=AgentOutcome.ASK_CLARIFICATION.value,
        ambiguity_options=[
            "Randevu sayısı",
            "Gelmeme oranı",
            "Sorumu değiştireceğim",
            "Randevu sayısı",
        ],
    )

    assert suggestions == ["Randevu sayısı", "Gelmeme oranı"]


def test_schema_help_reuses_column_specific_examples():
    capability = SchemaCapabilityAnswer(
        column="RandevuSuresi",
        business_name="Randevu süresi",
        markdown="yardım",
        example_questions=["Ortalama süre nedir?", "Maksimum süre nedir?"],
    )

    assert build_suggested_questions(
        outcome=AgentOutcome.RETURN_HELP.value,
        capability=capability,
    ) == ["Ortalama süre nedir?", "Maksimum süre nedir?"]


def test_guidance_outcomes_always_offer_safe_answerable_alternatives():
    for outcome in (
        AgentOutcome.OUT_OF_SCOPE.value,
        AgentOutcome.NO_RESULT_GUIDANCE.value,
        AgentOutcome.SAFE_ERROR.value,
    ):
        suggestions = build_suggested_questions(outcome=outcome)
        assert len(suggestions) == 4
        assert len(suggestions) == len(set(suggestions))


def test_successful_data_answer_does_not_add_distracting_suggestions():
    assert build_suggested_questions(outcome=AgentOutcome.EXECUTE_SQL.value) == []
