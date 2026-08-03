# LIVE-CATEGORY-GROUNDING-001 — Walkthrough

## Canlı doğrulama

Bağlantı `PusulaComed.dbo.vw_RandevuRaporu` için Windows kimlik doğrulaması ve
salt-okunur allowed-object sınırıyla doğrulandı. Güvenli `ValueCatalog` yalnız
kategori değerlerini okudu; hasta verisi alınmadı.

| Sütun | Farklı değer | Katalog davranışı |
|---|---:|---|
| `RandevuDurumu` | 5 | Tam küme; `İptal` cevaplanamaz |
| `CinsiyetId` | 3 | Tam E/K/D kod kümesi |
| `RandevuTipiAdi` | 4 | Tam randevu tipi kümesi |
| `Uyruk` | 149 | Kısmi prompt metadata'sı + canlı değer grounding |

## Ajan davranışı

- “Kaç Türk hasta var?” → `Türkiye` değerine bağlanır.
- “Iraklı hastalar” → `Irak` ve `Irak 2` nedeniyle netleştirme ister.
- “İngiliz hastalar” → kaynakta doğrulanan `Ingiltere` değerine bağlanır;
  `Birleşik Krallık` kayıtlarını birleştirdiğini iddia etmez.
- “İptal oranı” → kaynakta bu durum olmadığı için sayı uydurmaz.
- Bağlamsız “Radyoloji” → randevu tipi/bölüm çakışması nedeniyle alanın açık
  söylenmesi önerilir.

## LLM bağlamı

Her kategorik kolon kartı artık aşağıdaki ayrımı taşır:

- Değerler canlıda doğrulandı mı?
- `known_values` tam küme mi, örnek mi?
- Canlı farklı değer sayısı kaç?
- Hangi tarihte doğrulandı?
- Kaynak veri kalitesi ve grounding notları neler?

149 uyruk değeri prompt'a kopyalanmaz; yalnız doğrulanmış metadata ve güvenli
uyarılar gider. Gerçek filtre değeri her sorguda `ValueCatalog` ile bağlanır.

## Doğrulama sonucu

- Odaklı kategori/grounding paketi: `117 passed`.
- Tam backend regresyonu: `2455 passed, 1 skipped`.
- Ruff: değiştirilen Python dosyalarında hata yok.
