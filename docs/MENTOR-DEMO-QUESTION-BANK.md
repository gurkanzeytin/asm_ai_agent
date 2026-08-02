# Mentor Demo Question Bank

## Hedef

Amaç yalnız “2025 bölüm bazında randevu sayısı” gibi tek bir kalıbı çalıştırmak değil; `dbo.vw_RandevuRaporu` görünümündeki 24 kolonun izin verdiği soru uzayını metrik, filtre, kırılım, dönem, karşılaştırma ve takip sorusu bileşimleriyle kapsamak.

Doğal dilde olası cümle sayısı sonsuzdur. Bu nedenle güvenilir yaklaşım cümle ezberlemek değil, aşağıdaki soru gramerini ve eşdeğer söyleyişleri test etmektir.

## Soru üretme grameri

Bir analitik soru çoğunlukla şu parçalardan oluşur:

```text
[DÖNEM] + [KAPSAM/FİLTRE] + [METRİK] + [KIRILIM] + [SIRALAMA/EŞİK] + [ÇIKTI]
```

Örnek:

```text
2024 yılında + Gelmedi durumundaki + randevu oranını + bölüm bazında
+ en yüksek ilk 5 + grafik olarak göster
```

Bu yapı tek başına yüzlerce anlamlı kombinasyon üretir. Her kombinasyonun iş açısından geçerli olup olmadığı metrik ve ilişki kataloglarıyla sınırlandırılır.

## Dönem varyasyonları

- bugün, dün, yarın
- bu hafta, geçen hafta, son 7 gün
- bu ay, geçen ay, son 30 gün
- bu çeyrek, geçen çeyrek, 2025 ilk çeyrek
- bu yıl, geçen yıl, 2024 yılı
- 2024 Ocak, 2024 Ocak-Haziran
- 2024 ile 2025
- bu ay ile geçen ay
- hafta içi / hafta sonu
- günlük, haftalık, aylık, yıllık
- randevu tarihine göre (`BaslangicTarihi`)
- oluşturulma tarihine göre (`CreatedDate`)
- protokol açılış tarihine göre (`ProtokolAcilisTarihi`)

## Metrik varyasyonları

### Hacim

- toplam randevu sayısı
- tekil hasta sayısı
- tekil doktor sayısı
- gerçekleşen, gelmeyen, bekleyen, giriş yapılmış veya işlemi süren randevu sayısı
- protokol açılan randevu sayısı
- aynı gün alınan randevu sayısı

### Oran ve pay

- gelmeme oranı
- gerçekleşme oranı
- protokole dönüşüm oranı
- aynı gün randevu alma oranı
- kadın/erkek hasta payı
- yabancı uyruklu payı
- belirli bir uyruk, hizmet, kategori veya randevu tipinin toplam içindeki payı

### Süre

- ortalama, minimum ve maksimum planlanan randevu süresi
- başlangıç-bitiş tarihinden hesaplanan fiili süre
- planlanan ve fiili süre farkı
- randevu oluşturma ile randevu tarihi arasındaki lead time
- randevu ile protokol açılışı arasındaki gecikme

### Davranış

- hasta başına randevu
- birden fazla randevusu olan hasta sayısı
- farklı şubelerde tekrar eden hastalar
- aynı gün birden fazla hizmet veya doktor gören hasta-gün sayısı
- iki dönemde de randevusu bulunan ortak hasta sayısı

### Veri kalitesi

- doktor/bölüm bilgisi eksik kayıtlar
- bitiş tarihi başlangıçtan önce olan kayıtlar
- sıfır veya negatif süreler
- planlanan ve hesaplanan süre uyuşmazlığı
- hasta kimliği uyuşmazlığı
- protokol durum tutarsızlığı

## Kırılım ve filtre varyasyonları

- şube (`SubeAdi`)
- bölüm/branş/klinik (`GenelRandevuBolumAdi`)
- doktor veya randevu kaynağı (`GenelRandevuKaynakAdi`, `DoktorId`)
- randevuyu oluşturan kişi/sistem (`RandevuyuVeren`)
- randevu tipi (`RandevuTipiAdi`)
- randevu durumu (`RandevuDurumu`)
- hizmet (`HizmetAdi`)
- kategori (`KategoriAdi`)
- uyruk (`Uyruk`)
- cinsiyet (`CinsiyetId`)
- yaş grubu (`DogumTarihi` türetimi)
- protokol işlem durumu (`ProtokolIslemState`)
- gün, hafta, ay, yıl ve saat dilimi

