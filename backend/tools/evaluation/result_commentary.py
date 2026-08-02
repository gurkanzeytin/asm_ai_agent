"""Deterministic result-commentary evaluation harness.

Runs without a database or LLM. Cases contain only synthetic aggregate values
and assert required/forbidden claims in the user-facing deterministic narrative.
"""

import json
from dataclasses import dataclass
from pathlib import Path

from app.analytics.models import AnalyticsResult
from app.insights.rules_engine import InsightRulesEngine
from app.insights.templates import build_deterministic_narrative

RESOURCE_PATH = Path(__file__).parent / "resources" / "result_commentary_cases.json"


@dataclass(frozen=True)
class CommentaryCaseResult:
    case_id: str
    passed: bool
    missing: tuple[str, ...]
    forbidden: tuple[str, ...]
    narrative: str


def run_commentary_evaluation(
    resource_path: Path = RESOURCE_PATH,
) -> list[CommentaryCaseResult]:
    payload = json.loads(resource_path.read_text(encoding="utf-8"))
    engine = InsightRulesEngine()
    results: list[CommentaryCaseResult] = []
    for case in payload["cases"]:
        analytics = AnalyticsResult(**case["analytics"])
        rules = engine.evaluate(analytics)
        narrative = build_deterministic_narrative(analytics, rules)
        text = "\n".join(
            [
                narrative.title,
                narrative.summary,
                *narrative.highlights,
                *narrative.observations,
                *narrative.considerations,
            ]
        )
        folded = text.casefold()
        missing = tuple(
            phrase for phrase in case.get("must_include", []) if phrase.casefold() not in folded
        )
        forbidden = tuple(
            phrase for phrase in case.get("must_not_include", []) if phrase.casefold() in folded
        )
        results.append(
            CommentaryCaseResult(
                case_id=case["id"],
                passed=not missing and not forbidden,
                missing=missing,
                forbidden=forbidden,
                narrative=text,
            )
        )
    return results


def main() -> int:
    results = run_commentary_evaluation()
    failed = [result for result in results if not result.passed]
    print(f"cases={len(results)} passed={len(results) - len(failed)} failed={len(failed)}")
    for result in failed:
        print(
            f"{result.case_id}: missing={list(result.missing)} "
            f"forbidden={list(result.forbidden)}"
        )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
