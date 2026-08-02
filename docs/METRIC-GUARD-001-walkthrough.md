# METRIC-GUARD-001 Walkthrough

## Kullanıcı davranışı

Doğrulanmış bir metrik katalog adıyla sorulduğunda synonym listesinde birebir
karşılığı olmasa bile tanınır. Örneğin “Bölüm bilgisi eksik kayıt sayısı” artık
genel randevu sayısına düşmez; kendi veri kalitesi metriğine bağlanır.

Kaynak sistem kodları doğrulanmamış bir metrik sorulduğunda ajan SQL üretmez:

```text
Hasta kimliği uyuşmayan kayıt sayısı kaç?
```

Bu soru, `HastaId` ve `HastaId2` ilişkisinin iş anlamı doğrulanana kadar açık ve
güvenli bir clarification döndürür. Aynı koruma protokol durum eşlemeleri için de
geçerlidir.

## Ölçüm değişimi

| Ölçüm | Önce | Sonra |
|---|---:|---:|
| Başarılı varyasyon | 673 | 804 |
| Başarı oranı | %75,9 | %90,6 |
| Metrik uyuşmazlığı | 105 | 2 |
| Deterministik SQL yok | 69 | 33 |
| Golden başarılı | 253 | 255 |

51 doğrulanmamış metrik varyasyonu kontrollü clarification olarak doğrulandı.
Sabit-boyutlu COUNT metrikleri için anlamsal olarak aynı SQL planlarının farklı
metrik kimliği yüzünden hata sayılması kaldırıldı.

## Doğrulama

```bash
cd backend
../.venv/bin/python -m pytest -q tests/test_agent_intelligence.py \
  tests/test_question_variation_audit.py
../.venv/bin/python -m tools.evaluation.question_variations --show failing
../.venv/bin/python -m tools.evaluation.golden_audit --show failing
../.venv/bin/python -m pytest -q
```

Sonuç: `2253 passed, 1 skipped`; 887 varyasyonda 804 başarılı; 284 golden
soruda 255 başarılı ve 243 deterministik demo-ready.
