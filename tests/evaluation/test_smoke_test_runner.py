from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from scripts.smoke_test_runner import (
    DEFAULT_CATALOG,
    ArtifactWriter,
    AssertionEngine,
    AssertionResult,
    AssertionSpec,
    HttpResult,
    HttpxTransport,
    ScenarioCatalog,
    Severity,
    SmokeTestRunner,
    TurnResult,
    Verdict,
    classify_assertions,
    extract_evidence,
    filter_scenarios,
    redact_secrets,
)


class FakeTransport:
    def __init__(self, responses: list[HttpResult]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, dict[str, Any], float]] = []

    def post(self, url: str, payload: dict[str, Any], timeout: float) -> HttpResult:
        self.calls.append((url, payload, timeout))
        return self.responses[len(self.calls) - 1]


class FakeHttpxClient:
    response: httpx.Response | None = None
    error: Exception | None = None

    def __init__(self, timeout: float) -> None:
        self.timeout = timeout

    def __enter__(self) -> FakeHttpxClient:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def post(self, url: str, json: dict[str, Any]) -> httpx.Response:
        if self.error:
            raise self.error
        assert self.response is not None
        return self.response


def _success_payload(session_id: str = "server-session") -> dict[str, Any]:
    return {
        "session_id": session_id,
        "outcome": "success",
        "generated_sql": "SELECT COUNT(*) AS appointment_count FROM fact_appointment",
        "resolved_metrics": ["appointment_count"],
        "resolved_dimensions": ["branch_name"],
        "context_applied": False,
        "query_result": {
            "columns": ["branch_name", "appointment_count"],
            "row_count": 1,
            "rows": [{"branch_name": "Sensitive branch", "appointment_count": 42}],
        },
        "analytics": {
            "analytics_type": "distribution",
            "result_shape": "breakdown",
            "metrics": {"total": 42},
            "displayable_kpis": [{"key": "appointment_count", "label": "Randevu", "value": 42}],
        },
        "insights": {
            "provider": "template",
            "routing_mode": "deterministic",
            "model": "deterministic-v1",
            "fallback_used": False,
            "summary": "Toplam randevu sayısı 42.",
        },
        "report": {"title": "Randevu Dağılımı", "markdown": "# Randevu Dağılımı"},
        "timing": {"total_ms": 125, "planning_ms": 25},
    }


def _assertion(severity: Severity, passed: bool) -> AssertionResult:
    return AssertionResult("test", passed, severity, True, passed, "diagnostic")


def _turn_result(verdict: Verdict = Verdict.PASS) -> TurnResult:
    return TurnResult(
        timestamp="2026-07-22T10:00:00+03:00",
        scenario_id="01_basic_distribution",
        scenario_title="Temel dağılım",
        category="core",
        turn_number=1,
        question="Şubelere göre randevu sayısı",
        session_id="safe-session",
        http_status=200,
        response_outcome="success",
        report_text="# Randevu Dağılımı",
        generated_sql="SELECT COUNT(*) FROM fact_appointment",
        sql_source=None,
        query_row_count=1,
        query_columns=["appointment_count"],
        first_row_keys=["appointment_count"],
        safe_aggregate_summaries={"metrics": {"total": 42}, "kpis": []},
        analytics_type="distribution",
        result_shape="scalar",
        metric_ids=["appointment_count"],
        dimension_ids=[],
        context_applied=False,
        inherited_fields=[],
        provider="template",
        model="deterministic-v1",
        fallback_used=False,
        total_duration_seconds=0.125,
        stage_timings={"total_ms": 125},
        errors=[],
        stack_trace=None,
        assertions=[_assertion(Severity.MINOR, verdict == Verdict.PASS)],
        verdict=verdict,
        unavailable_fields=["sql_source", "server_stack_trace"],
    )


def test_scenario_catalog_parses_all_required_scenarios_and_turns() -> None:
    scenarios = ScenarioCatalog.load(DEFAULT_CATALOG)

    assert len(scenarios) == 12
    assert sum(len(scenario.turns) for scenario in scenarios) == 15
    assert {scenario.id for scenario in scenarios if len(scenario.turns) > 1} == {
        "07_additive_followup",
        "08_dimension_override",
        "09_year_only_followup",
    }
    assert all(scenario.session_group for scenario in scenarios)


