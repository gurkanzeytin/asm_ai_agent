#!/usr/bin/env python3
"""HTTP smoke/evaluation runner for a running ASM AI Agent backend.

This module is deliberately independent of ``backend/app``.  It observes the
public API and never imports or mutates production workflow components.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import re
import shutil
import sys
import time
import traceback
import uuid
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

import httpx

DEFAULT_BASE_URL = "http://localhost:8000"
DEFAULT_ENDPOINT = "/api/v1/report/"
DEFAULT_CATALOG = Path(__file__).resolve().parents[1] / "tests/evaluation/smoke_scenarios.json"
DEFAULT_OUTPUT_DIR = Path("artifacts/smoke_tests")
MEETING_SCENARIOS = {
    "01_basic_distribution",
    "03_monthly_trend",
    "04_complex_multi_metric",
    "05_grounded_branch",
    "07_additive_followup",
    "09_year_only_followup",
}


class Severity(StrEnum):
    CRITICAL = "CRITICAL"
    MAJOR = "MAJOR"
    MINOR = "MINOR"


class Verdict(StrEnum):
    PASS = "PASS"
    PARTIAL = "PARTIAL"
    FAIL = "FAIL"


@dataclass(frozen=True)
class AssertionSpec:
    kind: str
    expected: Any
    severity: Severity
    message: str
    path: str | None = None


@dataclass(frozen=True)
class Expectations:
    expected_outcome: str | None = None
    expected_analysis_type: str | None = None
    expected_provider: str | None = None
    expected_model_contains: str | None = None
    expected_metrics: tuple[str, ...] = ()
    expected_dimensions: tuple[str, ...] = ()
    expected_context_applied: bool | None = None
    expected_sql_contains: tuple[str, ...] = ()
    forbidden_sql_contains: tuple[str, ...] = ()
    expected_ui_text_contains: tuple[str, ...] = ()
    forbidden_ui_text_contains: tuple[str, ...] = ()
    max_duration_seconds: float | None = None
    assertions: tuple[AssertionSpec, ...] = ()


@dataclass(frozen=True)
class ScenarioTurn:
    question: str
    expectations: Expectations


@dataclass(frozen=True)
class Scenario:
    id: str
    title: str
    category: str
    question: str
    session_group: str
    expected_outcome: str | None
    expected_analysis_type: str | None
    expected_provider: str | None
    expected_model_contains: str | None
    expected_metrics: tuple[str, ...]
    expected_dimensions: tuple[str, ...]
    expected_context_applied: bool | None
    expected_sql_contains: tuple[str, ...]
    forbidden_sql_contains: tuple[str, ...]
    expected_ui_text_contains: tuple[str, ...]
    forbidden_ui_text_contains: tuple[str, ...]
    max_duration_seconds: float | None
    notes: str
    turns: tuple[ScenarioTurn, ...]


@dataclass(frozen=True)
class AssertionResult:
    kind: str
    passed: bool
    severity: Severity
    expected: Any
    actual: Any
    diagnostic: str


@dataclass(frozen=True)
class HttpResult:
    status_code: int
    payload: dict[str, Any]
    elapsed_seconds: float
    error: str | None = None
    stack_trace: str | None = None


@dataclass
class TurnResult:
    timestamp: str
    scenario_id: str
    scenario_title: str
    category: str
    turn_number: int
    question: str
    session_id: str
    http_status: int
    response_outcome: str | None
    report_text: str
    generated_sql: str
    sql_source: str | None
    query_row_count: int | None
    query_columns: list[str]
    first_row_keys: list[str]
    safe_aggregate_summaries: dict[str, Any]
    analytics_type: str | None
    result_shape: str | None
    metric_ids: list[str]
    dimension_ids: list[str]
    context_applied: bool | None
    inherited_fields: list[str]
    provider: str | None
    model: str | None
    fallback_used: bool | None
    total_duration_seconds: float
    stage_timings: dict[str, Any]
    errors: list[str]
    stack_trace: str | None
    assertions: list[AssertionResult]
    verdict: Verdict
    unavailable_fields: list[str] = field(default_factory=list)


class Transport(Protocol):
    def post(self, url: str, payload: dict[str, Any], timeout: float) -> HttpResult: ...


class HttpxTransport:
    """Small HTTP adapter; headers are fixed and never persisted."""

    def post(self, url: str, payload: dict[str, Any], timeout: float) -> HttpResult:
        started = time.perf_counter()
        try:
            with httpx.Client(timeout=timeout) as client:
                response = client.post(url, json=payload)
            elapsed = time.perf_counter() - started
            try:
                body = response.json()
            except (json.JSONDecodeError, ValueError):
                body = {"raw_error": response.text[:2000]}
            if not isinstance(body, dict):
                body = {"response": body}
            error = None if response.is_success else f"HTTP {response.status_code}"
            return HttpResult(response.status_code, body, elapsed, error=error)
        except httpx.TimeoutException as exc:
            elapsed = time.perf_counter() - started
            return HttpResult(
                0,
                {},
                elapsed,
                error=f"İstek zaman aşımına uğradı: {exc}",
                stack_trace=traceback.format_exc(),
            )
        except httpx.HTTPError as exc:
            elapsed = time.perf_counter() - started
            return HttpResult(
                0,
                {},
                elapsed,
                error=f"HTTP bağlantı hatası: {exc}",
                stack_trace=traceback.format_exc(),
            )


class ScenarioCatalog:
    @staticmethod
    def load(path: Path) -> list[Scenario]:
        payload = json.loads(path.read_text(encoding="utf-8"))
        raw_scenarios = payload.get("scenarios")
        if not isinstance(raw_scenarios, list):
            raise ValueError("Senaryo dosyasında 'scenarios' listesi bulunamadı.")
        scenarios = [ScenarioCatalog._parse_scenario(item) for item in raw_scenarios]
        ids = [scenario.id for scenario in scenarios]
        if len(ids) != len(set(ids)):
            raise ValueError("Senaryo kimlikleri benzersiz olmalıdır.")
        return scenarios

    @staticmethod
    def _parse_scenario(raw: dict[str, Any]) -> Scenario:
        required = ("id", "title", "category", "question", "session_group")
        missing = [key for key in required if not raw.get(key)]
        if missing:
            raise ValueError(f"Eksik senaryo alanları: {', '.join(missing)}")
        base = ScenarioCatalog._expectations(raw)
        raw_turns = raw.get("turns") or []
        turns: list[ScenarioTurn] = []
        if raw_turns:
            for raw_turn in raw_turns:
                merged = dict(raw)
                merged.pop("turns", None)
                merged.update(raw_turn)
                turns.append(
                    ScenarioTurn(
                        question=str(raw_turn["question"]),
                        expectations=ScenarioCatalog._expectations(merged),
                    )
                )
        else:
            turns.append(ScenarioTurn(question=str(raw["question"]), expectations=base))
        return Scenario(
            id=str(raw["id"]),
            title=str(raw["title"]),
            category=str(raw["category"]),
            question=str(raw["question"]),
            session_group=str(raw["session_group"]),
            expected_outcome=base.expected_outcome,
            expected_analysis_type=base.expected_analysis_type,
            expected_provider=base.expected_provider,
            expected_model_contains=base.expected_model_contains,
            expected_metrics=base.expected_metrics,
            expected_dimensions=base.expected_dimensions,
            expected_context_applied=base.expected_context_applied,
            expected_sql_contains=base.expected_sql_contains,
            forbidden_sql_contains=base.forbidden_sql_contains,
            expected_ui_text_contains=base.expected_ui_text_contains,
            forbidden_ui_text_contains=base.forbidden_ui_text_contains,
            max_duration_seconds=base.max_duration_seconds,
            notes=str(raw.get("notes") or ""),
            turns=tuple(turns),
        )

    @staticmethod
    def _expectations(raw: dict[str, Any]) -> Expectations:
        assertion_specs = tuple(
            AssertionSpec(
                kind=str(item["kind"]),
                path=item.get("path"),
                expected=item.get("expected"),
                severity=Severity(str(item.get("severity", "MAJOR"))),
                message=str(item.get("message") or item["kind"]),
            )
            for item in raw.get("assertions", [])
        )
        return Expectations(
            expected_outcome=_optional_str(raw.get("expected_outcome")),
            expected_analysis_type=_optional_str(raw.get("expected_analysis_type")),
            expected_provider=_optional_str(raw.get("expected_provider")),
            expected_model_contains=_optional_str(raw.get("expected_model_contains")),
            expected_metrics=tuple(map(str, raw.get("expected_metrics", []))),
            expected_dimensions=tuple(map(str, raw.get("expected_dimensions", []))),
            expected_context_applied=raw.get("expected_context_applied"),
            expected_sql_contains=tuple(map(str, raw.get("expected_sql_contains", []))),
            forbidden_sql_contains=tuple(map(str, raw.get("forbidden_sql_contains", []))),
            expected_ui_text_contains=tuple(map(str, raw.get("expected_ui_text_contains", []))),
            forbidden_ui_text_contains=tuple(map(str, raw.get("forbidden_ui_text_contains", []))),
            max_duration_seconds=(
                float(raw["max_duration_seconds"])
                if raw.get("max_duration_seconds") is not None
                else None
            ),
            assertions=assertion_specs,
        )


class AssertionEngine:
    """Reusable API/UI assertion primitives plus scenario expectation mapping."""

    def evaluate(
        self,
        expectations: Expectations,
        response: dict[str, Any],
        evidence: dict[str, Any],
    ) -> list[AssertionResult]:
        results: list[AssertionResult] = []
        add = results.append
        if expectations.expected_outcome:
            add(
                self.equals(
                    "outcome",
                    evidence.get("response_outcome"),
                    expectations.expected_outcome,
                    Severity.CRITICAL,
                    "Beklenen iş akışı sonucu alınmadı.",
                )
            )
        if expectations.expected_analysis_type:
            add(
                self.equals(
                    "analysis_type",
                    evidence.get("analytics_type"),
                    expectations.expected_analysis_type,
                    Severity.MAJOR,
                    "Analiz tipi beklentiyle eşleşmiyor.",
                )
            )
        if expectations.expected_provider:
            add(
                self.provider_model(
                    response,
                    expectations.expected_provider,
                    expectations.expected_model_contains,
                )
            )
        elif expectations.expected_model_contains:
            add(
                self.contains(
                    "model",
                    evidence.get("model"),
                    expectations.expected_model_contains,
                    Severity.MAJOR,
                    "Model beklentisi karşılanmadı.",
                )
            )
        if expectations.expected_metrics:
            add(
                self.subset(
                    "metrics",
                    evidence.get("metric_ids", []),
                    expectations.expected_metrics,
                    Severity.MAJOR,
                    "Beklenen metriklerin tümü çözümlenmedi.",
                )
            )
        if expectations.expected_dimensions:
            add(
                self.subset(
                    "dimensions",
                    evidence.get("dimension_ids", []),
                    expectations.expected_dimensions,
                    Severity.MAJOR,
                    "Beklenen boyutların tümü çözümlenmedi.",
                )
            )
        if expectations.expected_context_applied is not None:
            add(
                self.boolean(
                    "context_applied",
                    evidence.get("context_applied"),
                    expectations.expected_context_applied,
                    Severity.CRITICAL,
                    "Bağlam uygulama kararı beklentiyle eşleşmiyor.",
                )
            )
        for clause in expectations.expected_sql_contains:
            add(self.sql_clause(evidence.get("generated_sql", ""), clause, True))
        for clause in expectations.forbidden_sql_contains:
            add(self.sql_clause(evidence.get("generated_sql", ""), clause, False))
        for text in expectations.expected_ui_text_contains:
            add(self.visible_text(evidence.get("visible_text", ""), text, True))
        for text in expectations.forbidden_ui_text_contains:
            add(self.visible_text(evidence.get("visible_text", ""), text, False))
        if expectations.max_duration_seconds is not None:
            add(
                self.numeric_threshold(
                    "duration",
                    evidence.get("total_duration_seconds"),
                    expectations.max_duration_seconds,
                    Severity.MAJOR,
                    "Senaryo azami süreyi aştı.",
                )
            )
        for spec in expectations.assertions:
            add(self.custom(spec, response, evidence))
        return results

    def equals(
        self,
        kind: str,
        actual: Any,
        expected: Any,
        severity: Severity,
        message: str,
    ) -> AssertionResult:
        options = _options(expected)
        passed = any(_normalized(actual) == _normalized(option) for option in options)
        return _assertion(kind, passed, severity, expected, actual, message)

    def contains(
        self,
        kind: str,
        actual: Any,
        expected: Any,
        severity: Severity,
        message: str,
    ) -> AssertionResult:
        actual_text = _normalized(actual)
        passed = any(_normalized(option) in actual_text for option in _options(expected))
        return _assertion(kind, passed, severity, expected, actual, message)

    def not_contains(
        self,
        kind: str,
        actual: Any,
        expected: Any,
        severity: Severity,
        message: str,
    ) -> AssertionResult:
        actual_text = _normalized(actual)
        passed = all(_normalized(option) not in actual_text for option in _options(expected))
        return _assertion(kind, passed, severity, expected, actual, message)

    def subset(
        self,
        kind: str,
        actual: Any,
        expected: Any,
        severity: Severity,
        message: str,
    ) -> AssertionResult:
        actual_set = {_normalized(item) for item in (actual or [])}
        expected_set = {_normalized(item) for item in (expected or [])}
        passed = expected_set.issubset(actual_set)
        return _assertion(kind, passed, severity, list(expected or []), list(actual or []), message)

    def numeric_threshold(
        self,
        kind: str,
        actual: Any,
        maximum: float,
        severity: Severity,
        message: str,
    ) -> AssertionResult:
        passed = isinstance(actual, (int, float)) and float(actual) <= maximum
        return _assertion(kind, passed, severity, f"<= {maximum}", actual, message)

    def boolean(
        self,
        kind: str,
        actual: Any,
        expected: bool,
        severity: Severity,
        message: str,
    ) -> AssertionResult:
        return _assertion(kind, actual is expected, severity, expected, actual, message)

    def sql_clause(self, sql: str, clause: str, should_exist: bool) -> AssertionResult:
        actual_sql = _normalize_sql(sql)
        target = _normalize_sql(clause)
        exists = target in actual_sql
        passed = exists if should_exist else not exists
        message = (
            f"SQL beklenen ifadeyi içermiyor: {clause}"
            if should_exist
            else f"SQL yasaklı ifadeyi içeriyor: {clause}"
        )
        return _assertion(
            "sql_clause",
            passed,
            Severity.CRITICAL,
            f"{'contains' if should_exist else 'not_contains'} {clause}",
            sql,
            message,
        )

    def visible_text(self, text: str, expected: str, should_exist: bool) -> AssertionResult:
        exists = _normalized(expected) in _normalized(text)
        passed = exists if should_exist else not exists
        severity = Severity.MINOR
        if not should_exist and any(
            marker in _normalized(expected)
            for marker in (
                "kapsami disinda",
                "kapsamı dışında",
                "kayit sayisi: 1",
                "kayıt sayısı: 1",
            )
        ):
            severity = Severity.CRITICAL
        message = (
            f"Görünür metin beklenen ifadeyi içermiyor: {expected}"
            if should_exist
            else f"Görünür metin yasaklı ifadeyi içeriyor: {expected}"
        )
        return _assertion(
            "visible_text",
            passed,
            severity,
            f"{'contains' if should_exist else 'not_contains'} {expected}",
            text,
            message,
        )

    def provider_model(
        self, response: dict[str, Any], expected_provider: str, expected_model: str | None
    ) -> AssertionResult:
        metadata = _mapping(response.get("metadata"))
        insights = _mapping(response.get("insights"))
        candidates = [
            insights.get("provider"),
            insights.get("routing_mode"),
            metadata.get("provider"),
        ]
        provider_passed = any(
            self.contains("provider", candidate, expected_provider, Severity.MAJOR, "").passed
            for candidate in candidates
            if candidate
        )
        models = [insights.get("model"), metadata.get("model")]
        model_passed = not expected_model or any(
            self.contains("model", candidate, expected_model, Severity.MAJOR, "").passed
            for candidate in models
            if candidate
        )
        return _assertion(
            "provider_model",
            provider_passed and model_passed,
            Severity.MAJOR,
            {"provider": expected_provider, "model_contains": expected_model},
            {"providers": candidates, "models": models},
            "Provider veya model yönlendirmesi beklentiyle eşleşmiyor.",
        )

    def context_inheritance(
        self,
        response: dict[str, Any],
        expected_fields: list[str],
        message: str,
        expected_outcomes: list[str] | None = None,
    ) -> AssertionResult:
        fields = {
            _context_family(field)
            for field in (
                list(response.get("inherited_fields") or [])
                + list(response.get("inherited_context_fields") or [])
            )
        }
        required = {_context_family(field) for field in expected_fields}
        family_proof = required.issubset(fields)
        raw_question = str(response.get("raw_question") or response.get("question") or "")
        resolved_question = str(response.get("resolved_question") or "")
        explicit_merge_proof = any(
            response.get(field) is True
            for field in ("merge_applied", "context_merge_applied", "signals_merged")
        ) or (
            response.get("follow_up_detected") is True
            and bool(raw_question)
            and bool(resolved_question)
            and _normalized(raw_question) != _normalized(resolved_question)
        )
        allowed_outcomes = expected_outcomes or ["EXECUTE_SQL"]
        outcome_ok = _normalized(response.get("outcome")) in {
            _normalized(outcome) for outcome in allowed_outcomes
        }
        passed = (
            response.get("context_applied") is True
            and (family_proof or explicit_merge_proof)
            and outcome_ok
        )
        return _assertion(
            "context_inheritance",
            passed,
            Severity.CRITICAL,
            {
                "context_applied": True,
                "families_or_explicit_merge": sorted(required),
                "outcomes": allowed_outcomes,
            },
            {
                "context_applied": response.get("context_applied"),
                "inherited_families": sorted(fields),
                "explicit_merge_proof": explicit_merge_proof,
                "outcome": response.get("outcome"),
            },
            message,
        )

    def custom(
        self, spec: AssertionSpec, response: dict[str, Any], evidence: dict[str, Any]
    ) -> AssertionResult:
        actual = _get_path(response, spec.path) if spec.path else None
        if spec.kind == "equals_path":
            return self.equals(spec.kind, actual, spec.expected, spec.severity, spec.message)
        if spec.kind == "contains_path":
            return self.contains(spec.kind, actual, spec.expected, spec.severity, spec.message)
        if spec.kind == "not_contains_path":
            return self.not_contains(spec.kind, actual, spec.expected, spec.severity, spec.message)
        if spec.kind == "nonempty_path":
            return _assertion(
                spec.kind, bool(actual), spec.severity, spec.expected, actual, spec.message
            )
        if spec.kind == "result_shape_in":
            actual = evidence.get("result_shape")
            passed = _normalized(actual) in {_normalized(item) for item in spec.expected}
            return _assertion(spec.kind, passed, spec.severity, spec.expected, actual, spec.message)
        if spec.kind == "context_inheritance":
            config = spec.expected if isinstance(spec.expected, dict) else {}
            fields = config.get("families", []) if config else spec.expected
            outcomes = config.get("outcomes") if config else None
            return self.context_inheritance(
                response,
                list(fields),
                spec.message,
                list(outcomes) if outcomes else None,
            )
        if spec.kind == "sql_today_range":
            sql = evidence.get("generated_sql", "")
            today = date.today().isoformat()
            normalized = _normalize_sql(sql)
            passed = (today in sql or "getdate()" in normalized) and ">=" in sql and "<" in sql
            return _assertion(spec.kind, passed, spec.severity, True, sql, spec.message)
        if spec.kind == "sql_recent_day_window":
            sql = evidence.get("generated_sql", "")
            days = int(spec.expected)
            windows = _sql_calendar_windows(sql)
            matching = [window for window in windows if window["days"] == days]
            return _assertion(
                spec.kind,
                bool(matching),
                spec.severity,
                {"covered_calendar_dates": days, "bounds": ">= start AND < end_exclusive"},
                {"windows": windows, "sql": sql},
                spec.message,
            )
        if spec.kind == "sql_year_window":
            sql = evidence.get("generated_sql", "")
            year = int(spec.expected)
            expected_start = date(year, 1, 1)
            expected_end = date(year + 1, 1, 1)
            windows = _sql_calendar_windows(sql)
            matching = [
                window
                for window in windows
                if window["start"] == expected_start.isoformat()
                and window["end_exclusive"] == expected_end.isoformat()
            ]
            return _assertion(
                spec.kind,
                bool(matching),
                spec.severity,
                {
                    "start": expected_start.isoformat(),
                    "end_exclusive": expected_end.isoformat(),
                },
                {"windows": windows, "sql": sql},
                spec.message,
            )
        if spec.kind == "no_contradictory_trend_rules":
            rules = set(_mapping(response.get("insights")).get("rules") or [])
            contradictory = {
                "CONSISTENT_UPWARD_TREND",
                "CONSISTENT_DOWNWARD_TREND",
            }.issubset(rules)
            return _assertion(
                spec.kind, not contradictory, spec.severity, True, sorted(rules), spec.message
            )
        if spec.kind == "trend_language_consistency":
            values = _trend_values(response, spec.expected)
            visible = _normalized(evidence.get("visible_text", ""))
            forbidden_claims = _continuous_growth_claims(visible)
            strictly_increasing = len(values) >= 2 and all(
                current > previous for previous, current in zip(values, values[1:], strict=False)
            )
            passed = not forbidden_claims or strictly_increasing
            return _assertion(
                spec.kind,
                passed,
                Severity.CRITICAL,
                "Sürekli yükseliş iddiası yalnızca her komşu dönem arttığında kullanılmalı",
                {
                    "values": values,
                    "strictly_increasing": strictly_increasing,
                    "forbidden_claims": forbidden_claims,
                },
                spec.message,
            )
        if spec.kind == "partial_period_disclosed":
            analytics = _mapping(response.get("analytics"))
            metrics = _mapping(analytics.get("metrics"))
            applicable = bool(metrics.get("comparison_excluded_partial_period"))
            visible = _normalized(evidence.get("visible_text", ""))
            passed = not applicable or any(
                marker in visible for marker in ("tamamlan", "kismi donem", "kısmi dönem")
            )
            return _assertion(
                spec.kind,
                passed,
                spec.severity,
                "Kısmi dönem varsa açıklama",
                {"applicable": applicable, "visible_text": visible},
                spec.message,
            )
        if spec.kind == "turkish_report_title":
            title = str(_mapping(response.get("report")).get("title") or "")
            english_markers = ("report", "analysis", "result", "summary", "appointment")
            passed = bool(title) and not any(
                re.search(rf"\b{marker}\b", title, re.IGNORECASE) for marker in english_markers
            )
            return _assertion(spec.kind, passed, spec.severity, True, title, spec.message)
        if spec.kind == "concise_turkish_guidance":
            visible = str(evidence.get("visible_text") or "").strip()
            normalized = _normalized(visible)
            guidance_terms = ("destek", "kapsam", "veri", "randevu", "soru")
            passed = (
                bool(visible)
                and len(visible) <= int(spec.expected)
                and any(term in normalized for term in guidance_terms)
            )
            return _assertion(
                spec.kind,
                passed,
                spec.severity,
                f"Türkçe yönlendirme, en çok {spec.expected} karakter",
                visible,
                spec.message,
            )
        return _assertion(
            spec.kind,
            False,
            spec.severity,
            spec.expected,
            actual,
            f"Bilinmeyen assertion türü: {spec.kind}",
        )


def classify_assertions(assertions: list[AssertionResult]) -> Verdict:
    failed = [item for item in assertions if not item.passed]
    critical = sum(item.severity == Severity.CRITICAL for item in failed)
    major = sum(item.severity == Severity.MAJOR for item in failed)
    minor = sum(item.severity == Severity.MINOR for item in failed)
    if critical or major >= 2:
        return Verdict.FAIL
    if major == 1 or minor:
        return Verdict.PARTIAL
    return Verdict.PASS


class SmokeTestRunner:
    def __init__(
        self,
        base_url: str,
        timeout: float,
        session_mode: str,
        transport: Transport | None = None,
        assertion_engine: AssertionEngine | None = None,
    ) -> None:
        self.url = f"{base_url.rstrip('/')}{DEFAULT_ENDPOINT}"
        self.timeout = timeout
        self.session_mode = session_mode
        self.transport = transport or HttpxTransport()
        self.assertions = assertion_engine or AssertionEngine()
        self._sessions: dict[str, str] = {}

    def run(self, scenarios: list[Scenario]) -> list[TurnResult]:
        results: list[TurnResult] = []
        for scenario in scenarios:
            session_key = scenario.session_group if self.session_mode == "grouped" else scenario.id
            session_id = self._sessions.setdefault(session_key, str(uuid.uuid4()))
            for turn_number, turn in enumerate(scenario.turns, start=1):
                http_result = self.transport.post(
                    self.url,
                    {"question": turn.question, "session_id": session_id},
                    self.timeout,
                )
                response = redact_secrets(http_result.payload)
                returned_session = response.get("session_id")
                if isinstance(returned_session, str) and returned_session:
                    session_id = returned_session
                    self._sessions[session_key] = session_id
                result = self._build_result(
                    scenario, turn, turn_number, session_id, http_result, response
                )
                results.append(result)
        return results

    def _build_result(
        self,
        scenario: Scenario,
        turn: ScenarioTurn,
        turn_number: int,
        session_id: str,
        http_result: HttpResult,
        response: dict[str, Any],
    ) -> TurnResult:
        evidence = extract_evidence(response, http_result.elapsed_seconds)
        assertion_results: list[AssertionResult] = []
        safe_http_error = str(redact_secrets(http_result.error)) if http_result.error else None
        if http_result.error:
            assertion_results.append(
                _assertion(
                    "http_request",
                    False,
                    Severity.CRITICAL,
                    "HTTP 2xx JSON response",
                    {"status": http_result.status_code, "error": safe_http_error},
                    "Backend isteği tamamlanamadı.",
                )
            )
        else:
            assertion_results.extend(
                self.assertions.evaluate(turn.expectations, response, evidence)
            )
        server_trace = _find_stack_trace(response)
        errors = list(map(str, response.get("errors") or []))
        if safe_http_error:
            errors.append(safe_http_error)
        unavailable = []
        if response.get("sql_source") is None:
            unavailable.append("sql_source")
        if server_trace is None:
            unavailable.append("server_stack_trace")
        return TurnResult(
            timestamp=datetime.now().astimezone().isoformat(timespec="seconds"),
            scenario_id=scenario.id,
            scenario_title=scenario.title,
            category=scenario.category,
            turn_number=turn_number,
            question=turn.question,
            session_id=session_id,
            http_status=http_result.status_code,
            response_outcome=evidence["response_outcome"],
            report_text=evidence["report_text"],
            generated_sql=evidence["generated_sql"],
            sql_source=response.get("sql_source"),
            query_row_count=evidence["query_row_count"],
            query_columns=evidence["query_columns"],
            first_row_keys=evidence["first_row_keys"],
            safe_aggregate_summaries=evidence["safe_aggregate_summaries"],
            analytics_type=evidence["analytics_type"],
            result_shape=evidence["result_shape"],
            metric_ids=evidence["metric_ids"],
            dimension_ids=evidence["dimension_ids"],
            context_applied=evidence["context_applied"],
            inherited_fields=evidence["inherited_fields"],
            provider=evidence["provider"],
            model=evidence["model"],
            fallback_used=evidence["fallback_used"],
            total_duration_seconds=evidence["total_duration_seconds"],
            stage_timings=evidence["stage_timings"],
            errors=errors,
            stack_trace=redact_secrets(server_trace or http_result.stack_trace),
            assertions=assertion_results,
            verdict=classify_assertions(assertion_results),
            unavailable_fields=unavailable,
        )


def extract_evidence(response: dict[str, Any], elapsed_seconds: float) -> dict[str, Any]:
    query = _mapping(response.get("query_result"))
    analytics = _mapping(response.get("analytics"))
    report = _mapping(response.get("report"))
    metadata = _mapping(response.get("metadata"))
    insights = _mapping(response.get("insights"))
    timings = _mapping(response.get("timing"))
    rows = query.get("rows") if isinstance(query.get("rows"), list) else []
    first_row_keys = sorted(rows[0].keys()) if rows and isinstance(rows[0], dict) else []
    displayable = analytics.get("displayable_kpis")
    if not isinstance(displayable, list):
        displayable = []
    metric_ids = _dedupe(
        list(response.get("resolved_metrics") or [])
        + [item.get("key") for item in displayable if isinstance(item, dict)]
        + list(_mapping(analytics.get("metric_summaries")).keys())
    )
    dimension_ids = _dedupe(list(response.get("resolved_dimensions") or []))
    safe_metrics = {
        key: value
        for key, value in _mapping(analytics.get("metrics")).items()
        if value is None or isinstance(value, (str, int, float, bool))
    }
    safe_kpis = [
        {key: item.get(key) for key in ("key", "label", "value", "format", "unit") if key in item}
        for item in displayable
        if isinstance(item, dict)
    ]
    report_text = str(report.get("markdown") or "")
    visible_parts = [report_text]
    for item in safe_kpis:
        visible_parts.append(f"{item.get('label', '')}: {item.get('value', '')}")
    visible_parts.extend(
        str(value) for key in ("summary", "title") if (value := insights.get(key)) is not None
    )
    for key in ("highlights", "observations", "considerations"):
        values = insights.get(key)
        if isinstance(values, list):
            visible_parts.extend(map(str, values))
    provider = insights.get("provider") or insights.get("routing_mode") or metadata.get("provider")
    model = insights.get("model") or metadata.get("model")
    total_ms = timings.get("total_ms")
    duration = (
        float(total_ms) / 1000
        if isinstance(total_ms, (int, float)) and total_ms > 0
        else elapsed_seconds
    )
    inherited = _dedupe(
        list(response.get("inherited_fields") or [])
        + list(response.get("inherited_context_fields") or [])
    )
    return {
        "response_outcome": response.get("outcome"),
        "report_text": report_text,
        "visible_text": "\n".join(visible_parts),
        "generated_sql": str(response.get("generated_sql") or ""),
        "query_row_count": query.get("row_count"),
        "query_columns": list(map(str, query.get("columns") or [])),
        "first_row_keys": first_row_keys,
        "safe_aggregate_summaries": {"metrics": safe_metrics, "kpis": safe_kpis},
        "analytics_type": analytics.get("analytics_type"),
        "result_shape": analytics.get("result_shape") or analytics.get("data_shape"),
        "metric_ids": metric_ids,
        "dimension_ids": dimension_ids,
        "context_applied": response.get("context_applied"),
        "inherited_fields": inherited,
        "provider": provider,
        "model": model,
        "fallback_used": insights.get("fallback_used"),
        "total_duration_seconds": round(duration, 4),
        "stage_timings": timings,
    }


_SENSITIVE_KEYS = {
    "authorization",
    "api_key",
    "apikey",
    "password",
    "secret",
    "access_token",
    "refresh_token",
    "connection_string",
}
_SENSITIVE_PATTERNS = (
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+"),
    re.compile(r"(?i)\b(password|pwd|api[_-]?key|secret|token)\s*[=:]\s*[^;\s]+"),
    re.compile(r"(?i)(https?://[^:/\s]+:)[^@/\s]+@"),
)


def redact_secrets(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]" if str(key).lower() in _SENSITIVE_KEYS else redact_secrets(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_secrets(item) for item in value)
    if isinstance(value, str):
        redacted = value
        for pattern in _SENSITIVE_PATTERNS:
            if pattern.pattern.startswith("(?i)(https?"):
                redacted = pattern.sub(r"\1[REDACTED]@", redacted)
            else:
                redacted = pattern.sub("[REDACTED]", redacted)
        return redacted
    return value


class ArtifactWriter:
    FILENAMES = (
        "smoke_test_results.json",
        "smoke_test_results.csv",
        "smoke_test_report.md",
        "smoke_test_summary.html",
    )

    def write(self, results: list[TurnResult], output_root: Path) -> Path:
        stamp = datetime.now().astimezone().strftime("%Y-%m-%d_%H%M%S")
        run_dir = output_root / stamp
        suffix = 1
        while run_dir.exists():
            run_dir = output_root / f"{stamp}_{suffix:02d}"
            suffix += 1
        run_dir.mkdir(parents=True)
        self.write_json(results, run_dir / self.FILENAMES[0])
        self.write_csv(results, run_dir / self.FILENAMES[1])
        self.write_markdown(results, run_dir / self.FILENAMES[2])
        self.write_html(results, run_dir / self.FILENAMES[3])
        latest = output_root / "latest"
        latest.mkdir(parents=True, exist_ok=True)
        for filename in self.FILENAMES:
            shutil.copy2(run_dir / filename, latest / filename)
        return run_dir

    def write_json(self, results: list[TurnResult], path: Path) -> None:
        payload = {
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "summary": summarize(results),
            "results": [_serializable_result(result) for result in results],
        }
        path.write_text(
            json.dumps(redact_secrets(payload), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def write_csv(self, results: list[TurnResult], path: Path) -> None:
        fields = [
            "timestamp",
            "scenario_id",
            "scenario_title",
            "category",
            "turn_number",
            "question",
            "session_id",
            "http_status",
            "response_outcome",
            "report_text",
            "generated_sql",
            "sql_source",
            "query_row_count",
            "query_columns",
            "first_row_keys",
            "safe_aggregate_summaries",
            "analytics_type",
            "result_shape",
            "metric_ids",
            "dimension_ids",
            "context_applied",
            "inherited_fields",
            "provider",
            "model",
            "fallback_used",
            "total_duration_seconds",
            "stage_timings",
            "errors",
            "stack_trace",
            "unavailable_fields",
            "verdict",
            "validation_assertions",
            "failed_assertions",
        ]
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for result in results:
                writer.writerow(
                    {
                        key: _csv_value(value)
                        for key, value in {
                            "timestamp": result.timestamp,
                            "scenario_id": result.scenario_id,
                            "scenario_title": result.scenario_title,
                            "category": result.category,
                            "turn_number": result.turn_number,
                            "question": result.question,
                            "session_id": result.session_id,
                            "http_status": result.http_status,
                            "response_outcome": result.response_outcome,
                            "report_text": result.report_text,
                            "generated_sql": result.generated_sql,
                            "sql_source": result.sql_source,
                            "query_row_count": result.query_row_count,
                            "query_columns": result.query_columns,
                            "first_row_keys": result.first_row_keys,
                            "safe_aggregate_summaries": result.safe_aggregate_summaries,
                            "analytics_type": result.analytics_type,
                            "result_shape": result.result_shape,
                            "metric_ids": result.metric_ids,
                            "dimension_ids": result.dimension_ids,
                            "context_applied": result.context_applied,
                            "inherited_fields": result.inherited_fields,
                            "provider": result.provider,
                            "model": result.model,
                            "fallback_used": result.fallback_used,
                            "total_duration_seconds": result.total_duration_seconds,
                            "stage_timings": result.stage_timings,
                            "errors": result.errors,
                            "stack_trace": result.stack_trace,
                            "unavailable_fields": result.unavailable_fields,
                            "verdict": result.verdict.value,
                            "validation_assertions": [asdict(item) for item in result.assertions],
                            "failed_assertions": [
                                item.diagnostic for item in result.assertions if not item.passed
                            ],
                        }.items()
                    }
                )

    def write_markdown(self, results: list[TurnResult], path: Path) -> None:
        summary = summarize(results)
        verdict_totals = f"{summary['pass']} / {summary['partial']} / {summary['fail']}"
        lines = [
            "# ASM AI Agent Smoke-Test Raporu",
            "",
            f"- Oluşturulma: {datetime.now().astimezone().isoformat(timespec='seconds')}",
            f"- Senaryo: {summary['scenario_count']}",
            f"- Tur: {summary['turn_count']}",
            f"- Başarı oranı: %{summary['pass_rate']:.1f}",
            f"- PASS / PARTIAL / FAIL: {verdict_totals}",
            f"- Ortalama süre: {summary['average_duration_seconds']:.2f} sn",
            "",
            "## Sonuçlar",
            "",
            "| Test | Kategori | Tur | Sonuç | Provider | Süre | Kritik sorun |",
            "|---|---|---:|---|---|---:|---|",
        ]
        for result in results:
            lines.append(
                f"| {result.scenario_id} — {result.scenario_title} | {result.category} | "
                f"{result.turn_number} | {result.verdict.value} | {result.provider or '-'} | "
                f"{result.total_duration_seconds:.2f} sn | {_critical_issue(result)} |"
            )
        lines.extend(["", "## Kategori Dağılımı", ""])
        for category, counts in summary["category_breakdown"].items():
            lines.append(
                f"- **{category}:** PASS {counts.get('PASS', 0)}, "
                f"PARTIAL {counts.get('PARTIAL', 0)}, FAIL {counts.get('FAIL', 0)}"
            )
        lines.extend(["", "## Provider Kullanımı", ""])
        for provider, count in summary["provider_breakdown"].items():
            lines.append(f"- **{provider}:** {count} tur")
        lines.extend(["", "## En Yavaş Senaryolar", ""])
        for item in summary["slowest"]:
            lines.append(
                f"- {item['scenario_id']} / tur {item['turn_number']}: "
                f"{item['duration_seconds']:.2f} sn"
            )
        lines.extend(["", "## Başarısız Assertion'lar", ""])
        failed_any = False
        for result in results:
            for assertion in result.assertions:
                if assertion.passed:
                    continue
                failed_any = True
                lines.append(
                    f"- **{result.scenario_id} / tur {result.turn_number} / "
                    f"{assertion.severity.value}:** {assertion.diagnostic} "
                    f"(beklenen: `{_short(assertion.expected)}`, "
                    f"gerçek: `{_short(assertion.actual)}`)"
                )
        if not failed_any:
            lines.append("- Başarısız assertion yok.")
        lines.extend(["", "## SQL ve Oturum Kanıtları", ""])
        for result in results:
            lines.extend(
                [
                    f"### {result.scenario_id} / Tur {result.turn_number}",
                    "",
                    f"- Oturum: `{result.session_id}`",
                    f"- Bağlam uygulandı: `{result.context_applied}`",
                    f"- Devralınan alanlar: `{', '.join(result.inherited_fields) or '-'}`",
                    f"- Satır / sütun: `{result.query_row_count}` / "
                    f"`{', '.join(result.query_columns) or '-'}`",
                    "",
                    "```sql",
                    result.generated_sql[:4000] or "-- SQL üretilmedi",
                    "```",
                    "",
                ]
            )
        lines.extend(["## Yerelleştirme ve Risk Özeti", ""])
        localization = [
            item
            for result in results
            for item in result.assertions
            if not item.passed and item.severity == Severity.MINOR
        ]
        lines.append(f"- Yerelleştirme/sunum bulgusu: {len(localization)}")
        lines.append(f"- Kritik başarısızlık: {summary['critical_failures']}")
        lines.append(f"- Major başarısızlık: {summary['major_failures']}")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def write_html(self, results: list[TurnResult], path: Path) -> None:
        summary = summarize(results)
        cards = []
        for result in results:
            failed = [item for item in result.assertions if not item.passed]
            provider_model = (
                f"{html.escape(result.provider or '-')} / {html.escape(result.model or '-')}"
            )
            sql_html = html.escape(result.generated_sql[:6000] or "-- SQL üretilmedi")
            report_html = html.escape(result.report_text[:6000] or "—")
            failed_html = (
                "".join(
                    f"<li><b>{html.escape(item.severity.value)}</b> — "
                    f"{html.escape(item.diagnostic)}<br><small>Beklenen: "
                    f"{html.escape(_short(item.expected))} · Gerçek: "
                    f"{html.escape(_short(item.actual))}</small></li>"
                    for item in failed
                )
                or "<li>Başarısız assertion yok.</li>"
            )
            cards.append(
                f"""
