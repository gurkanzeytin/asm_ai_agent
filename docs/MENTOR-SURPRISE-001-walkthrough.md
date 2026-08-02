# MENTOR-SURPRISE-001 Walkthrough

## Outcome

The backend now has a catalog-independent mentor-surprise gate for analytical
questions. It contains 15 still-blind questions and 14 promoted regression
questions. The final offline SQL-generation scores are:

- Mentor surprise: 15/15
- Mentor surprise regression: 14/14
- Existing colloquial blind: 35/35
- Existing colloquial regression: 44/44
- Catalog variation matrix: 887/887

The first calibrated probe passed 7/15. Eight genuine failures were promoted
to regression after general fixes. Fresh replacement rounds scored 11/15,
14/15, and finally 15/15. Output-contract mistakes discovered while authoring
the test were corrected separately and were not counted as agent capability
failures.

## What changed

### Independent evaluation data

`backend/tools/evaluation/resources/mentor_surprise_v1.json` is manually
authored and is not used as production few-shot data. It exercises combinations
that generated synonym variations do not adequately test:

- metric + period + dimension;
- metric + two dimensions;
- conditional rate + dimension;
- data-quality metric + time trend;
- specialized duration + ranking;
- repeat relationship + organizational breakdown;
- numeric threshold share + written Turkish number.

When a blind question fails, it moves to `mentor_surprise_regression_v1` with
`blind: false`; a fresh question replaces it in `mentor_surprise_v1`.

### Evaluation fidelity

The offline runner now executes the same plan-enrichment node used in
production before deterministic SQL generation. Its value catalog performs no
database I/O and returns no deployment-specific values. This lets schema-only
features such as threshold shares and curated named cohorts be evaluated while
preventing invented branch, doctor, department, or nationality values.

### General language and plan fixes

- Multi-metric intent no longer fires merely because the user says
  `karşılaştır` or `kıyasla`. It requires additive/conjunction wording or at
  least two grammatical measure mentions.
- A conjunction between dimensions, such as `şube ve hizmet`, no longer blocks
  one well-grounded compositional metric.
- A compositional conditional count is promoted to its catalog-linked rate
  sibling when the user asks for `oran`, `yüzde`, or `pay`.
- Data-quality metrics can retain their metric while upgrading to a monthly or
  weekly trend.
- Condition nouns such as `doktor bilgisi eksik` and `aynı tarihte kaydedilen`
  no longer become accidental grouping dimensions; an explicit `bazında`,
  `göre`, or `kırılımında` request still wins.
- `aynı gün farklı doktor` is no longer confused with a patient first/last
  appointment span merely because `gün farklı` contains the text `gün fark`.
- Common Turkish number words from zero through one hundred, including compound
  tens such as `kırk beş`, can ground a safe duration threshold.
- Metric catalog concept phrases were expanded for fiili duration, protocol
  opening delay, waiting share, same-day booking, and same-day multi-doctor
  behavior.

## SQL safety

No API route or direct database access was added. All successful mentor cases
use the deterministic builder, the known reporting view, read-only SQL, and the
existing SQL validator. Ratio cases assert `NULLIF` protection, and status-rate
cases prohibit a numerator status filter from shrinking the denominator.

## Monday live verification

1. Add the SQL Server connection profile without committing credentials.
2. Run the mentor suite in live mode and inspect row/alias contracts.
3. Ask representative questions through the UI, including a multi-dimension
   duration, a conditional rate, a repeat-patient breakdown, and a written
   number threshold.
4. Verify tables/charts, Turkish commentary, empty-result behavior, and that no
   patient-level PII is rendered.
