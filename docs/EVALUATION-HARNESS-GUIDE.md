# Değerlendirme (Eval) Harness Rehberi

Amaç: ajanın kalitesini **his**le değil **sayı**yla ölçmek. Her canlı bulguyu
kalıcı bir regresyon vakasına çevirir; bir değişikliğin işe yarayıp yaramadığını
skorbordla görürüz.

Konum: `backend/tools/evaluation/` — vaka seti `backend/app/resources/evaluation_cases.json`.

## Çalıştırma (tek komut)

```bash
cd backend
../.venv/Scripts/python.exe -m tools.evaluation run --suite <suite> --mode <mode>
```

Her koşu `backend/evaluation/results/` altına JSON + Markdown skorbord yazar ve
önceki koşuyla karşılaştırır. `--no-write` ile yazmadan çalıştırılabilir.
Tek vaka: `--case EXP-THRESH-GT-001`. Sınır: `--limit N`.

### Suite'ler
| Suite | Kapsam |
|-------|--------|
| `expert` | **Beyaz-kutu regresyon** — sevk edilen yeteneklerin SQL-şeklini kilitler (aşağıda). CI kapısı. |
| `blind` | Kör/zorlayıcı vakalar (kapsam-dışı, netleştirme, belirsiz performans, vb.). |
| `acceptance` | E2E kabul vakaları (E2E-RW-*). CI kapısı. |
| `deterministic` | `sql_source == deterministic` bekleyen tüm vakalar. |
| `live` | Canlı DB gerektiren vakalar. |
| `all` | Hepsi. |

### Modlar
`planner-only`, `sql-generation` (varsayılan — LLM/DB gerekmez, hızlı),
`mocked-execution`, `live-db`, `full-endpoint`.

## Skorbord çıktısı
Markdown rapor şunları içerir: katman doğruluğu (routing / query_plan /
sql_generation / sql_semantics), **hata taksonomisi** (40+ tipli `FailureCode`),
en yavaş sorular, ve önceki koşuya göre **regresyon karşılaştırması**
(çözülen/yeni düşen vaka id'leri, p95 gecikme deltası).

## CI kapısı (exit kodları)
- `0` — geçti
- `2` — kabul vakası (E2E-RW-*) düştü
- `4` — **expert regresyon vakası (EXP-*) düştü** (yeni)
- `3` — routing veya sql_generation doğruluğu < %95

## Expert regresyon suite'i (bu haftaki iş)
`EXP-*` vakaları 2026-07-28 haftasında sevk edilen yetenekleri kilitler:
- **Sayısal eşik (HAVING):** `> N`, `< N`, `en az N` (+ sahte `TOP(N)` limiti yok).
- **Yüzdelik dilim:** `en üstteki/en yüksek %N` → `TOP (N) PERCENT`.
- **Hafta içi/sonu:** `DayType` türetilmiş boyut, `DATEDIFF(day,'19000101',...) % 7`.
- **Lead-time:** iki-tarih `AVG(DATEDIFF(day, CreatedDate, BaslangicTarihi))`.
- **Tarih aralıkları:** çeyrek, yarı-yıl, ay-aralığı (tam yıla düşmez).
- **Günlük ortalama:** tek skaler (güne göre GROUP BY yok).
- **Durum dışlaması:** `X ve Y hariç tut` → tümleyen IN-list (waiting_count yok).
- **Negatif vakalar:** ratio `%10` ≠ percentile; haftalık trend ≠ day_type; düz `TOP 5` ≠ percentile.

## Yeni regresyon vakası ekleme
`evaluation_cases.json` içindeki `cases` dizisine ekle. Şema `EvaluationCase`
(`tools/evaluation/models.py`). Anahtar alanlar:
- `expected`: `analysis_type`, `metrics` (alt-küme), `dimensions` (kesişim),
  `sql_source`, `result_contract`, `answerable`.
- `sql_requirements`:
  - `must_use_columns` / `must_not_use_columns` — kolon varlığı (katalogda tanımlı olmalı).
  - `must_include_features` / `must_not_include_features` — sabit özellik sözcükleri
    (`group_by`, `null_safe_division`, `current_period`, `baseline_period`,
    `cohort_filter`, `default_having_minimum_sample`, ...).
  - **`must_include_sql` / `must_not_include_sql`** — serbest, büyük/küçük harf
    duyarsız SQL alt-dizesi (yeni; HAVING eşiği, `TOP (N) PERCENT`, day_type CASE,
    tarih literalleri gibi yeteneğe özgü şekilleri kesin doğrular).

Doğru `expected` değerlerini üretmek için soruyu gerçek pipeline'dan geçir
(`QueryPlanner.build_plan` + `DeterministicSQLBuilder.build`) ve
`analysis_type`/`metrics`/`dimensions`/`result_schema` + SQL parçalarını oku.

Türetilmiş boyutlar (ör. `DayType`) gerçek kolon olmadığından
`tools/evaluation/dataset.py::_DERIVED_DIMENSIONS` içinde beyaz-listelenir.

## Mevcut skorbord anlık görüntüsü (2026-07-28, sql-generation)
- **expert: 15/15 (%100)** — CI kapısı yeşil.
- blind: 51/86 (kör suite kasıtlı zor/adversaryal vakalar içerir; katman
  doğrulukları: routing ~%81, sql_semantics ~%92 — sürekli iyileştirme hedefi).

Birim testler: `tests/test_evaluation_harness.py` (harness), tam paket 1778 geçti.
