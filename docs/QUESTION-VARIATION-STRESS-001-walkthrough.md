# QUESTION-VARIATION-STRESS-001 Walkthrough

## Üretilen soru aileleri

| Aile | Toplam | Başarılı | Amaç |
|---|---:|---:|---|
| Metrik scalar | 285 | 285 | Metrik ve dönem söyleyişleri |
| Metrik × boyut | 576 | 576 | Kırılım ve uyumluluk kombinasyonları |
| Kolon capability | 24 | 24 | Her kolonun katalogdan açıklanması |
| Privacy guard | 2 | 2 | Ham PII projection engeli |
| **Toplam** | **887** | **887** | **%100 offline baseline** |

## Örnek üretim

Bir metrik ve boyut çifti farklı biçimlerde sınanır:

```text
2024 yılında bölüm adı bazında gerçekleşme oranını göster.
Gerçekleşme oranı, bölüm kırılımında nasıl?
Bölüm tarafında gerçekleşme oranı dağılımı nedir?
```

Bu cümleler kalıcı golden dosyaya yazılmaz. Araç her çalıştırmada aynı katalog
sürümünden deterministik olarak yeniden üretir.

## İlk baseline bulguları

- Metrik eşleme: 0 başarısızlık.
- Deterministik SQL şekli: 0 başarısızlık.
- Gerekli kolon kapsaması: 0 başarısızlık.
- Boyut eşleme: 0 başarısızlık.
- Geçersiz SQL: 0.
- Tarih filtresi kaybı: 0.
- Yanlış out-of-scope: 0.
- PII SELECT ihlali: 0.

Bir vaka birden fazla başarısızlık kodu taşıyabildiği için kod toplamı 214'ten
yüksek olabilir.

## Kullanım

```bash
cd backend
../.venv/bin/python -m tools.evaluation.question_variations --show failing --limit 20
```

Yalnız bir aile:

```bash
../.venv/bin/python -m tools.evaluation.question_variations \
  --family metric_dimension --show failing --limit 20
```

`--strict`, backlog'ta tek bir hata varsa non-zero döndürür. Günlük geliştirme
için varsayılan komut rapor üretir fakat mevcut backlog nedeniyle CI'ı tamamen
kırmaz; pytest regresyon kapısı başarı sayısının 650 altına düşmesini engeller.

## Doğrulama sonucu

- Odaklı varyasyon testleri: `5 passed`.
- Backend tam regresyon paketi: `2270 passed, 1 skipped`.
- Ruff: hata yok.
- Mevcut 284 soruluk golden audit: `255 passed`, `243 deterministic demo ready`.
