# PROJECT-COVERAGE-AUDIT-001 — Genel Durum ve Eksik Analizi

Tarih: 2026-08-02

## Sonuç

Proje artık yalnız “2025 bölüm bazlı randevu sayısı” gibi ezberlenmiş kalıplara bağlı değil. Doğrulanmış 24 kolon ve 48 metrik üzerinden metrik, boyut, tarih, filtre, kohort, oran, sıralama ve karşılaştırma parçalarını birleştiren genel bir planlama/SQL üretim katmanı var.

Bu tur sonunda çevrimdışı kabul paketi **233/233**, katalogdan üretilen soru varyasyonları **887/887**, backend regresyonu **2413 geçti / 1 atlandı** ve root smoke paketi **40/40** sonucuna ulaştı. Bu sonuç canlı SQL Server ve UI doğrulamasının yerine geçmez; plan ve SQL üretim kapsamasının güçlü olduğunu gösterir.

## Ajan bugün neyi yapabiliyor?

- Sayı, tekil sayı, toplam, ortalama, min/max, oran ve yüzde soruları
- Şube, bölüm, durum, kaynak, uyruk, cinsiyet, hizmet, kategori ve zaman kırılımları
- İki boyutlu çapraz kırılımlar; örneğin kaynak × durum
- İki dönem karşılaştırması, mutlak/yüzdesel değişim ve grup bazlı fark
- Çok metrikli performans özeti: hacim, gerçekleşme oranı, gelmeme oranı, tekil hasta
- Son dakika/24 saat kala alınan randevu kohortu ve gerçekleşme/gelmeme davranışı
- Veri kalitesi: eksik alan, bozuk tarih aralığı, süre-tarih farkı tutarsızlığı
- Katalogda hazır olmayan fakat güvenli kolon/predicate parçalarından kurulabilen kohort oranları
- Konuşma içi takip soruları ve önceki planın kontrollü devamı
- Yalnız SELECT/CTE; her üretilen sorgu SQL validator ve plan uyum kontrolünden geçer

## Bu turda kapatılan gerçek boşluklar

1. “Geç alan”, “acele randevu”, “24 saat kala” ifadeleri mevcut `lead_time_under_24h` kohortuna bağlandı.
2. Kohort sorularında “şubelere/bölümlere göre” boyutu artık SQL'de kaybolmuyor.
3. “Tarih aralığı bozuk” ve “randevu süresi tarih farkıyla tutmuyor” ifadeleri doğrulanmış veri-kalitesi metriklerine bağlandı.
4. “Kaynak ve durum kırılımı” iki ayrı boyut olarak korunuyor.
5. Şube bazında eksik doktor gibi gruplanmış veri-kalitesi sonuçları doğru sonuç sözleşmesini kullanıyor.
6. Boşluğu ölçülen kolonun kendisine göre anlamsız gruplama kaldırıldı; örneğin bölüm bilgisi boş kayıtlar NULL bölüme göre gruplanmıyor.
7. “2024 günlük ortalama randevu” scalar kaldı; açıkça “trend/eğilim” denirse zaman serisine dönüyor.
8. “Yoğunluk” kelimesinin içindeki `gunluk` karakter dizisi artık yanlışlıkla “günlük trend” sayılmıyor.
9. Açık iki dönem varken “fark var mı” sözü genel varyans yerine dönem karşılaştırmasına gidiyor.
10. “Son zamanlarda durumumuz nasıl?” dört KPI'lı deterministik dönem karşılaştırması üretiyor; LLM'in rastgele SQL üretmesine bağlı değil.
11. Maaş gibi görünümde olmayan finansal alanlar uydurulmuyor; neden ve randevu hacmi/gerçekleşme oranı alternatifi veriliyor.
12. Değerlendirme paketi, cevaplanamaz bir alanda neden + alternatif sunmayı hata değil kontrollü sınırlama olarak ölçüyor.

## Önemli riskler ve eksikler

### Kritik — pazartesi canlı doğrulama gerekir