<details class="result {result.verdict.value.lower()}">
  <summary><span>{html.escape(result.scenario_id)} · {html.escape(result.scenario_title)}</span>
    <b>{result.verdict.value}</b></summary>
  <div class="grid">
    <div><label>Kategori</label>{html.escape(result.category)}</div>
    <div><label>Tur</label>{result.turn_number}</div>
    <div><label>Provider / Model</label>{provider_model}</div>
    <div><label>Süre</label>{result.total_duration_seconds:.2f} sn</div>
    <div><label>Outcome</label>{html.escape(result.response_outcome or "-")}</div>
    <div><label>Sonuç şekli</label>{html.escape(result.result_shape or "-")}</div>
  </div>
  <p><b>Soru:</b> {html.escape(result.question)}</p>
  <p><b>Oturum:</b> <code>{html.escape(result.session_id)}</code> ·
     <b>Bağlam:</b> {html.escape(str(result.context_applied))}</p>
  <h4>Başarısız Assertion'lar</h4><ul>{failed_html}</ul>
  <h4>SQL</h4><pre><code>{sql_html}</code></pre>
  <h4>Görünür Rapor</h4><pre>{report_html}</pre>
</details>"""
            )
        generated_at = html.escape(datetime.now().astimezone().isoformat(timespec="seconds"))
        category_summary = "".join(
            "<li><b>"
            f"{html.escape(category)}</b>: PASS {counts.get('PASS', 0)}, "
            f"PARTIAL {counts.get('PARTIAL', 0)}, FAIL {counts.get('FAIL', 0)}</li>"
            for category, counts in summary["category_breakdown"].items()
        )
        provider_summary = "".join(
            f"<li><b>{html.escape(provider)}</b>: {count} tur</li>"
            for provider, count in summary["provider_breakdown"].items()
        )
        slowest_summary = "".join(
            f"<li>{html.escape(item['scenario_id'])} / tur {item['turn_number']}: "
            f"{item['duration_seconds']:.2f} sn</li>"
            for item in summary["slowest"]
        )
        document = f"""<!doctype html>