def test_catalog_rejects_duplicate_ids(tmp_path: Path) -> None:
    catalog = json.loads(DEFAULT_CATALOG.read_text(encoding="utf-8"))
    catalog["scenarios"].append(catalog["scenarios"][0])
    path = tmp_path / "duplicates.json"
    path.write_text(json.dumps(catalog), encoding="utf-8")

    with pytest.raises(ValueError, match="benzersiz"):
        ScenarioCatalog.load(path)


def test_updated_scenario_expectations_remain_separate_and_semantic() -> None:
    scenarios = {scenario.id: scenario for scenario in ScenarioCatalog.load(DEFAULT_CATALOG)}
    grounded = scenarios["05_grounded_branch"]
    monthly = scenarios["03_monthly_trend"]
    year_only = scenarios["09_year_only_followup"]

    assert grounded.expected_analysis_type == "count|summary|list|trend|time_series"
    assert grounded.expected_provider == "template|deterministic"
    assert any(
        spec.kind == "sql_recent_day_window" for spec in grounded.turns[0].expectations.assertions
    )
    assert any(
        spec.kind == "trend_language_consistency"
        for spec in monthly.turns[0].expectations.assertions
    )
    assert [
        spec.expected
        for turn in year_only.turns
        for spec in turn.expectations.assertions
        if spec.kind == "sql_year_window"
    ] == [2025, 2024]


def test_grounded_provider_mismatch_is_major_and_sql_window_still_passes() -> None:
    grounded = next(
        scenario
        for scenario in ScenarioCatalog.load(DEFAULT_CATALOG)
        if scenario.id == "05_grounded_branch"
    )
    response = _success_payload()
    response.update(
        {
            "outcome": "EXECUTE_SQL",
            "generated_sql": (
                "SELECT COUNT(*) FROM t WHERE branch = 'TEST ASM Gebze' "
                "AND d >= '2026-06-23' "
                "AND d < DATEADD(day, 1, '2026-07-22')"
            ),
            "resolved_dimensions": [],
        }
    )
    response["analytics"]["analytics_type"] = "trend"
    response["insights"].update(
        {"provider": "nvidia", "routing_mode": "remote_llm", "model": "nemotron"}
    )
    response["metadata"] = {"provider": "nvidia", "model": "nemotron"}

    results = AssertionEngine().evaluate(
        grounded.turns[0].expectations,
        response,
        extract_evidence(response, 0.2),
    )
    by_kind = {result.kind: result for result in results}

    assert not by_kind["provider_model"].passed
    assert by_kind["provider_model"].severity == Severity.MAJOR
    assert by_kind["sql_recent_day_window"].passed


def test_reusable_assertion_types_and_turkish_critical_text_detection() -> None:
    engine = AssertionEngine()

    assert engine.equals("x", "SUCCESS", "success", Severity.MAJOR, "").passed
    assert engine.contains("x", "monthly trend", "trend", Severity.MAJOR, "").passed
    assert engine.not_contains("x", "safe", "secret", Severity.MAJOR, "").passed
    assert engine.subset("x", ["a", "b"], ["a"], Severity.MAJOR, "").passed
    assert engine.numeric_threshold("x", 1.5, 2.0, Severity.MAJOR, "").passed
    assert engine.boolean("x", True, True, Severity.MAJOR, "").passed
    assert engine.sql_clause("SELECT * FROM t WHERE year = 2026", "year = 2026", True).passed
    false_claim = engine.visible_text("Kayıt sayısı: 1", "Kayıt sayısı: 1", False)
    assert not false_claim.passed
    assert false_claim.severity == Severity.CRITICAL


def test_custom_guidance_assertion() -> None:
    engine = AssertionEngine()
    guidance = AssertionSpec("concise_turkish_guidance", 1000, Severity.MAJOR, "missing guidance")
    evidence = {
        "visible_text": "Bu veri alanı desteklenmiyor; randevu verilerini sorabilirsiniz.",
    }

    assert engine.custom(guidance, {}, evidence).passed