- Gerçek SQL Server distinct değerleri bu bilgisayarda yok. Kategorik değer grounding'i katalog ve önceki doğrulamalara dayanıyor.
- `ProtokolIslemState` kodlarının anlamı doğrulanmamış durumda; tamamlandı/iptal gibi anlamlar çıkarılmamalı.
- SQL Server compatibility level, gerçek sorgu süreleri, timeout ve büyük sonuç davranışı yeniden canlı ölçülmeli.
- UI'da streaming, tablo/grafik sözleşmesi ve mentorun soracağı takip soruları son turda gözle doğrulanmalı.

### Önemli — yanıt oranını daha da yükseltecek mimari boşluk

- Planın bir kısmı anlaşılırken bir kısmı çözülemezse `partial_reading_reasons` üretiliyor fakat yalnız loglanıyor. Bir sonraki yüksek kaldıraçlı özellik, bu parçayı tipli schema-reasoning/LLM plan tamamlamasına göndermek ve sonucu yeniden plan uyumu + SQL validator'dan geçirmektir.
- Canlı değer kataloğunda bulunmayan serbest metin değerlerinde ajan güvenli biçimde clarification verir. Yanlış değer uydurmamak doğru davranıştır fakat kullanıcı bunu “cevap vermedi” olarak algılayabilir; mesajın alternatif sorguyu otomatik önermesi/çalıştırması geliştirilebilir.
- Çok-worker/restart durumunda konuşma belleği kaybolur; `SessionStore` process içidir.

### Üretim ve operasyon riski

- Backend endpoint'lerinde gerçek auth/authorization yok; `/login` yalnız UI görünümüdür.
- CI/CD, Docker/deployment, readiness, rollback ve merkezi gözlemlenebilirlik tanımlı değil.
- Tüm eski repoda 655 Ruff bulgusu var. Bu turda değişen dosyalar temiz fakat repo-geneli lint kapısı henüz açılamıyor.
- Frontend `node_modules` eksik/yarım; `vitest` ve `vite` bulunamadığı için frontend test/build bu makinede doğrulanamadı.
- Kökten çıplak pytest, `scripts` paket çözümleme çakışması yüzünden çalışmıyor; açık `PYTHONPATH` ile smoke paketi geçiyor.

## “Cevap vermeme” nasıl ölçülmeli?

Üç sonucu ayırmak gerekir:

1. **Doğrudan cevap:** Plan + güvenli SQL + veri + yorum.
2. **Kontrollü sınırlama:** İstenen kolon/veri yok; neden ve yapılabilir alternatif verilir. Bu, “yanıt veremiyorum” şeklinde boş bir hata değildir.
3. **Gerçek hata:** Veri mevcut olduğu hâlde plan/SQL/çalıştırma/sunum başarısız olur. Minimuma indirilmesi gereken budur.

233/233 çevrimdışı skor ilk iki sonucu başarı kabul eder. Canlı veriden sonuç üretme oranı ancak pazartesi SQL Server bağlantısıyla ayrıca ölçülebilir.

## Pazartesi canlı turu

1. `.env` ve Windows Authentication/SQL bağlantısını doğrula.
2. 24 kolon için tip, null oranı, yaklaşık cardinality ve güvenli distinct örneklerini çıkar.
3. `ProtokolIslemState` kod eşlemesini kullanıcı/mentor bilgisiyle doğrula; doğrulanmayanı katalogda kapalı tut.
4. Scalar, oran, iki boyut, dönem karşılaştırması, kohort, veri kalitesi ve çok metrikli performans sorularını backend'den çalıştır.
5. Aynı senaryoları UI streaming üzerinden çalıştır; tablo, grafik, açıklama, boş sonuç ve hata mesajlarını kontrol et.
6. Mentor sürpriz sorularını kaydet; gerçek ürün hatalarını yeni regression vakasına dönüştür.

## Doğrulama kanıtı

```text
Backend pytest:             2413 passed, 1 skipped
Genel SQL eval:             233/233, tüm katmanlar %100
Soru varyasyonu:            887/887 (812 deterministik SQL)
Root smoke testleri:        40/40
Değişen Python dosyaları:   Ruff temiz
Frontend test/build:        doğrulanamadı (vitest/vite eksik)
Canlı SQL/UI:               pazartesi bekliyor
```