## Doğrulanmış 60 soruluk mentor seçkisi

Bu seçki offline ortamda planner -> deterministic SQL -> SQL Validator hattından geçer. Canlı gösterimde kategori değerlerinin gerçek veritabanıyla eşleşmesi ayrıca gerekir.

### Sayım

1. Bugün kaç randevu var?
2. Kardiyoloji bölümünde bu hafta kaç randevu var?
3. Kaç farklı hasta randevu almış?
4. Gerçekleşen randevu sayısı kaç?
5. Bu ay kaç randevuda hasta gelmedi?
6. Aynı gün içinde alınan randevu sayısı nedir?

### Dağılım

7. Randevuların şubelere göre dağılımı nedir?
8. Durum bazında randevu adetleri nedir?
9. Uyruklara göre hasta dağılımını göster.
10. Cinsiyete göre randevu dağılımı nasıl?
11. Hizmetlere göre randevu sayıları nedir?
12. Şubelerdeki gelmeme sayılarının dağılımını göster.

### Sıralama

13. En çok randevu alan 5 bölüm hangisi?
14. En yoğun şube hangisi?
15. İlk 10 hizmeti randevu adedine göre listele.
16. Gelmeme sayısı en yüksek 5 bölümü sırala.
17. En uzun ortalama randevu süresine sahip bölüm hangisi?
18. Hasta sayısı en fazla olan bölüm hangisi?

### Oran ve pay

19. Bu ay gelmeme oranı nedir?
20. Şubelere göre gelmeme oranlarını karşılaştır.
21. Bölüm bazında gerçekleşme oranları nedir?
22. Gerçekleşme oranı en yüksek şube hangisi?
23. Randevuların ne kadarı protokole dönüşüyor?
24. 2024 yılında Türk olmayan uyrukların oranı nedir?

### Trend

25. Son 3 ayda aylık randevu trendi nasıl?
26. Günlük randevu sayıları bu ay nasıl seyretti?
27. Gelmeme sayılarının aylık trendi nasıl?
28. Tekil hasta sayısının aylık değişimi nedir?
29. Şube bazında aylık randevu trendlerini göster.
30. Protokol açılışlarının aylık trendini göster.

### Dönem karşılaştırma

31. Bu ay ile geçen ayın randevu sayılarını karşılaştır.
32. Bu yıl ile geçen yılın toplam randevularını kıyasla.
33. Gelmeme oranı geçen aya göre arttı mı azaldı mı?
34. Geçen aya göre tekil hasta sayısı ne kadar değişti?
35. Bölümlerin randevu sayıları önceki aya göre nasıl değişti?
36. Ortalama randevu süresi geçen aya göre değişmiş mi?

### Süre

37. 2024 yılının ortalama randevu süresi nedir?
38. Bölümlere göre ortalama randevu sürelerini göster.
39. Hastalar randevularını kaç gün önceden alıyor?
40. Randevu oluşturma ile randevu tarihi arasında ortalama kaç gün var?
41. Planlanan süre ile gerçek süre arasındaki fark nedir?
42. Hizmet bazında ortalama randevu süresi kaç?

### Çapraz analiz

43. Şube ve bölüm bazında randevu sayılarını ver.
44. Bölüm ve randevu tipi kırılımında adetleri göster.
45. Kaynak ve durum bazında randevu dağılımı nedir?
46. Cinsiyet ve bölüm kırılımında hasta sayıları nedir?
47. Uyruk ve bölüm bazında gelmeme oranlarını incele.
48. Şube ve hizmet bazında ortalama süreleri göster.

### Tekrar davranışı

49. Hasta başına ortalama randevu sayısı nedir?
50. Birden fazla randevusu olan hasta sayısı kaç?
51. Bölüm bazında hasta başına randevu sayısını göster.
52. Şubelere göre tekrar eden hasta sayılarını çıkar.
53. Hasta başına randevuyu şubelere göre kıyasla.
54. Ayda birden fazla gelen hasta sayısının trendini göster.

### Veri kalitesi