@pytest.mark.parametrize(
    "sql",
    [
        ("BaslangicTarihi >= '2026-06-23' AND BaslangicTarihi < DATEADD(day, 1, '2026-07-22')"),
        "BaslangicTarihi >= '2026-06-23' AND BaslangicTarihi < '2026-07-23'",
        ("BaslangicTarihi >= DATEADD(day, -30, '2026-07-23') AND BaslangicTarihi < '2026-07-23'"),
        (
            "baslangictarihi  >=  '2026-06-23' and baslangictarihi < "
            "dateadd ( dd , 1 , '2026-07-22' )"
        ),
        ("BaslangicTarihi >= '2024-01-31' AND BaslangicTarihi < DATEADD(DAY, 1, '2024-02-29')"),
        ("BaslangicTarihi >= '2025-12-10' AND BaslangicTarihi < DATEADD(day, 1, '2026-01-08')"),
    ],
    ids=[
        "inclusive-30-days",
        "next-day-literal",
        "relative-dateadd",
        "case-and-whitespace",
        "leap-month-boundary",
        "year-boundary",
    ],
)
def test_recent_day_window_accepts_semantic_30_day_equivalents(sql: str) -> None:
    spec = AssertionSpec("sql_recent_day_window", 30, Severity.CRITICAL, "wrong window")

    result = AssertionEngine().custom(spec, {}, {"generated_sql": sql})

    assert result.passed, result.actual


@pytest.mark.parametrize(
    ("sql", "covered_days"),
    [
        (
            "d >= '2026-06-24' AND d < DATEADD(day, 1, '2026-07-22')",
            29,
        ),
        (
            "d >= '2026-06-22' AND d < DATEADD(day, 1, '2026-07-22')",
            31,
        ),
    ],
    ids=["29-days", "31-days"],
)
def test_recent_day_window_rejects_wrong_calendar_coverage(sql: str, covered_days: int) -> None:
    spec = AssertionSpec("sql_recent_day_window", 30, Severity.CRITICAL, "wrong window")

    result = AssertionEngine().custom(spec, {}, {"generated_sql": sql})

    assert not result.passed
    assert result.actual["windows"][0]["days"] == covered_days


@pytest.mark.parametrize(
    "sql",
    [
        "d >= '2024-01-01' AND d < '2025-01-01'",
        "d >= '2024-01-01' AND d < DATEADD(day, 1, '2024-12-31')",
        "d >= '2024-01-01' AND d < dateadd ( DD , 1 , '2024-12-31' )",
    ],
)
def test_year_window_accepts_half_open_semantic_equivalents(sql: str) -> None:
    spec = AssertionSpec("sql_year_window", 2024, Severity.CRITICAL, "wrong year")

    assert AssertionEngine().custom(spec, {}, {"generated_sql": sql}).passed


@pytest.mark.parametrize(
    "sql",
    [
        "d >= '2024-01-01' AND d < '2024-12-31'",
        "d >= '2024-01-01' AND d < '2025-01-02'",
    ],
)
def test_year_window_rejects_short_or_long_ranges(sql: str) -> None:
    spec = AssertionSpec("sql_year_window", 2024, Severity.CRITICAL, "wrong year")

    assert not AssertionEngine().custom(spec, {}, {"generated_sql": sql}).passed


def test_context_inheritance_does_not_infer_merge_from_resolved_ids() -> None:
    response = {
        "context_applied": False,
        "outcome": "EXECUTE_SQL",
        "resolved_metrics": ["appointment_count", "completed_appointment_rate"],
        "resolved_dimensions": ["branch"],
        "inherited_fields": [],
    }

    result = AssertionEngine().context_inheritance(
        response, ["metrics", "dimensions"], "inheritance missing"
    )

    assert not result.passed
    assert result.severity == Severity.CRITICAL


def test_context_inheritance_requires_context_proof_and_expected_outcome() -> None:
    engine = AssertionEngine()
    valid = {
        "context_applied": True,
        "outcome": "EXECUTE_SQL",
        "inherited_fields": ["metric", "dimension"],
    }
    wrong_outcome = {**valid, "outcome": "ASK_CLARIFICATION"}

    assert engine.context_inheritance(
        valid, ["metrics", "dimensions"], "inheritance missing"
    ).passed
    assert not engine.context_inheritance(
        wrong_outcome, ["metrics", "dimensions"], "inheritance missing"
    ).passed


def test_context_inheritance_accepts_explicit_rewrite_merge_proof() -> None:
    response = {
        "context_applied": True,
        "follow_up_detected": True,
        "raw_question": "Bir de gerçekleşme oranını ekle.",
        "resolved_question": "Şubelere göre randevu sayısı ve gerçekleşme oranı.",
        "outcome": "EXECUTE_SQL",
        "inherited_fields": ["previous_question"],
    }

    result = AssertionEngine().context_inheritance(
        response, ["metrics", "dimensions"], "inheritance missing"
    )

    assert result.passed


