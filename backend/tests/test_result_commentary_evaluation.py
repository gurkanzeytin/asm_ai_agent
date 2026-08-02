from tools.evaluation.result_commentary import run_commentary_evaluation


def test_result_commentary_evaluation_suite_passes():
    results = run_commentary_evaluation()

    assert len(results) == 7
    assert all(result.passed for result in results), [
        {
            "case_id": result.case_id,
            "missing": result.missing,
            "forbidden": result.forbidden,
            "narrative": result.narrative,
        }
        for result in results
        if not result.passed
    ]
