"""REASONING-001 — Semantic Understanding Engine regression tests.

Covers single/multiple entities, date and department expressions, compound
constraints, ranking, aggregation, comparison, trend, negative, existence,
out-of-scope, ambiguity (with reasons), follow-up questions, medical synonyms,
constraint completeness, and the <5 ms latency target. Deterministic — no
LLM, no database, no embeddings.
"""

import time

import pytest

from app.semantics.engine import SemanticUnderstandingEngine
from app.semantics.ontology import AMBIGUOUS_PHRASES


@pytest.fixture(scope="module")
def engine() -> SemanticUnderstandingEngine:
    return SemanticUnderstandingEngine()


# ─────────────────────────────────────────────
# Subjects
# ─────────────────────────────────────────────

class TestSubjects:
    def test_single_entity(self, engine):
        frame = engine.understand("Doktorları listele")
        assert frame.primary_subject == "Doctor"
        assert frame.goal == "LIST"
        assert frame.requested_output == "doctor_names"

    def test_multiple_entities_primary_is_last_mentioned(self, engine):
        frame = engine.understand("Randevulardaki doktorları göster")
        assert frame.primary_subject == "Doctor"
        assert frame.fact_subject == "Appointment"
        assert "Appointment" in frame.secondary_subjects

    def test_department_only_question(self, engine):
        frame = engine.understand("Bölümleri listele")
        assert frame.primary_subject == "Department"

    def test_implied_appointment_for_volume_ranking(self, engine):
        frame = engine.understand("En yoğun bölüm hangisi?")
        assert frame.primary_subject == "Department"
        assert frame.fact_subject == "Appointment"

    def test_date_on_non_event_subject_implies_appointments(self, engine):
        """'Bugünkü doktorlar' means doctors with appointments today — the date
        must never bind to the doctor's own date columns (e.g. hire date)."""
        frame = engine.understand("Bugünkü çocuk doktorlarını göster")
        assert frame.primary_subject == "Doctor"
        assert frame.fact_subject == "Appointment"


# ─────────────────────────────────────────────
# Constraints
# ─────────────────────────────────────────────

class TestConstraints:
    def test_date_expression(self, engine):
        frame = engine.understand("Bugün kaç randevu oluşturuldu?")
        dates = [c for c in frame.constraints if c.type == "date"]
        assert len(dates) == 1
        assert ".." in dates[0].detail

    def test_department_expression(self, engine):
        frame = engine.understand("Kardiyoloji doktorlarını göster")
        departments = [c for c in frame.constraints if c.type == "department"]
        assert departments and departments[0].value == "Kardiyoloji"

    def test_compound_constraints_all_preserved(self, engine):
        """The spec example: every meaningful concept must be structured."""
        frame = engine.understand("Bugünkü çocuk doktorlarını göster")
        assert frame.goal == "LIST"
        assert frame.primary_subject == "Doctor"
        assert frame.requested_output == "doctor_names"
        types = frame.constraint_types()
        assert "date" in types
        departments = [c for c in frame.constraints if c.type == "department"]
        assert departments[0].value == "Cocuk Sagligi"
        assert frame.confidence >= 0.9

    def test_limit_constraint(self, engine):
        frame = engine.understand("İlk 5 doktoru göster")
        limits = [c for c in frame.constraints if c.type == "limit"]
        assert limits and limits[0].value == "5"

    def test_three_constraints_survive(self, engine):
        frame = engine.understand("Bugün Kardiyolojideki ilk 3 doktoru göster")
        types = frame.constraint_types()
        assert {"date", "department", "limit"}.issubset(set(types))


# ─────────────────────────────────────────────
# Question types and goals
# ─────────────────────────────────────────────

class TestQuestionTypes:
    def test_ranking(self, engine):
        frame = engine.understand("En çok randevusu olan doktor kim?")
        assert frame.goal == "RANK"
        assert frame.question_type == "ranking"
        assert frame.requested_output == "ranking"

    def test_aggregation_count(self, engine):
        frame = engine.understand("Kaç hasta var?")
        assert frame.goal == "COUNT"
        assert frame.question_type == "aggregation"
        assert frame.requested_output == "count"

    def test_aggregation_average(self, engine):
        frame = engine.understand("Doktor başına ortalama randevu sayısı nedir?")
        assert frame.requested_output in ("average", "count")
        assert frame.question_type == "aggregation"

    def test_comparison(self, engine):
        frame = engine.understand("Bölümlere göre randevuları karşılaştır")
        assert frame.goal == "COMPARE"
        assert frame.question_type == "comparison"
        assert frame.requested_output == "distribution"

    def test_trend(self, engine):
        frame = engine.understand("Randevuların aylara göre trendini göster")
        assert frame.goal == "TREND"
        assert frame.question_type == "trend"
        assert frame.requested_output == "time_series"

    def test_negative_query(self, engine):
        frame = engine.understand("Randevusu olmayan doktorları listele")
        assert frame.question_type == "negative"
        assert any(c.type == "negation" for c in frame.constraints)

    def test_existence_query(self, engine):
        frame = engine.understand("Kardiyolojide randevusu olan hasta var mı?")
        assert frame.question_type == "existence"
        assert frame.requested_output == "boolean"

    def test_out_of_scope(self, engine):
        frame = engine.understand("Bitcoin fiyatı ne kadar?")
        assert frame.question_type == "out_of_scope"
        assert frame.confidence <= 0.4

    def test_bare_column_mention_is_not_out_of_scope(self, engine):
        """Kept in sync with AnswerabilityGuard (2026-07-24): a question
        naming a view column/metric with no entity noun ("hasta"/"randevu")
        must not be classified out_of_scope here either, or the logged
        Question Type contradicts the pipeline actually answering it."""
        frame = engine.understand("Kadın erkek oranını hesapla")
        assert frame.question_type != "out_of_scope"

    def test_general_help(self, engine):
        frame = engine.understand("Bana yardım eder misin, neler yapabilirsin?")
        assert frame.question_type == "general_help"

    def test_follow_up_with_pronoun(self, engine):
        frame = engine.understand("Bunlardan en yoğun olan kim?")
        assert frame.question_type == "follow_up"

    def test_analytical(self, engine):
        frame = engine.understand("Son 6 ayın randevularını analiz et")
        assert frame.goal in ("ANALYZE", "TREND")
        assert frame.question_type in ("analytical", "trend")