def test_non_monotonic_series_rejects_continuous_growth_claim() -> None:
    spec = AssertionSpec(
        "trend_language_consistency",
        ["monthly_appointment_count"],
        Severity.CRITICAL,
        "factual inconsistency",
    )
    response = {
        "query_result": {
            "rows": [
                {"month": index, "monthly_appointment_count": value}
                for index, value in enumerate([12, 15, 9, 13, 13, 19], start=1)
            ]
        }
    }

    result = AssertionEngine().custom(
        spec, response, {"visible_text": "Randevu sayısı her ay arttı ve sürekli yükseldi."}
    )

    assert not result.passed
    assert result.severity == Severity.CRITICAL
    assert result.actual["values"] == [12.0, 15.0, 9.0, 13.0, 13.0, 19.0]


def test_trend_language_allows_grounded_or_neutral_claims() -> None:
    spec = AssertionSpec(
        "trend_language_consistency",
        ["monthly_appointment_count"],
        Severity.CRITICAL,
        "factual inconsistency",
    )
    monotonic = {
        "query_result": {
            "rows": [{"monthly_appointment_count": value} for value in [9, 12, 15, 19]]
        }
    }
    non_monotonic = {
        "query_result": {
            "rows": [{"monthly_appointment_count": value} for value in [12, 15, 9, 19]]
        }
    }
    engine = AssertionEngine()

    assert engine.custom(spec, monotonic, {"visible_text": "Randevu sayısı sürekli arttı."}).passed
    assert engine.custom(
        spec, non_monotonic, {"visible_text": "Dönemler arasında dalgalanma görüldü."}
    ).passed


@pytest.mark.parametrize(
    ("assertions", "expected"),
    [
        ([], Verdict.PASS),
        ([_assertion(Severity.MINOR, False)], Verdict.PARTIAL),
        ([_assertion(Severity.MAJOR, False)], Verdict.PARTIAL),
        (
            [_assertion(Severity.MAJOR, False), _assertion(Severity.MAJOR, False)],
            Verdict.FAIL,
        ),
        ([_assertion(Severity.CRITICAL, False)], Verdict.FAIL),
    ],
)
def test_pass_partial_fail_classification(
    assertions: list[AssertionResult], expected: Verdict
) -> None:
    assert classify_assertions(assertions) == expected


def test_multi_turn_scenario_reuses_returned_session_id() -> None:
    scenario = next(
        item for item in ScenarioCatalog.load(DEFAULT_CATALOG) if item.id == "07_additive_followup"
    )
    first = _success_payload("canonical-session")
    second = _success_payload("canonical-session")
    transport = FakeTransport([HttpResult(200, first, 0.1), HttpResult(200, second, 0.1)])

    results = SmokeTestRunner("http://localhost:8000", 5.0, "isolated", transport=transport).run(
        [scenario]
    )

    assert len(results) == 2
    assert transport.calls[1][1]["session_id"] == "canonical-session"
    assert all(call[0].endswith("/api/v1/report/") for call in transport.calls)
    assert all(call[2] == 5.0 for call in transport.calls)


def test_grouped_mode_shares_session_across_scenarios() -> None:
    scenarios = ScenarioCatalog.load(DEFAULT_CATALOG)[:2]
    # Force a common group without touching the frozen production catalog objects.
    common = [
        type(scenario)(**{**scenario.__dict__, "session_group": "meeting"})
        for scenario in scenarios
    ]
    transport = FakeTransport(
        [
            HttpResult(200, _success_payload("shared"), 0.1),
            HttpResult(200, _success_payload("shared"), 0.1),
        ]
    )

    SmokeTestRunner("http://localhost:8000", 5.0, "grouped", transport=transport).run(common)

    assert transport.calls[1][1]["session_id"] == "shared"


def test_redaction_recurses_and_removes_common_secret_forms() -> None:
    value = {
        "authorization": "Bearer abc.def",
        "nested": {
            "api_key": "top-secret",
            "message": "password=hunter2 token:abc123",
            "dsn": "https://alice:private@example.test/db",
        },
    }

    serialized = json.dumps(redact_secrets(value))

    for secret in ("abc.def", "top-secret", "hunter2", "abc123", "private"):
        assert secret not in serialized
    assert serialized.count("[REDACTED]") >= 4


