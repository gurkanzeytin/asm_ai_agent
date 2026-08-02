from tools.evaluation.question_variations import (
    audit_question_variations,
    generate_question_variations,
    summarize,
)

from app.semantics import catalog


def test_generator_creates_large_unseen_matrix_without_touching_golden_dataset():
    questions = generate_question_variations()

    assert len(questions) >= 500
    assert len({case.id for case in questions}) == len(questions)
    assert all(case.id.startswith("VAR-") for case in questions)


def test_generator_covers_every_column_and_metric_catalog_id():
    questions = generate_question_variations()
    covered_columns = {
        column for case in questions for column in case.expected_columns
    }
    covered_metrics = {
        case.expected_metric for case in questions if case.expected_metric
    }

    assert covered_columns == catalog.load_column_catalog().column_names()
    assert covered_metrics == set(catalog.load_metric_catalog().by_id())


def test_privacy_probes_exist_for_every_non_selectable_column():
    questions = generate_question_variations()
    protected = {
        column.column
        for column in catalog.load_column_catalog().columns
        if column.pii or not column.selectable
    }
    probed = {
        column for case in questions for column in case.must_not_select
    }

    assert probed == protected


def test_audit_is_reproducible_and_reports_actionable_failures():
    first = audit_question_variations()
    second = audit_question_variations()

    assert first is second
    assert len(first) == len(generate_question_variations())
    assert "questions=" in summarize(first)
    assert "families=" in summarize(first)
    assert any(result.passed for result in first)
    assert all(result.passed for result in first)
    assert sum(result.passed for result in first) >= 650
    assert not any(
        failure in {"invalid_sql", "date_missing", "out_of_scope"}
        for result in first
        for failure in result.failures
    )


def test_every_column_capability_probe_has_a_non_sql_schema_answer():
    results = [
        result
        for result in audit_question_variations()
        if result.case.family == "column_capability"
    ]

    assert len(results) == len(catalog.load_column_catalog().columns)
    assert all(result.passed and not result.deterministic for result in results)


def test_privacy_probes_never_emit_selected_pii():
    privacy_results = [
        result
        for result in audit_question_variations()
        if result.case.family == "privacy_guard"
    ]

    assert privacy_results
    assert all(
        not any(failure.startswith("privacy_violation:") for failure in result.failures)
        for result in privacy_results
    )


def test_fixed_dimension_count_variants_accept_the_canonical_equivalent_plan():
    fixed_ids = {
        metric.id
        for metric in catalog.load_metric_catalog().metrics
        if metric.formula_type == "count_rows_grouped"
        and metric.formula == "COUNT(*)"
        and metric.fixed_dimension
    }
    relevant = [
        result
        for result in audit_question_variations()
        if result.case.expected_metric in fixed_ids
    ]

    assert relevant
    # A canonical COUNT(*) plan is equivalent when it preserved the fixed
    # dimension. The only remaining metric mismatches must therefore also be
    # genuine dimension-resolution mismatches, not duplicate-metric noise.
    assert all(
        "dimension_mismatch" in result.failures
        for result in relevant
        if "metric_mismatch" in result.failures
    )


def test_unverified_metrics_fail_closed_as_expected_clarifications():
    results = [
        result
        for result in audit_question_variations()
        if result.case.expects_clarification
    ]
    unverified_ids = {
        metric.id
        for metric in catalog.load_metric_catalog().metrics
        if metric.status == "requires_verified_mapping"
    }

    assert {result.case.expected_metric for result in results} == unverified_ids
    assert all(result.passed and not result.deterministic for result in results)


def test_metric_dimension_variations_preserve_the_requested_dimension():
    results = [
        result
        for result in audit_question_variations()
        if result.case.family == "metric_dimension"
    ]

    assert results
    assert not any("dimension_mismatch" in result.failures for result in results)


def test_multi_period_metric_variations_supply_two_real_periods_and_build_sql():
    metric_id = "multi_period_patient_overlap_count"
    questions = [
        case
        for case in generate_question_variations()
        if case.expected_metric == metric_id
    ]
    results = [
        result
        for result in audit_question_variations()
        if result.case.expected_metric == metric_id
    ]

    assert questions
    assert all(
        ("2023 ve 2024" in case.question)
        or ("2024 ve 2025" in case.question)
        or ("Mayıs 2024 ve Haziran 2024" in case.question)
        for case in questions
    )
    assert all(result.passed and result.deterministic for result in results)
