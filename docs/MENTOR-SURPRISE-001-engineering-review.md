# MENTOR-SURPRISE-001 Engineering Review

## Decision

Ready for offline merge. Live SQL Server execution and final UI acceptance are
explicitly deferred to Monday.

## Correctness

- The manually authored holdout is separate from production prompts, golden
  examples, and catalog-generated variations.
- All 14 observed blind failures are retained as non-blind deterministic
  regressions; none was deleted to improve the displayed score.
- Multi-dimensional cases require every requested physical column in generated
  SQL, not merely one matching dimension in the plan.
- The offline evaluator now includes production plan enrichment, closing the
  previous gap where a valid threshold-share question failed only because the
  test runner skipped that node.
- Existing additive conversational behavior remains covered: `bir de ... ekle`
  preserves the earlier metric while group comparisons remain single-metric.

## Security and privacy

- Generated SQL still passes the existing validator and is read-only.
- The evaluation value catalog performs no I/O and cannot invent or expose
  deployment values.
- No secrets, connection strings, patient values, or fixtures containing PII
  were added.
- No database access was introduced into routes; production value grounding
  remains in its existing repository/catalog path.

## Maintainability

- New phrase coverage lives in the metric catalog or reusable concept groups,
  not whole-question conditionals.
- Rate promotion uses catalog numerator links, so future conditional rate
  metrics inherit the same behavior.
- Written-number parsing is bounded and deterministic. It supports common
  values through 100, not unrestricted natural-language arithmetic.
- The evaluator's no-I/O catalog is intentionally explicit; deployment-specific
  value grounding remains a live-test responsibility.

## Known limitations

- Offline SQL-generation success does not prove the SQL Server view contains
  the expected values or that every query returns rows.
- The suite validates routing, plans, SQL shape, contracts, and mocked result
  handling. It does not grade the final live LLM narrative for every case.
- Arbitrary nested cohort denominators, for example `yabancılar içinde kadın
  oranı`, remain more complex than a single conditional share and should get a
  separate feature/evaluation slice.
- Written numbers above 100 and free-form number phrases are intentionally not
  interpreted.
- The in-app UI and real database are not configured on this workstation; both
  remain Monday gates.

## Verification evidence

- Ruff on all changed Python files: passed.
- Focused mentor/planner/composition/evaluation tests: passed.
- Mentor surprise: 15/15.
- Mentor surprise regression: 14/14.
- Colloquial blind: 35/35.
- Colloquial regression: 44/44.
- Catalog variation audit: 887/887.
- Final full backend test suite: 2386 passed, 1 skipped.
