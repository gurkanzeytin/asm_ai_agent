# Walkthrough

Temel gösterge kartları artık teknik SQL aliaslarını göstermiyor. Örnek çıktı `Ortalama Randevu Süresi / 67 dk`, `Gerçekleşme Oranı / %0` ve `Toplam Randevu / 88 randevu` biçimindedir.

Tam sayılarda gereksiz ondalık basamak kaldırıldı. Backend `null` döndürdüğünde kart kaybolmak veya sıfır göstermek yerine `Veri yok` yazar; gerçek `0` değerleri ise korunur.
