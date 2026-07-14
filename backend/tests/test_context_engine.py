"""PRODUCT-001 — Conversational context engine regression tests.

Covers date/department/doctor inheritance, pronoun resolution, comparison and
trend continuation, context replacement, context expiration, ambiguous
follow-ups, and new-conversation reset. Fully deterministic — no LLM, no DB.
"""

import pytest

from app.context.context_manager import ContextManager
from app.context.extractor import ContextExtractor
from app.context.session_store import SessionStore


class FakeClock:
    def __init__(self) -> None:
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture()
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture()
def manager(clock: FakeClock) -> ContextManager:
    return ContextManager(store=SessionStore(now_fn=clock))


def ask(manager: ContextManager, question: str, session: str = "s1"):
    """Simulates one full pipeline turn: resolve then update."""
    resolution = manager.resolve(question, session)
    manager.update(resolution, session)
    return resolution


# ─────────────────────────────────────────────
# Extraction
# ─────────────────────────────────────────────

class TestExtractor:
    def setup_method(self) -> None:
        self.extractor = ContextExtractor()

    def test_detects_canonical_date_from_suffixed_form(self):
        signals = self.extractor.extract("Bugünkü randevuları göster")
        assert signals.date_expression == "bugun"

    def test_detects_department_fold_insensitive(self):
        signals = self.extractor.extract("KARDİYOLOJİ doktorlarını göster")
        assert signals.department == "Kardiyoloji"
        assert "Doctor" in signals.entity_types

    def test_detects_pronouns(self):
        signals = self.extractor.extract("Bunlardan en yoğun olan kim?")
        assert signals.pronouns == ["bunlardan"]
        assert signals.is_analytical

    def test_department_question_flagged(self):
        signals = self.extractor.extract("En yoğun bölüm hangisi?")
        assert signals.asks_department
        assert signals.is_analytical

    def test_date_only_followup(self):
        signals = self.extractor.extract("Peki geçen ay?")
        assert signals.is_date_only_followup
        assert signals.date_expression == "gecen ay"

    def test_full_question_is_not_date_only(self):
        signals = self.extractor.extract("Geçen ay kaç randevu oluşturuldu?")
        assert not signals.is_date_only_followup


# ─────────────────────────────────────────────
# Date inheritance
# ─────────────────────────────────────────────

class TestDateInheritance:
    def test_today_inherited_by_analytical_followup(self, manager):
        ask(manager, "Bugün kaç randevu oluşturuldu?")
        resolution = ask(manager, "En yoğun bölüm hangisi?")
        assert resolution.applied
        assert resolution.inherited["date"] == "bugun"
        assert resolution.resolved_question.startswith("bugun ")

    def test_explicit_date_never_overwritten(self, manager):
        ask(manager, "Bugün kaç randevu oluşturuldu?")
        resolution = ask(manager, "Geçen hafta kaç randevu oluşturuldu?")
        assert "date" not in resolution.inherited
        assert "bugun" not in resolution.resolved_question

    def test_plain_listing_not_date_scoped(self, manager):
        ask(manager, "Bugün kaç randevu oluşturuldu?")
        resolution = ask(manager, "Doktorları listele")
        assert "date" not in resolution.inherited


# ─────────────────────────────────────────────
# Department / doctor inheritance
# ─────────────────────────────────────────────

class TestDepartmentInheritance:
    def test_department_inherited_for_doctor_listing(self, manager):
        ask(manager, "Psikiyatri bölümünü göster")
        resolution = ask(manager, "Doktorları listele")
        assert resolution.inherited["department"] == "Psikiyatri"
        assert resolution.resolved_question.startswith("Psikiyatri ")

    def test_department_inherited_for_analytical_followup(self, manager):
        ask(manager, "Kardiyoloji doktorlarını göster")
        resolution = ask(manager, "Kaç hasta muayene edildi?")
        assert resolution.inherited["department"] == "Kardiyoloji"

    def test_department_question_does_not_inherit_department(self, manager):
        ask(manager, "Kardiyoloji doktorlarını göster")
        resolution = ask(manager, "En yoğun bölüm hangisi?")
        assert "department" not in resolution.inherited

    def test_explicit_department_never_overwritten(self, manager):
        ask(manager, "Kardiyoloji doktorlarını göster")
        resolution = ask(manager, "Üroloji doktorlarını göster")
        assert "department" not in resolution.inherited
        assert "Kardiyoloji" not in resolution.resolved_question


# ─────────────────────────────────────────────
# Pronoun resolution
# ─────────────────────────────────────────────

