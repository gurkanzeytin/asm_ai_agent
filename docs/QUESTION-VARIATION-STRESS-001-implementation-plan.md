# QUESTION-VARIATION-STRESS-001 Implementation Plan

## Amaç

Statik golden/few-shot soru bankasına eklenmeyen, kataloglardan otomatik üretilen
görülmemiş sorularla 24 kolon ve 48 metriğin doğal dil → plan → deterministik
SQL → validator kapsamasını sürekli ölçmek.

## Yaklaşım

Üretici aşağıdaki bileşenleri çaprazlar:

- metrik adı ve en fazla iki katalog eşanlamlısı,
- metrikle uyumlu en fazla üç groupable boyut,
- tüm zaman, 2024 ve geçen yıl dönemleri,
- scalar ve boyutlu üç doğal dil kalıbı,
- her kolon için capability probe,
- PII/selectable=false kolonlar için ham listeleme güvenlik probu.

Üretilen cümleler `golden_dataset.json` veya retrieval kaynaklarına yazılmaz.
Bu nedenle test edilen ifadeler LLM/planner few-shot bağlamında “öğretilmiş”
örnek hâline gelmez.

## Audit kapıları

Her soru için:

1. ambiguity/clarification,
2. deterministic answerability,
3. QueryAnalyzer ve QueryPlanner,
4. beklenen metrik, boyut, gerekli kolon ve tarih,
5. DeterministicSQLBuilder,
6. SQLValidator,
7. PII kolonunun SELECT projection'a sızmaması

kontrol edilir.

## Etkilenen dosyalar

- `backend/tools/evaluation/question_variations.py`
- `backend/tests/test_question_variation_audit.py`
- `docs/MENTOR-DEMO-QUESTION-BANK.md`

API, frontend, database schema, provider ve repository değişmez.

## Başarı ölçütleri

- En az 500 görülmemiş soru üretilmesi.
- 24 kolonun ve 48 metriğin tamamının beklenen kapsam alanında bulunması.
- Her PII/selectable=false kolon için güvenlik probu.
- En az 650 offline başarılı vaka regresyon tabanı.
- Geçersiz SQL, tarih kaybı ve yanlış out-of-scope sayısının sıfır olması.
- Başarısız vakaların metrik/boyut/kolon/SQL şekli olarak sınıflandırılması.

## Verification

```bash
cd backend
../.venv/bin/python -m tools.evaluation.question_variations --show failing --limit 20
../.venv/bin/python -m pytest -q tests/test_question_variation_audit.py
../.venv/bin/python -m pytest -q
```