def test_evidence_keeps_row_metadata_but_never_patient_row_values() -> None:
    payload = _success_payload()
    payload["query_result"]["rows"] = [
        {"patient_name": "Patient Jane", "tc_identity": "12345678901", "total": 9}
    ]

    evidence = extract_evidence(payload, 9.0)
    encoded = json.dumps(evidence)

    assert evidence["query_row_count"] == 1
    assert evidence["first_row_keys"] == ["patient_name", "tc_identity", "total"]
    assert "Patient Jane" not in encoded
    assert "12345678901" not in encoded
    assert "rows" not in evidence
    assert evidence["total_duration_seconds"] == 0.125


@pytest.mark.parametrize(
    ("http_result", "error_fragment"),
    [
        (HttpResult(0, {}, 5.0, error="İstek zaman aşımına uğradı"), "zaman aşımı"),
        (HttpResult(500, {"detail": "internal"}, 0.2, error="HTTP 500"), "HTTP 500"),
    ],
)
def test_timeout_and_http_errors_are_critical_failures(
    http_result: HttpResult, error_fragment: str
) -> None:
    scenario = ScenarioCatalog.load(DEFAULT_CATALOG)[0]
    result = SmokeTestRunner(
        "http://localhost:8000", 1.0, "isolated", transport=FakeTransport([http_result])
    ).run([scenario])[0]

    assert result.verdict == Verdict.FAIL
    assert result.assertions[0].severity == Severity.CRITICAL
    assert error_fragment in result.errors[0]


def test_httpx_transport_converts_timeout_to_diagnostic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeHttpxClient.error = httpx.ReadTimeout("slow backend")
    FakeHttpxClient.response = None
    monkeypatch.setattr(httpx, "Client", FakeHttpxClient)

    result = HttpxTransport().post("http://example.test/api/v1/report/", {}, 0.1)

    assert result.status_code == 0
    assert "zaman aşımına" in (result.error or "")
    assert "ReadTimeout" in (result.stack_trace or "")


def test_httpx_transport_preserves_http_error_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeHttpxClient.error = None
    FakeHttpxClient.response = httpx.Response(503, json={"detail": "unavailable"})
    monkeypatch.setattr(httpx, "Client", FakeHttpxClient)

    result = HttpxTransport().post("http://example.test/api/v1/report/", {}, 1.0)

    assert result.status_code == 503
    assert result.error == "HTTP 503"
    assert result.payload == {"detail": "unavailable"}


def test_http_error_secret_is_redacted_before_result_rendering() -> None:
    scenario = ScenarioCatalog.load(DEFAULT_CATALOG)[0]
    error = HttpResult(0, {}, 0.1, error="token=do-not-store")

    result = SmokeTestRunner(
        "http://localhost:8000", 1.0, "isolated", transport=FakeTransport([error])
    ).run([scenario])[0]

    assert "do-not-store" not in json.dumps(result, default=str)


def test_json_csv_markdown_html_and_latest_artifacts(tmp_path: Path) -> None:
    result = _turn_result()

    run_dir = ArtifactWriter().write([result], tmp_path)

    assert run_dir.parent == tmp_path
    for filename in ArtifactWriter.FILENAMES:
        assert (run_dir / filename).is_file()
        assert (tmp_path / "latest" / filename).is_file()
    json_payload = json.loads((run_dir / "smoke_test_results.json").read_text("utf-8"))
    assert json_payload["summary"]["pass"] == 1
    assert json_payload["results"][0]["verdict"] == "PASS"
    csv_text = (run_dir / "smoke_test_results.csv").read_text("utf-8-sig")
    markdown = (run_dir / "smoke_test_report.md").read_text("utf-8")
    html = (run_dir / "smoke_test_summary.html").read_text("utf-8")
    assert "scenario_id" in csv_text and "01_basic_distribution" in csv_text
    assert "# ASM AI Agent Smoke-Test Raporu" in markdown
    assert "SQL ve Oturum Kanıtları" in markdown
    assert '<html lang="tr">' in html
    assert "--bg:#061424" in html
    assert "<details" in html


def test_meeting_preset_and_free_text_filters() -> None:
    scenarios = ScenarioCatalog.load(DEFAULT_CATALOG)

    meeting = filter_scenarios(scenarios, [], "meeting")
    year_only = filter_scenarios(scenarios, ["year-only"], None)

    assert len(meeting) == 6
    assert [scenario.id for scenario in year_only] == ["09_year_only_followup"]
