"""Offline plan-level sweep: finds SILENTLY WRONG answers before the demo.

Touches no running code and never queries the database — it only builds each
question's QueryPlan and inspects it, so it is safe to run at any time.

Flags the signature of the 2026-08-03 live bug: a value the user named that
never reached the plan, or a patient question that fell back to counting rows.
"""

import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.planning.compliance import PlanComplianceValidator  # noqa: E402
from app.planning.planner import (  # noqa: E402
    _APPOINTMENT_NOUN_PATTERN,
    _COUNT_REQUEST_PATTERN,
    _PATIENT_NOUN_PATTERN,
    QueryPlanner,
)
from app.planning.value_resolver import extract_candidate_phrases  # noqa: E402
from app.semantics.view_mapping import fold  # noqa: E402
from app.services.deterministic_sql_builder import (  # noqa: E402
    DeterministicSQLBuilder,
    UnsupportedPlan,
)
from app.database_intelligence.models import ViewMetadata  # noqa: E402
from app.services.query_analyzer import QueryAnalyzer  # noqa: E402

VIEW = ViewMetadata(name="dbo.vw_RandevuRaporu", columns=[])

RESOURCES = BACKEND / "app" / "resources"

# Which plan field carries each extracted field's grounded value. Offline we
# cannot ground against the DB, so we only assert the plan has SOMEWHERE for the
# mention to live — a completely empty slot means the value was dropped.
_FIELD_SLOTS = {
    "department": ("department_filter", "excluded_departments"),
    "branch": ("branch_filters",),
}


def _plan_carries(plan, field: str) -> bool:
    if field in plan.resolved_filters:
        return True
    for slot in _FIELD_SLOTS.get(field, ()):
        if getattr(plan, slot, None):
            return True
    # Named as a grouping rather than a filter is a legitimate resolution.
    return bool(plan.dimensions)


def load_questions():
    seen, out = set(), []
    golden = json.loads((RESOURCES / "golden_dataset.json").read_text(encoding="utf-8"))
    for q in golden["questions"]:
        text = q["question"]
        if text not in seen:
            seen.add(text)
            out.append((q["id"], text))
    cases = json.loads((RESOURCES / "evaluation_cases.json").read_text(encoding="utf-8"))
    for c in cases["cases"]:
        text = c.get("question")
        if text and text not in seen:
            seen.add(text)
            out.append((c.get("id", "EVAL"), text))
    return out


def main():
    analyzer, planner = QueryAnalyzer(), QueryPlanner()
    builder, compliance = DeterministicSQLBuilder(), PlanComplianceValidator()
    questions = load_questions()

    findings = {"dropped_value": [], "patient_as_rows": [], "no_metric": [],
                "unsupported": [], "non_compliant": [], "crashed": []}

    for qid, question in questions:
        try:
            analysis = analyzer.analyze(question)
            plan = planner.build_plan(question, analysis, tables=[], views=[VIEW])
        except Exception as exc:  # noqa: BLE001
            findings["crashed"].append((qid, question, repr(exc)[:120]))
            continue

        folded = fold(question)

        # 1. A value the user named that the plan has nowhere to put.
        for field in extract_candidate_phrases(question):
            if not _plan_carries(plan, field):
                findings["dropped_value"].append((qid, question, field))
                break

        # 2. Today's bug class: counts patients, answers with row volume.
        if (
            plan.metrics == ["appointment_count"]
            and _PATIENT_NOUN_PATTERN.search(folded)
            and not _APPOINTMENT_NOUN_PATTERN.search(folded)
            and _COUNT_REQUEST_PATTERN.search(folded)
        ):
            findings["patient_as_rows"].append((qid, question, plan.metrics))

        if not plan.metrics:
            findings["no_metric"].append((qid, question, plan.analysis_type))

        try:
            built = builder.build(plan)
        except Exception as exc:  # noqa: BLE001
            findings["crashed"].append((qid, question, repr(exc)[:120]))
            continue
        if isinstance(built, UnsupportedPlan):
            findings["unsupported"].append((qid, question, str(built.reason)[:90]))
            continue
        verdict = compliance.check(built.sql, plan)
        if not verdict.compliant:
            findings["non_compliant"].append((qid, question, str(verdict.missing)[:90]))

    print(f"Taranan soru: {len(questions)}\n")
    labels = {
        "dropped_value": "SESSIZ KAYIP DEGER (bugunku hata sinifi)",
        "patient_as_rows": "HASTA SORUSU RANDEVU SAYIYOR",
        "no_metric": "HIC METRIK YOK",
        "unsupported": "BUILDER DESTEKLEMIYOR",
        "non_compliant": "PLAN-SQL UYUMSUZ",
        "crashed": "ISTISNA",
    }
    for key, label in labels.items():
        rows = findings[key]
        print(f"{'=' * 76}\n{label}  —  {len(rows)}\n{'=' * 76}")
        for qid, question, detail in rows[:40]:
            print(f"  [{qid}] {question}")
            print(f"        -> {detail}")
        if len(rows) > 40:
            print(f"  ... +{len(rows) - 40} tane daha")
        print()


if __name__ == "__main__":
    main()
