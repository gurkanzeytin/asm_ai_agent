# LIVE-UI-FIXES-001 Walkthrough

## Sensitive Detail Guard

`app.services.result_safety` now detects raw patient/contact identity columns separately from aggregate patient metrics. When such columns appear in a successful query result, `AnalyzeResultsNode` marks the result as `unsafe_detail_output` and uses a deterministic sensitive-data message. The API window already suppresses rows for `unsafe_detail_output`, so no route-level business logic was added.

Expected behavior:

- `HastaId` row lists are blocked.
- `unique_patient_count` remains allowed.
- The report explains that patient/person-level rows cannot be shown and asks for aggregate alternatives.

## Inline Memory Reset

`ContextManager.resolve` now consumes reset prefixes such as `önceki bağlamı unut`, `bağlamı sıfırla`, `memoryi unut`, and `yeni konu`. When matched, the session context is cleared before the remaining text is resolved.

Example:

`Önceki bağlamı unut. Beklemede randevu sayısını göster`

resolves as a fresh standalone `Beklemede randevu sayısını göster` request, without inheriting the previous branch/metric/date plan.

## Single-Branch Presentation

`TemplateReportRenderer` adds a short note when a branch breakdown result has exactly one branch row:

`Not: Bu sorgu sonucunda tek şube bulundu; şube bazında çoklu karşılaştırma oluşmadı.`

This matches the current data shape while avoiding a hardcoded global assumption in query planning.

For analytical/insight-routed branch results, `AnalyticsEngine` and the deterministic insight templates now use the result label column. A one-row `SubeAdi` grouped result is worded as:

`'TEST ASM Gebze' şubesine ait`

and the limitation says that only one branch was found, not that a generic category/status comparison failed.

## Full Comparison Isolation

The context resolver no longer treats every dated `karşılaştır` question as a follow-up. A complete question such as `2025 yılında şubelere göre randevu sayılarını karşılaştır` is independent and does not inherit a previous `Beklemede` status filter.
