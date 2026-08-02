# CONVERSATIONAL-ANSWER-001 — Walkthrough

## Resumable clarification

`Daha önce gelenlerden bu yıl da gelen kaç kişi var?` no longer silently treats “daha önce” as an arbitrary history window. The agent asks which prior period to use and offers a previous-calendar-year choice or an explicit year. The choice is stored as a bounded pending field; replying `Bir önceki takvim yılı` or `2024` rewrites the original question and produces a two-period patient-overlap plan.

`Randevular ortalama ne kadar sürmüş?` asks whether the intended value is:

- stored/planned `RandevuSuresi`; or
- actual duration calculated from `BaslangicTarihi` and `BitisTarihi`.

The reply resumes the original request with the selected catalog metric. Explicit questions such as `2025 ortalama randevu süresi` and `fiili süre` are not interrupted.

## Result commentary

Scalar KPI narratives now include their business label and formatted value. Examples include `Toplam randevu: 1.240`, `Gelmeme oranı: %18,4` and `Doktoru eksik kayıt: 12`. This complements the UI metric card and prevents a correct result from degrading to the context-free phrase “result total”.

The runnable command is:

```bash
cd backend
../.venv/bin/python -m tools.evaluation.result_commentary
```

It verifies seven synthetic, PII-free result families:

| Family | Required behavior |
|---|---|
| Scalar count | Business label and Turkish number formatting |
| Ratio | Percent formatting, not record-count wording |
| Distribution | Total, leading group and share |
| Period comparison | Correct increase/decrease direction and percentage |
| Trend | Consistent direction and average |
| Empty result | Insufficient-evidence guidance; no fabricated ranking/change |
| Data quality | Named quality metric without identity leakage |

Current result: **7/7 passed**.
