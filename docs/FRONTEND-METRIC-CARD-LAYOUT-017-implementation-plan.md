# Temel Gösterge Kart Düzeni - Uygulama Planı

## Amaç

Backend'in farklı uzunluk ve türlerde ürettiği KPI değerlerinin kart gridini bozmasını engellemek.

## Kapsam

- Masaüstünde en fazla dört eşit sütun kullanmak.
- Kartlara sabit minimum yükseklik ve güvenli metin sınırları vermek.
- Uzun değerlerde içeriğe göre kademeli yazı boyutu kullanmak.
- Değer ve etiketleri iki satırda sınırlandırıp tam metni `title` ile erişilebilir tutmak.
- Tek metrik bağlamını her kartta tekrar etmek yerine bölüm başlığında bir kez göstermek.
- Sunum modeli ve DOM düzeni testlerini güncellemek.

## Kapsam Dışı

Metrik hesaplama, sıralama ve backend analytics sözleşmesi değiştirilmez.
