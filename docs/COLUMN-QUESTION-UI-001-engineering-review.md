# COLUMN-QUESTION-UI-001 — Engineering Review

## Mimari değerlendirme

- Soru örnekleri API route içinde üretilmez; semantik katalog ve servis katmanındadır.
- API yalnız `suggested_questions` alanını DTO'dan response'a eşler.
- UI önerileri normal sohbet gönderimine bağlanır; SQL güvenlik doğrulamasını atlamaz.
- LLM'e giden örnekler mevcut `SchemaKnowledge` sağlayıcısından taşınır; endpoint doğrudan LLM çağırmaz.
- Response alanı eklemelidir ve eski istemciler için geriye uyumludur.

## Güvenlik

- `pii=true` veya `selectable=false` kolonlar yalnız açıklama örnekleri üretir.
- Kişi adı/soyadı için ham değer veya kişi listesi önerilmez.
- Doğrulanmamış protokol kodlarına iş anlamı atanmaz; yalnız kod dağılımı/boşluk analizi önerilir.
- Tüm tıklanabilir sorular mevcut read-only SQL validator hattından geçer.
- “Cevapsız bırakmama”, veri uydurma anlamına gelmez: veri yoksa veya istek güvenli değilse açıklama ve uygulanabilir alternatif verilir.

## Riskler ve takip işleri

- `935/935` kontrollü çevrimdışı kapsama sonucudur; sınırsız doğal dil için matematiksel garanti değildir.
- Canlı SQL Server değer profilleri henüz bu bilgisayarda doğrulanmadı. Pazartesi kategori örnekleri ve kod anlamları canlı kaynaktan kontrollü biçimde doğrulanmalıdır.
- `npm ci` mevcut bağımlılık ağacında iki yüksek önem dereceli güvenlik uyarısı bildirdi. Otomatik `npm audit fix` çalıştırılmadı; sürüm etkisi ayrı dependency/security çalışmasında incelenmelidir.
- Başlangıç soruları UI'ın bağlantısız durum fallback'idir; backend yardım önerileri ise katalogdan dinamik türetilir.

## Verification

```bash
cd backend && PYTHONPATH=. ../.venv/bin/pytest -q tests
cd backend && PYTHONPATH=. ../.venv/bin/python -m tools.evaluation.question_variations --strict
cd frontend && npm test
cd frontend && npm run build
```