55. Doktor bilgisi eksik kaç randevu var?
56. Bitiş tarihi başlangıçtan önce olan kayıt var mı?
57. Süresi sıfır veya negatif randevu sayısı kaç?
58. Planlanan süre ile tarih farkı uyuşmayan kayıt sayısı nedir?
59. Şube bazında eksik doktor kayıtlarını göster.
60. Geçersiz tarih aralıklı kayıtların aylık dağılımını çıkar.

## Aynı sorunun dil varyasyonları

### Randevu hacmi

- 2024 toplam randevu sayısı kaç?
- 2024'te kaç randevu olmuş?
- 2024 randevu adedini verir misin?
- Geçen yıl sistemden kaç randevu geçmiş?
- 2024'te randevu tarafında hacim ne durumda?

### Ortalama süre

- 2024 yılının ortalama randevu süresi nedir?
- 2024'te randevular ortalama kaç dakika sürmüş?
- Geçen yıl ortalama süre kaç dakikaydı?
- 2024 planlanan randevu süresi ortalaması nedir?
- 2024 için ortalama muayene süresini göster.

### Yabancı uyruklu payı

- Yabancı hasta oranı nedir?
- Türk olmayan uyrukların oranı kaç?
- Türkiye dışındaki uyrukların randevu payı nedir?
- Her 100 randevunun kaçı yabancı uyruklu?
- Yabancı uyruklular toplam randevuların yüzde kaçını oluşturuyor?

### Bölüm dağılımı

- Bölüm bazında randevu sayılarını göster.
- Branşlara göre randevu adetleri nedir?
- Kliniklerde randevu yükü nasıl dağılıyor?
- Hangi bölümlerde yoğunluk var?
- Bölüm bölüm randevu hacmini çıkar.

### Gelmeme oranı

- Gelmeme oranı nedir?
- No-show yüzdesi kaç?
- Gelmeyenlerin toplam içindeki payı nedir?
- Her 100 randevudan kaçına gelinmiyor?
- Hastaların gelmediği randevuların oranını göster.

## Takip sorusu varyasyonları

```text
2024 toplam randevu sayısı kaç?
→ Bunu bölüm bazında kır.
→ En yüksek ilk 5'i göster.
→ Gelmeme oranını da ekle.
→ 2025 ile karşılaştır.
→ Çizgi grafik yap.
```

```text
2024 ortalama randevu süresi nedir?
→ Şubelere göre dağıt.
→ En uzun süreli ilk 3 şubeyi göster.
→ Geçen yılla kıyasla.
```

## Görünümün cevaplayamayacağı sorular

Ajan bu sorularda SQL üretmek yerine hangi verinin eksik olduğunu açıklamalıdır:

- İptal nedeni veya doğrulanmış iptal metriği
- Tanı, teşhis, reçete ve ilaç
- Fatura, ödeme, gelir ve maaş
- Adres, telefon, pasaport ve sigorta
- Doktor uzmanlık alanı
- Hasta adı/soyadı veya başka ham kişisel veri listeleri

## Demo kullanım kuralı

1. Önce `mentor_demo_pack.json` içindeki sorularla smoke test çalıştır.
2. Canlı DB'de kategori değerleri için value grounding doğrulaması yap.
3. Mentora açıkça yalnız `vw_RandevuRaporu` görünümündeki analitik soruların kapsamda olduğunu söyle.
4. Kapsam dışı bir soru gelirse ajan “yanıt veremiyorum” demek yerine eksik kolonu ve cevaplayabildiği yakın soruları önermeli.
5. Demo sonrası yeni soru başarısızsa aynen evaluation vakasına ekle; cümleye özel yama yerine genel dil kuralını düzelt.

## Ölçülen durum

- Golden soru bankası: 284 soru.
- Offline kontrollü/başarılı davranış: 255 soru.
- Deterministik demo hazır: 243 soru.
- Deterministik SQL'i henüz olmayan cevaplanabilir şekiller: 6 soru.
- Blind gerçek-dil paketi: ilk değişikliklerle 59/90.
- Otomatik görülmemiş soru stres paketi: 887 sorudan 887 başarılı (%100);
  geçersiz SQL, tarih kaybı, yanlış out-of-scope ve PII SELECT ihlali sıfır.

Golden audit komutu:

```bash
cd backend
../.venv/bin/python -m tools.evaluation.golden_audit --show passing
```