# ─────────────────────────────────────────────
# Ambiguity — must explain WHY, never guess
# ─────────────────────────────────────────────

class TestAmbiguity:
    @pytest.mark.parametrize("phrase", ["en iyi", "en başarılı", "en kötü", "en verimli"])
    def test_ambiguous_phrases_detected_with_reason(self, engine, phrase):
        frame = engine.understand(f"{phrase} doktor kim?")
        assert frame.ambiguities, f"'{phrase}' should be ambiguous"
        assert frame.ambiguities[0].reason  # WHY must always be present
        assert frame.confidence < 0.75

    def test_performans_is_ambiguous(self, engine):
        frame = engine.understand("Doktor performansını göster")
        assert any(a.phrase == "performans" for a in frame.ambiguities)

    def test_every_ambiguous_phrase_has_reason(self):
        for phrase, reason in AMBIGUOUS_PHRASES.items():
            assert reason and len(reason) > 20, f"'{phrase}' needs an explanation"

    def test_unambiguous_ranking_stays_clean(self, engine):
        frame = engine.understand("En yoğun bölüm hangisi?")
        assert frame.ambiguities == []


# ─────────────────────────────────────────────
# Medical synonyms
# ─────────────────────────────────────────────

class TestMedicalSynonyms:
    @pytest.mark.parametrize(
        "question,department",
        [
            ("Kalp doktorlarını listele", "Kardiyoloji"),
            ("Pediatri doktorlarını göster", "Cocuk Sagligi"),
            ("Çocuk doktorlarını göster", "Cocuk Sagligi"),
            ("KBB doktorlarını göster", "Kulak Burun Bogaz"),
            ("Cildiye doktorlarını göster", "Cildiye"),
        ],
    )
    def test_medical_synonym_resolves_department(self, engine, question, department):
        frame = engine.understand(question)
        departments = [c.value for c in frame.constraints if c.type == "department"]
        assert departments == [department]

    def test_hekim_maps_to_doctor(self, engine):
        frame = engine.understand("Hekimleri listele")
        assert frame.primary_subject == "Doctor"

    def test_muayene_maps_to_appointment(self, engine):
        frame = engine.understand("Bugünkü muayeneleri göster")
        assert frame.primary_subject == "Appointment"


# ─────────────────────────────────────────────
# Relationships — semantic, not SQL joins
# ─────────────────────────────────────────────

class TestRelationships:
    def test_doctor_department_relationship(self, engine):
        frame = engine.understand("Kardiyoloji bölümündeki doktorları göster")
        rendered = [r.render() for r in frame.relationships]
        assert "Doctor --works_in--> Department" in rendered

    def test_appointment_doctor_relationship(self, engine):
        frame = engine.understand("Randevulardaki doktorları göster")
        rendered = [r.render() for r in frame.relationships]
        assert "Appointment --belongs_to--> Doctor" in rendered

    def test_no_relationship_without_subjects(self, engine):
        frame = engine.understand("Doktorları listele")
        assert frame.relationships == []


# ─────────────────────────────────────────────
# Confidence model
# ─────────────────────────────────────────────

class TestConfidence:
    def test_rich_question_high_confidence(self, engine):
        frame = engine.understand("Bugünkü çocuk doktorlarını göster")
        assert frame.confidence >= 0.9

    def test_ambiguous_question_low_confidence(self, engine):
        frame = engine.understand("En iyi doktor kim?")
        assert frame.confidence < 0.6

    def test_bare_question_medium_confidence(self, engine):
        frame = engine.understand("Doktorlar")
        assert 0.4 <= frame.confidence <= 0.8


# ─────────────────────────────────────────────
# Performance — target < 5 ms
# ─────────────────────────────────────────────

class TestPerformance:
    def test_latency_under_5ms(self, engine):
        question = "Bugünkü randevular içerisinden çocuk sağlığındaki doktorları listele"
        engine.understand(question)  # warm-up (rule config load)
        start = time.perf_counter()
        runs = 50
        for _ in range(runs):
            engine.understand(question)
        average_ms = (time.perf_counter() - start) * 1000 / runs
        assert average_ms < 5.0, f"average {average_ms:.2f} ms exceeds 5 ms target"


# ─────────────────────────────────────────────
# Planner integration — frame is the planner's input
# ─────────────────────────────────────────────

class TestPlannerIntegration:
    def test_frame_subjects_drive_plan(self, engine):
        from app.planning.planner import QueryPlanner
        from app.services.query_analyzer import QueryAnalyzer

        question = "Bugünkü randevular içerisinden çocuk sağlığındaki doktorları listele"
        frame = engine.understand(question)
        analysis = QueryAnalyzer().analyze(question)
        plan = QueryPlanner().build_plan(question, analysis, [], semantic_frame=frame)
        assert plan.output_entity == frame.primary_subject == "Doctor"
        assert plan.fact_entity == frame.fact_subject == "Appointment"
        assert plan.department_filter == "Cocuk Sagligi"