class TestPronounResolution:
    def test_bunlardan_resolves_to_department_doctors(self, manager):
        ask(manager, "Kardiyoloji doktorlarını göster")
        resolution = ask(manager, "Bunlardan en yoğun olan kim?")
        assert resolution.applied
        assert "Kardiyoloji doktorlari arasindan" in resolution.resolved_question
        assert not resolution.clarification_needed

    def test_onlar_resolves_to_single_entity(self, manager):
        ask(manager, "Hastaları listele")
        resolution = ask(manager, "Onları say")
        assert resolution.applied
        assert "hastalar" in resolution.resolved_question

    def test_o_bolum_resolves_to_department(self, manager):
        ask(manager, "Psikiyatri randevularını göster")
        resolution = ask(manager, "O bölümde kaç doktor var?")
        assert "Psikiyatri" in resolution.resolved_question
        assert not resolution.clarification_needed

    def test_o_doktor_requires_clarification(self, manager):
        ask(manager, "Kardiyoloji doktorlarını göster")
        resolution = manager.resolve("O doktorun randevularını göster", "s1")
        assert resolution.clarification_needed

    def test_pronoun_without_context_requires_clarification(self, manager):
        resolution = manager.resolve("Bunlardan en yoğun olan kim?", "s1")
        assert resolution.clarification_needed
        assert resolution.clarification_question


# ─────────────────────────────────────────────
# Comparison / trend continuation
# ─────────────────────────────────────────────

class TestContinuation:
    def test_comparison_continuation_with_new_date(self, manager):
        ask(manager, "Bu ay bölümlere göre randevuları karşılaştır")
        resolution = ask(manager, "Peki geçen ay?")
        assert resolution.applied
        assert "karsilastir" in resolution.resolved_question
        assert "gecen ay" in resolution.resolved_question
        assert "bu ay" not in resolution.resolved_question

    def test_trend_continuation_with_new_date(self, manager):
        ask(manager, "Bu yıl randevu trendini göster")
        resolution = ask(manager, "Geçen yıl?")
        assert resolution.applied
        assert "trend" in resolution.resolved_question
        assert "gecen yil" in resolution.resolved_question

    def test_date_only_followup_without_anchor_passes_through(self, manager):
        resolution = ask(manager, "Peki geçen ay?")
        assert resolution.resolved_question == "Peki geçen ay?"
        assert not resolution.applied


# ─────────────────────────────────────────────
# Context replacement / expiration
# ─────────────────────────────────────────────

class TestReplacementAndExpiration:
    def test_latest_explicit_date_replaces_previous(self, manager):
        ask(manager, "Bugün kaç randevu var?")
        ask(manager, "Yarın kaç randevu var?")
        resolution = ask(manager, "En yoğun bölüm hangisi?")
        assert resolution.inherited["date"] == "yarin"

    def test_latest_explicit_department_replaces_previous(self, manager):
        ask(manager, "Kardiyoloji doktorlarını göster")
        ask(manager, "Psikiyatri doktorlarını göster")
        resolution = ask(manager, "Kaç randevu oluşturuldu?")
        assert resolution.inherited["department"] == "Psikiyatri"

    def test_context_expires_after_ttl(self, manager, clock):
        ask(manager, "Bugün kaç randevu oluşturuldu?")
        clock.advance(31 * 60)
        resolution = manager.resolve("En yoğun bölüm hangisi?", "s1")
        assert not resolution.applied
        assert resolution.resolved_question == "En yoğun bölüm hangisi?"

    def test_turn_window_is_bounded(self, manager):
        for index in range(12):
            ask(manager, f"Bugün kaç randevu var? ({index})")
        context = manager._store.get("s1")
        assert len(context.turns) <= manager._store.max_turns


# ─────────────────────────────────────────────
# Session isolation / reset
# ─────────────────────────────────────────────

class TestSessions:
    def test_sessions_are_isolated(self, manager):
        ask(manager, "Bugün kaç randevu oluşturuldu?", session="a")
        resolution = manager.resolve("En yoğun bölüm hangisi?", "b")
        assert not resolution.applied

    def test_new_conversation_reset(self, manager):
        ask(manager, "Kardiyoloji doktorlarını göster")
        manager.clear("s1")
        resolution = manager.resolve("Doktorları listele", "s1")
        assert not resolution.applied
        assert resolution.resolved_question == "Doktorları listele"

    def test_small_talk_does_not_become_anchor(self, manager):
        ask(manager, "Bu ay bölümlere göre randevuları karşılaştır")
        ask(manager, "Teşekkürler")
        resolution = ask(manager, "Peki geçen ay?")
        assert "karsilastir" in resolution.resolved_question


# ─────────────────────────────────────────────
# Safety
# ─────────────────────────────────────────────

class TestSafety:
    def test_standalone_question_passes_through_unchanged(self, manager):
        resolution = ask(manager, "Geçen hafta Üroloji bölümünde kaç randevu oluşturuldu?")
        assert not resolution.applied
        assert (
            resolution.resolved_question
            == "Geçen hafta Üroloji bölümünde kaç randevu oluşturuldu?"
        )

    def test_resolver_failure_degrades_to_passthrough(self, manager, monkeypatch):
        def boom(*args, **kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr(manager._resolver, "resolve", boom)
        resolution = manager.resolve("Bugün kaç randevu var?", "s1")
        assert resolution.resolved_question == "Bugün kaç randevu var?"
        assert not resolution.applied
