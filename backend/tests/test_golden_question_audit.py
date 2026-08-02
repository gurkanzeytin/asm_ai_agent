import json
from pathlib import Path

from tools.evaluation.golden_audit import audit_golden_questions, summarize

DEMO_PACK_PATH = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "resources"
    / "mentor_demo_pack.json"
)


def test_golden_question_audit_finds_demo_ready_questions_without_database():
    results = audit_golden_questions()

    assert len(results) >= 250
    assert any(result.passed and result.deterministic for result in results)
    assert "deterministic_demo_ready=" in summarize(results)


def test_golden_question_audit_keeps_patient_detail_out_of_passing_sql_questions():
    results = audit_golden_questions()
    passing_ids = {
        result.id
        for result in results
        if result.passed and result.deterministic
    }

    assert "COUNT-001" in passing_ids
    assert "UNANS-021" not in passing_ids


def test_mentor_demo_pack_contains_only_audited_deterministic_questions():
    pack = json.loads(DEMO_PACK_PATH.read_text(encoding="utf-8"))
    results = {result.id: result for result in audit_golden_questions()}
    question_ids = pack["question_ids"]

    assert len(question_ids) >= 50
    assert len(question_ids) == len(set(question_ids))
    assert all(results[question_id].passed for question_id in question_ids)
    assert all(results[question_id].deterministic for question_id in question_ids)
