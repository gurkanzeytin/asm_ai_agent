# Live UI Test Report - 2026-07-30

App: http://127.0.0.1:5174/
Backend health: http://127.0.0.1:8000/docs -> 200

## Scope

10 complete live UI sessions were run through the chat UI. Each complete session used 7 consecutive prompts, covering basic, mid, and expert flows. One earlier patient-metric session was partially interrupted by browser-control timeout after a heavy chat DOM; it was rerun as `S08b`.

Total complete UI prompts: 70

## Session Matrix

| Session | Level | Focus | Result |
| --- | --- | --- | --- |
| S01 | Basic | Year totals, comparison, Kardiyoloji filter memory, monthly top-N | Pass |
| S02 | Mid | Department top/bottom-N, share of total, Radyoloji filter, service dimension shift | Pass, 1 slow response (~88s) |
| S03 | Mid | Multi-month comparison, filter carry, daily breakdown, top days | Pass |
| S04 | Expert | Monthly department trends, Q1 filter, doctor/service replacement, share %, Q1/Q2 service compare | Pass |
| S05 | Mid | Relative dates: this year, last year, common-month comparison, Kardiyoloji carry | Pass |
| S06 | Expert | Status distribution, Gelmedi rate, completed rate, cancellation limitation fallback | Pass, 1 slow response |
| S07 | Mid | Branch, appointment source, Telefon filter, status removal, appointment type share | Pass |
| S08b | Expert | Unique patient, multi-metric patient aggregate, appointments per patient, duration/lead-time metrics | 1 functional failure |
| S09 | Expert | Multi-metric period comparisons, branch breakdown, Gelmedi/complete rates, doctor shift | Pass |
| S10 | Basic/Mid | Unsafe delete/raw SQL/PII requests, recovery to normal analytics | Pass |

## Confirmed Issues

### LIVE-P1-001 - Aggregate Patient Metric Blocked As Sensitive

Prompt:
`2025 randevu sayısı ile tekil hasta sayısını birlikte göster.`

Observed:
The UI returned `Hassas veri gösterilemez`, saying patient identity or row-level personal data cannot be shown.

Expected:
This is an aggregate request, not patient-level data. It should return `appointment_count` and `unique_patient_count` as scalar aggregate metrics.

Status:
Reproduced in the partial S08 run and again in S08b. Persistent.

### LIVE-P2-002 - Transient Failure On Appointments Per Patient

Prompt:
`2025 hasta başına ortalama randevu adedi nedir?`

Observed:
In the first S08 attempt, the UI returned `Yanıt Oluşturulamadı`.

Expected:
Return scalar `appointments_per_patient`.

Status:
Retried in S08b and passed. Treat as transient or context-dependent, not confirmed persistent.

### LIVE-P2-003 - Follow-Up After Failed Turn Can Inherit Wrong Metric

Prompt sequence:
1. `2025 hasta başına ortalama randevu adedi nedir?`
2. `Bu ortalamayı bölümlere göre en yüksek 10 bölüm olarak listele.`

Observed:
After the failed average turn, the follow-up returned `unique_patient_count` by department instead of the requested average.

Expected:
Either compute `appointments_per_patient` by department or ask for clarification. It should not silently switch to tekil hasta count.

Status:
Observed once after the failed turn. Needs targeted regression test after fixing LIVE-P2-002.

## Non-Product Noise

Repeated `Statsig` / `nodeRepl.fetch response is too large` messages appeared in the browser-control output. These are from the Codex in-app browser/control layer, not from the app backend. Backend error log was empty during the final check.

## Notes

- The earlier fixes for department filter carry, period comparison, monthly top-N, share-of-total, multi-month comparison, and duplicate chart keys held up under the live session chains.
- Security recovery passed: after unsafe delete/raw SQL/PII prompts, the app recovered and answered a normal analytics prompt.

## Fix Verification - 2026-07-30 10:56

Status after code fixes:

- `LIVE-P1-001`: Fixed. The planner no longer treats `HastaId` as a GROUP BY/projection column when it is only the target of `COUNT(DISTINCT HastaId)` in a scalar aggregate. Live UI now returns both `Toplam Randevu: 213.855` and `Tekil Hasta Sayisi: 38.067`; no sensitive-data block.
- `LIVE-P2-002`: Fixed. `repeat_behavior` plans with verified ratio formulas now build deterministic SQL. Live UI now returns `Hasta Basina Randevu: 5,6`; no `Yanıt Oluşturulamadı`.
- `LIVE-P2-003`: Fixed. After the average turn succeeds and persists `appointments_per_patient`, the follow-up `Bu ortalamayi bolumlere gore en yuksek 10 bolum olarak listele.` keeps the same metric and returns a 10-row department ranking table. Top row observed: `Fizik Tedavi ve Rehabilitasyon` with `7,7`.

Automated verification:

- `pytest tests/test_deterministic_sql_pipeline.py tests/test_result_size_safety.py tests/test_live_memory_followups.py -q` -> 87 passed.
- Focused catalog/planner checks -> 8 passed.

Live UI verification:

1. `2025 randevu sayisi ile tekil hasta sayisini birlikte goster.` -> pass, aggregate cards shown.
2. `2025 hasta basina ortalama randevu adedi nedir?` -> pass, scalar average shown.
3. `Bu ortalamayi bolumlere gore en yuksek 10 bolum olarak listele.` -> pass, session memory preserved metric and date scope.
