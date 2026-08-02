# ANSWER-COVERAGE-001 — Walkthrough

## New analytical coverage

The deterministic planner now composes reusable concepts for:

- average appointments per patient;
- appointments booked for the same day;
- average protocol-opening delay after an appointment;
- planned-versus-actual duration difference;
- actual duration calculated from start/end timestamps;
- monthly appointment trends;
- daily average appointment volume;
- patients with repeated appointments;
- patients seeing multiple doctors on the same day;
- waiting records as a share of all records.

`2025 ile 2024 arası randevu adedi farkı` is now parsed as two comparison periods. `Geçen sene`, `önceki sene` and `bu sene` are normalized to the same date semantics as their `yıl` forms.

## Precedence protections

- Raw requests such as “son 20 randevuyu getir” remain raw lists.
- A breakdown such as “bu ay cinsiyete göre dağılım” remains a demographic distribution and is not reinterpreted as a monthly time trend.
- A catalog synonym match remains authoritative when a compositional candidate refers to a different dimension.
- A more specific relationship metric can supersede generic count/distinct-count only when its required columns demonstrate the specialization.

## User-facing fallback

When execution cannot safely finish, the response is no longer only “Yanıt Oluşturulamadı”. It states that no unverified number was produced, lists the metric/dimension/period the agent understood when available, and offers a concrete reformulation. Internal validation or provider errors remain hidden from the user and available only in diagnostics.

## Evaluation

| Measurement | Passed | Failed | Accuracy |
|---|---:|---:|---:|
| Holdout before this slice | 23 | 12 | 65.71% |
| Same holdout after implementation, before promotion | 34 | 1 | 97.14% |
| Fresh holdout after 11 promotions/replacements | 28 | 7 | 80.00% |
| Promoted colloquial regression | 35 | 0 | 100% |
| Catalog variation matrix | 887 | 0 | 100% |

The seven fresh failures remain untouched evidence for the next slice.
