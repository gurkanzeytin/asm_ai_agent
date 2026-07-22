import pytest

from app.llm.remote_policy import (
    RemoteDataPolicyViolation,
    enforce_remote_data_policy,
    find_prohibited_fields,
)


class TestFindProhibitedFields:
    @pytest.mark.parametrize(
        "field",
        [
            "HastaAdi",
            "HastaSoyadi",
            "HastaId",
            "HastaId2",
            "DogumTarihi",
            "CinsiyetId",
            "Uyruk",
            "RandevuyuVeren",
            "TCKimlikNo",
            "PasaportNo",
            "HastaGSM",
        ],
    )
    def test_each_prohibited_field_is_detected(self, field):
        text = f"SELECT {field} FROM dbo.vw_RandevuRaporu"
        assert field in find_prohibited_fields(text)

    def test_case_insensitive_match(self):
        assert "HastaAdi" in find_prohibited_fields("select hastaadi from x")

    def test_no_match_on_safe_text(self):
        text = "Group appointments by department and count them per month."
        assert find_prohibited_fields(text) == []

    def test_empty_text_returns_empty(self):
        assert find_prohibited_fields("") == []

    def test_substring_is_not_falsely_matched(self):
        # "HastaAdiSoyadiBirlesik" is a different identifier; word-boundary match
        # must not treat it as containing the prohibited "HastaAdi" field.
        assert find_prohibited_fields("SELECT HastaAdiSoyadiBirlesik FROM x") == []


class TestEnforceRemoteDataPolicy:
    def test_unsafe_payload_raises(self):
        with pytest.raises(RemoteDataPolicyViolation) as exc_info:
            enforce_remote_data_policy("SELECT HastaAdi, HastaSoyadi FROM dbo.vw_RandevuRaporu")
        assert "HastaAdi" in exc_info.value.matched_fields
        assert "HastaSoyadi" in exc_info.value.matched_fields

    def test_safe_aggregate_payload_is_allowed(self):
        # Schema metadata, query plans, and aggregate summaries must pass through cleanly.
        enforce_remote_data_policy(
            "Schema: dbo.vw_RandevuRaporu(BaslangicTarihi, Departman, Id). "
            "Return a JSON query plan grouping appointment counts by department and month."
        )

    def test_checks_multiple_text_fragments(self):
        with pytest.raises(RemoteDataPolicyViolation):
            enforce_remote_data_policy("safe system prompt", "SELECT DogumTarihi FROM x")

    def test_previously_removed_fields_remain_prohibited(self):
        with pytest.raises(RemoteDataPolicyViolation):
            enforce_remote_data_policy("SELECT TCKimlikNo, PasaportNo, HastaGSM FROM x")