<html lang="tr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>ASM AI Agent Smoke-Test Özeti</title>
<style>
:root{{--bg:#061424;--panel:#0b2035;--line:#173d58;--text:#d9f2f2;--muted:#8eb3bd;
--blue:#38bdf8;--cyan:#2dd4bf;--pass:#22c55e;--partial:#f59e0b;--fail:#ef4444}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--text);
font:14px/1.55 system-ui,sans-serif}}
main{{max-width:1180px;margin:auto;padding:32px 20px 64px}} h1{{color:var(--cyan);margin:0 0 8px}}
.muted,label,small{{color:var(--muted)}}
.stats{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
gap:12px;margin:24px 0}}
.stat,.result{{background:var(--panel);border:1px solid var(--line);
border-radius:12px}}
.stat{{padding:16px}} .stat b{{display:block;font-size:24px;color:var(--blue)}}
.result{{margin:12px 0;overflow:hidden}}
summary{{display:flex;justify-content:space-between;gap:16px;
padding:16px;cursor:pointer}}
.pass summary b{{color:var(--pass)}} .partial summary b{{color:var(--partial)}}
.fail summary b{{color:var(--fail)}}
.result>div,.result>p,.result>h4,.result>ul,.result>pre{{margin-left:16px;margin-right:16px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));
gap:10px;padding:12px;background:#081a2b;border-radius:8px}}
.grid label{{display:block;font-size:11px;text-transform:uppercase}}
pre{{white-space:pre-wrap;overflow:auto;background:#03101d;
border:1px solid var(--line);padding:14px;border-radius:8px;color:#b9f5e8}}
code{{color:#7dd3fc}} ul{{padding-bottom:10px}}
.overview{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px}}
.overview article{{background:var(--panel);border:1px solid var(--line);
border-radius:12px;padding:0 16px}}
</style></head><body><main>
<h1>ASM AI Agent Smoke-Test Özeti</h1>
<div class="muted">{generated_at}</div>
<section class="stats">
 <div class="stat"><span>Başarı oranı</span><b>%{summary["pass_rate"]:.1f}</b></div>
 <div class="stat"><span>PASS</span><b style="color:var(--pass)">{summary["pass"]}</b></div>
 <div class="stat"><span>PARTIAL</span>
  <b style="color:var(--partial)">{summary["partial"]}</b></div>
 <div class="stat"><span>FAIL</span><b style="color:var(--fail)">{summary["fail"]}</b></div>
 <div class="stat"><span>Ortalama süre</span><b>{summary["average_duration_seconds"]:.2f}s</b></div>
</section>
<section class="overview">
 <article><h3>Kategori Dağılımı</h3><ul>{category_summary}</ul></article>
 <article><h3>Provider Kullanımı</h3><ul>{provider_summary}</ul></article>
 <article><h3>En Yavaş Senaryolar</h3><ul>{slowest_summary}</ul></article>
 <article><h3>Risk Özeti</h3><ul>
  <li>Kritik başarısızlık: {summary["critical_failures"]}</li>
  <li>Major başarısızlık: {summary["major_failures"]}</li>
  <li>Başarısız tur: {summary["fail"]}</li>
 </ul></article>
</section>
<h2>Senaryo Ayrıntıları</h2>{"".join(cards)}
</main></body></html>"""
        path.write_text(document, encoding="utf-8")


def summarize(results: list[TurnResult]) -> dict[str, Any]:
    verdicts = Counter(result.verdict.value for result in results)
    categories: dict[str, Counter[str]] = defaultdict(Counter)
    providers = Counter(result.provider or "bilinmiyor" for result in results)
    for result in results:
        categories[result.category][result.verdict.value] += 1
    pass_count = verdicts[Verdict.PASS.value]
    return {
        "scenario_count": len({result.scenario_id for result in results}),
        "turn_count": len(results),
        "pass": pass_count,
        "partial": verdicts[Verdict.PARTIAL.value],
        "fail": verdicts[Verdict.FAIL.value],
        "pass_rate": (pass_count / len(results) * 100) if results else 0.0,
        "average_duration_seconds": (
            sum(result.total_duration_seconds for result in results) / len(results)
            if results
            else 0.0
        ),
        "category_breakdown": {
            category: dict(counts) for category, counts in sorted(categories.items())
        },
        "provider_breakdown": dict(providers.most_common()),
        "slowest": [
            {
                "scenario_id": result.scenario_id,
                "turn_number": result.turn_number,
                "duration_seconds": result.total_duration_seconds,
            }
            for result in sorted(
                results, key=lambda item: item.total_duration_seconds, reverse=True
            )[:5]
        ],
        "critical_failures": sum(
            not assertion.passed and assertion.severity == Severity.CRITICAL
            for result in results
            for assertion in result.assertions
        ),
        "major_failures": sum(
            not assertion.passed and assertion.severity == Severity.MAJOR
            for result in results
            for assertion in result.assertions
        ),
    }


def print_terminal_summary(results: list[TurnResult]) -> None:
    print("\nTest | Kategori | Sonuç | Provider | Süre | Kritik sorun")
    print("-" * 96)
    scenario_results: dict[str, list[TurnResult]] = defaultdict(list)
    for result in results:
        scenario_results[result.scenario_id].append(result)
    for index, scenario_id in enumerate(scenario_results, start=1):
        turns = scenario_results[scenario_id]
        verdict = _worst_verdict([turn.verdict for turn in turns])
        provider = next((turn.provider for turn in reversed(turns) if turn.provider), "-")
        duration = sum(turn.total_duration_seconds for turn in turns)
        issue = next(
            (
                assertion.diagnostic
                for turn in turns
                for assertion in turn.assertions
                if not assertion.passed and assertion.severity == Severity.CRITICAL
            ),
            "-",
        )
        print(
            f"{index:02d} | {turns[0].category[:18]:18} | {verdict.value:7} | "
            f"{provider[:15]:15} | {duration:6.2f}s | {issue[:45]}"
        )


def filter_scenarios(
    scenarios: list[Scenario], filters: list[str], preset: str | None
) -> list[Scenario]:
    selected = scenarios
    if preset == "meeting":
        selected = [scenario for scenario in selected if scenario.id in MEETING_SCENARIOS]
    tokens = [
        token.strip().casefold().replace("-", "_")
        for raw_filter in filters
        for token in raw_filter.split(",")
        if token.strip()
    ]
    if tokens:
        selected = [
            scenario
            for scenario in selected
            if any(
                token
                in " ".join(
                    (scenario.id, scenario.title, scenario.category, scenario.session_group)
                )
                .casefold()
                .replace("-", "_")
                for token in tokens
            )
        ]
    return selected


def _serializable_result(result: TurnResult) -> dict[str, Any]:
    value = asdict(result)
    value["verdict"] = result.verdict.value
    for assertion in value["assertions"]:
        assertion["severity"] = str(assertion["severity"])
    return value


def _assertion(
    kind: str,
    passed: bool,
    severity: Severity,
    expected: Any,
    actual: Any,
    message: str,
) -> AssertionResult:
    diagnostic = "Beklenti karşılandı." if passed else message
    return AssertionResult(kind, passed, severity, expected, actual, diagnostic)


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _get_path(payload: dict[str, Any], path: str | None) -> Any:
    current: Any = payload
    for part in (path or "").split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _find_stack_trace(payload: Any) -> str | None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key.casefold() in {"stack_trace", "stacktrace", "traceback"} and value:
                return str(value)
            found = _find_stack_trace(value)
            if found:
                return found
    elif isinstance(payload, list):
        for item in payload:
            found = _find_stack_trace(item)
            if found:
                return found
    return None


def _options(value: Any) -> list[Any]:
    if isinstance(value, str) and "|" in value:
        return [item.strip() for item in value.split("|") if item.strip()]
    return list(value) if isinstance(value, (list, tuple, set)) else [value]


def _normalized(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        return " ".join(map(str, value)).casefold()
    return str(value).strip().casefold()


def _normalize_sql(value: str) -> str:
    cleaned = re.sub(r"[\[\]`\"]", "", value or "")
    return re.sub(r"\s+", " ", cleaned).strip().casefold()


_SQL_DATE_COMPARISON = re.compile(
    r"(?P<column>(?:\[[^\]]+\]|[A-Za-z_][\w]*)(?:\s*\.\s*"
    r"(?:\[[^\]]+\]|[A-Za-z_][\w]*))*)\s*(?P<operator>>=|<(?![=>]))",
    re.IGNORECASE,
)


def _sql_calendar_windows(sql: str) -> list[dict[str, Any]]:
    """Return semantic half-open date windows found in SQL predicates."""
    comparisons: list[tuple[str, str, date]] = []
    for match in _SQL_DATE_COMPARISON.finditer(sql or ""):
        expression = _read_sql_expression(sql, match.end())
        parsed_date = _parse_sql_date_expression(expression)
        if parsed_date is None:
            continue
        column = re.sub(r"[\[\]\s]", "", match.group("column")).casefold()
        comparisons.append((column, match.group("operator"), parsed_date))

    windows: list[dict[str, Any]] = []
    for lower_column, lower_operator, start in comparisons:
        if lower_operator != ">=":
            continue
        for upper_column, upper_operator, end_exclusive in comparisons:
            if upper_operator != "<" or upper_column != lower_column:
                continue
            covered_days = (end_exclusive - start).days
            if covered_days <= 0:
                continue
            window = {
                "column": lower_column,
                "start": start.isoformat(),
                "end_exclusive": end_exclusive.isoformat(),
                "days": covered_days,
            }
            if window not in windows:
                windows.append(window)
    return windows


def _read_sql_expression(sql: str, start: int) -> str:
    index = start
    while index < len(sql) and sql[index].isspace():
        index += 1
    expression_start = index
    if index < len(sql) and sql[index] in "Nn" and index + 1 < len(sql):
        if sql[index + 1] == "'":
            index += 1
    if index < len(sql) and sql[index] == "'":
        index += 1
        while index < len(sql):
            if sql[index] == "'":
                if index + 1 < len(sql) and sql[index + 1] == "'":
                    index += 2
                    continue
                return sql[expression_start : index + 1]
            index += 1
        return sql[expression_start:index]

    identifier = re.match(r"[A-Za-z_][\w]*", sql[index:])
    if not identifier:
        return ""
    index += identifier.end()
    while index < len(sql) and sql[index].isspace():
        index += 1
    if index >= len(sql) or sql[index] != "(":
        return sql[expression_start:index]
    end = _balanced_parenthesis_end(sql, index)
    return sql[expression_start:end]


def _balanced_parenthesis_end(value: str, opening: int) -> int:
    depth = 0
    quoted = False
    index = opening
    while index < len(value):
        character = value[index]
        if character == "'":
            if quoted and index + 1 < len(value) and value[index + 1] == "'":
                index += 2
                continue
            quoted = not quoted
        elif not quoted:
            if character == "(":
                depth += 1
            elif character == ")":
                depth -= 1
                if depth == 0:
                    return index + 1
        index += 1
    return len(value)


def _parse_sql_date_expression(expression: str) -> date | None:
    value = expression.strip().rstrip(";")
    while value.startswith("(") and _balanced_parenthesis_end(value, 0) == len(value):
        value = value[1:-1].strip()
    literal = re.fullmatch(r"[Nn]?'(\d{4})-?(\d{2})-?(\d{2})'", value)
    if literal:
        try:
            return date(*(int(part) for part in literal.groups()))
        except ValueError:
            return None
    if re.fullmatch(r"(?i)getdate\s*\(\s*\)|current_timestamp", value):
        return date.today()

    function = re.fullmatch(r"(?is)([A-Za-z_][\w]*)\s*\((.*)\)", value)
    if not function:
        return None
    name = function.group(1).casefold()
    body = function.group(2)
    if name == "dateadd":
        arguments = _split_sql_arguments(body)
        if len(arguments) != 3 or arguments[0].strip().casefold() not in {"day", "dd"}:
            return None
        try:
            offset = int(arguments[1].strip())
        except ValueError:
            return None
        anchor = _parse_sql_date_expression(arguments[2])
        return anchor + timedelta(days=offset) if anchor else None
    if name == "convert":
        arguments = _split_sql_arguments(body)
        return _parse_sql_date_expression(arguments[1]) if len(arguments) >= 2 else None
    if name == "cast":
        cast_match = re.fullmatch(r"(?is)(.+)\s+as\s+[A-Za-z_][\w]*(?:\([^)]*\))?", body)
        return _parse_sql_date_expression(cast_match.group(1)) if cast_match else None
    return None


def _split_sql_arguments(value: str) -> list[str]:
    arguments: list[str] = []
    start = 0
    depth = 0
    quoted = False
    index = 0
    while index < len(value):
        character = value[index]
        if character == "'":
            if quoted and index + 1 < len(value) and value[index + 1] == "'":
                index += 2
                continue
            quoted = not quoted
        elif not quoted:
            if character == "(":
                depth += 1
            elif character == ")":
                depth -= 1
            elif character == "," and depth == 0:
                arguments.append(value[start:index].strip())
                start = index + 1
        index += 1
    arguments.append(value[start:].strip())
    return arguments


def _context_family(field: Any) -> str:
    normalized = _normalized(field).replace("-", "_")
    aliases = {
        "metric": "metrics",
        "resolved_metric": "metrics",
        "resolved_metrics": "metrics",
        "dimension": "dimensions",
        "resolved_dimension": "dimensions",
        "resolved_dimensions": "dimensions",
    }
    return aliases.get(normalized, normalized)


def _trend_values(response: dict[str, Any], expected_metrics: Any) -> list[float]:
    rows = _mapping(response.get("query_result")).get("rows")
    if not isinstance(rows, list):
        return []
    candidates = [
        _normalized(value)
        for value in (
            expected_metrics
            if isinstance(expected_metrics, (list, tuple, set))
            else [expected_metrics]
        )
        if value
    ]
    values: list[float] = []
    excluded_tokens = ("date", "tarih", "month", "ay", "year", "yil", "period", "donem")
    for row in rows:
        if not isinstance(row, dict):
            continue
        normalized_row = {_normalized(key): value for key, value in row.items()}
        selected = next(
            (
                normalized_row[candidate]
                for candidate in candidates
                if candidate in normalized_row
                and isinstance(normalized_row[candidate], (int, float))
                and not isinstance(normalized_row[candidate], bool)
            ),
            None,
        )
        if selected is None:
            selected = next(
                (
                    value
                    for key, value in normalized_row.items()
                    if isinstance(value, (int, float))
                    and not isinstance(value, bool)
                    and not any(token in key for token in excluded_tokens)
                ),
                None,
            )
        if selected is not None:
            values.append(float(selected))
    return values


def _continuous_growth_claims(visible_text: str) -> list[str]:
    patterns = (
        r"\b(?:sürekli|surekli|kesintisiz|tutarlı|tutarli|istikrarlı|istikrarli)\b"
        r"[^.!?\n]{0,40}\b(?:art(?:tı|ti|ış|is|ıyor|iyor)|yüksel(?:di|iş|is|iyor))",
        r"\bher\s+(?:ay|dönem|donem)\b[^.!?\n]{0,40}"
        r"\b(?:art(?:tı|ti|ış|is|ıyor|iyor)|yüksel(?:di|iş|is|iyor))",
    )
    matches: list[str] = []
    for pattern in patterns:
        matches.extend(match.group(0) for match in re.finditer(pattern, visible_text))
    return _dedupe(matches)


def _dedupe(values: list[Any]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value is None:
            continue
        text = str(value)
        if text not in result:
            result.append(text)
    return result


def _optional_str(value: Any) -> str | None:
    return str(value) if value is not None else None


def _csv_value(value: Any) -> Any:
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return value


def _short(value: Any, limit: int = 240) -> str:
    text = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _critical_issue(result: TurnResult) -> str:
    issue = next(
        (
            assertion.diagnostic
            for assertion in result.assertions
            if not assertion.passed and assertion.severity == Severity.CRITICAL
        ),
        "-",
    )
    return issue.replace("|", "\\|")


def _worst_verdict(verdicts: list[Verdict]) -> Verdict:
    if Verdict.FAIL in verdicts:
        return Verdict.FAIL
    if Verdict.PARTIAL in verdicts:
        return Verdict.PARTIAL
    return Verdict.PASS


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--session-mode", choices=("isolated", "grouped"), default="grouped")
    parser.add_argument("--scenario-filter", action="append", default=[])
    parser.add_argument("--preset", choices=("meeting",))
    parser.add_argument("--scenario-file", type=Path, default=DEFAULT_CATALOG)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    scenarios = filter_scenarios(
        ScenarioCatalog.load(args.scenario_file), args.scenario_filter, args.preset
    )
    if not scenarios:
        print("Seçilen filtrelerle eşleşen senaryo bulunamadı.", file=sys.stderr)
        return 2
    runner = SmokeTestRunner(
        base_url=args.base_url,
        timeout=args.timeout,
        session_mode=args.session_mode,
    )
    results = runner.run(scenarios)
    run_dir = ArtifactWriter().write(results, args.output_dir)
    print_terminal_summary(results)
    print(f"\nRaporlar: {run_dir.resolve()}")
    return 1 if any(result.verdict == Verdict.FAIL for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
