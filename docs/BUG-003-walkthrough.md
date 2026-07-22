# BUG-003 Walkthrough

## Conversation Flow

Before:

`raw fragment -> intent/answerability -> out of scope -> context never applied`

After:

`raw fragment -> date-fragment recognition -> typed context merge -> resolved question -> answerability -> planning`

For a successful appointment-duration turn anchored to 2025, `2024 yılının?` now resolves to
the prior appointment-duration request with the 2025 expression replaced by 2024. Subject,
metric, dimensions, compatible filters, analysis type, time grain, ranking, and limit remain
inheritable; the explicit date and explicit comparison target take precedence.

Without a valid anchor, the same fragment returns `ASK_CLARIFICATION` with:

> 2024 yılı için hangi randevu analizini görmek istediğinizi belirtir misiniz?

It does not run SQL and is not classified as out of scope.

## Supported Year Forms

The shared extractor recognizes possessive/case variants, bare conversational years,
`geçen yıl`, `bir önceki yıl`, `önceki yıl`, comparison wording, and “olanı” forms.
An explicit year is a full calendar year. `Bir önceki yıl` uses the active explicit-year
anchor when one exists; `geçen yıl` remains relative to the current calendar year.

The 2024 aggregate SQL produced by the deterministic builder is:

```sql
SELECT AVG(CAST(RandevuSuresi AS FLOAT)) AS appointment_duration_average
FROM dbo.vw_RandevuRaporu
WHERE BaslangicTarihi >= '2024-01-01'
  AND BaslangicTarihi < DATEADD(day, 1, '2024-12-31')
;
```

This is the existing SQL Server representation of the half-open interval
`[2024-01-01, 2025-01-01)` and contains no rolling-window fallback.

## Aggregate Presentation

An AVG-only plan returning one physical row now has:

```text
result_shape: scalar_aggregate
technical_row_count: 1
business_record_count: null
aggregate_result: true
displayable_kpis: [appointment_duration_average]
```

Before, the UI could display `Kayıt Sayısı: 1`, total, average, median, minimum, and maximum
over the already-aggregated value. After, it displays one card:

```text
Ortalama Randevu Süresi: 31,9 dk
```

A scalar COUNT+AVG query displays both returned business metrics exactly once. Raw-row
queries may retain their returned-record count. Technical row count and semantic result
shape stay in the developer-details section.

## Diagnostics

The response now carries `raw_question`, `resolved_question`, `follow_up_detected`,
`context_applied`, `answerability_input_source`, and `answerability_signals`. Resolved
follow-ups identify inherited entities/metrics and the explicit current-turn date.

