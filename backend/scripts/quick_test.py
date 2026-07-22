"""Manual smoke-test CLI for the AI reporting workflow, with explicit session control.

Session isolation is the point of this script: every standalone invocation gets
its own fresh, ephemeral session by default so unrelated quick tests never
contaminate each other's conversational memory (see app.context.session_store).
Use --shared-session (or an explicit --session-id) only when deliberately
testing follow-up behavior across multiple questions.

Usage:

    python scripts/quick_test.py "Toplam kaç randevu var?"
        -> unique isolated session, one question

    python scripts/quick_test.py --file followups.txt --shared-session
        -> one shared session for every line in followups.txt, in order
           (deliberate follow-up testing)

    python scripts/quick_test.py "Peki geçen ay?" --session-id my-session
        -> reuses an explicit session (e.g. to continue a specific conversation)

    python scripts/quick_test.py "..." --session-id my-session --reset-session
        -> clears my-session's memory before asking the question

Not run as part of the automated test suite — this hits the real configured
LLM/database. Exits non-zero if the workflow could not produce a report.
"""

import argparse
import asyncio
import sys
from pathlib import Path

# Add backend directory to sys.path to resolve 'app' correctly
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.bootstrap import container  # noqa: E402
from app.context.session_store import generate_session_id  # noqa: E402


def _print_diagnostics(question: str, result) -> None:
    print(f"\n--- {question!r} ---")
    print(f"session_id        : {result.session_id}")
    print(f"outcome           : {result.outcome}")
    print(f"follow_up_detected: {result.follow_up_detected}")
    print(f"context_applied   : {result.context_applied}")
    print(f"inherited_fields  : {result.inherited_fields}")
    print(f"overridden_fields : {result.overridden_fields}")
    print(f"memory_updated    : {result.memory_updated}")
    print(f"memory_turn_count : {result.memory_turn_count}")
    if result.generated_report:
        print(f"report title      : {result.generated_report.title}")
    print(f"errors            : {result.errors or 'none'}")


async def _run_one(question: str, session_id: str) -> bool:
    result = await container.reporting_service.run_workflow(question, session_id=session_id)
    _print_diagnostics(question, result)
    return bool(result.generated_report) and not result.errors


async def _main(args: argparse.Namespace) -> int:
    if args.file:
        session_id = args.session_id or generate_session_id()
        questions = [
            line.strip()
            for line in Path(args.file).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        if not args.shared_session and not args.session_id:
            print(
                "Warning: --file without --shared-session or --session-id still runs each "
                "question in the SAME session (shared by default for batch files). Pass "
                "--session-id per-question invocations instead for full isolation.",
                file=sys.stderr,
            )
        if args.reset_session:
            existed = container.context_manager.clear(session_id)
            print(f"Reset session {session_id} (had memory: {existed})")
        ok = True
        for question in questions:
            ok = await _run_one(question, session_id) and ok
        return 0 if ok else 1

    if not args.question:
        print("Provide a question, or use --file for batch mode.", file=sys.stderr)
        return 2

    if args.shared_session and not args.session_id:
        print(
            "--shared-session has no effect on a single question; pass --session-id "
            "explicitly to reuse a specific session across separate invocations.",
            file=sys.stderr,
        )

    session_id = args.session_id or generate_session_id()
    if args.reset_session:
        existed = container.context_manager.clear(session_id)
        print(f"Reset session {session_id} (had memory: {existed})")

    ok = await _run_one(args.question, session_id)
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question", nargs="?", help="Natural-language question to ask.")
    parser.add_argument(
        "--file", help="Path to a newline-delimited file of questions (batch mode)."
    )
    parser.add_argument(
        "--session-id", dest="session_id", help="Explicit session ID to use/reuse."
    )
    parser.add_argument(
        "--shared-session",
        action="store_true",
        help="Batch mode: run every question in --file under one shared session "
        "(deliberate follow-up testing). Ignored for a single question unless "
        "combined with --session-id.",
    )
    parser.add_argument(
        "--reset-session",
        action="store_true",
        help="Clear the target session's memory before running.",
    )
    args = parser.parse_args()
    return asyncio.run(_main(args))


if __name__ == "__main__":
    sys.exit(main())
