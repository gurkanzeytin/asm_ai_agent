# Engineering Review

## Değerlendirme

- Logo için tek asset ve tek React bileşeni bulunur.
- SVG içeriği çalışma zamanında kopyalanmaz veya farklı bileşenlere gömülmez.
- Dış asset kullanımı Canva SVG içindeki kimlik ve gömülü veri çakışmalarını önler.
- Animasyonlar marka çizimini değiştirmeden kapsayıcı seviyesinde uygulanır.

## Risk

Kaynak SVG, Canva metadata ve gömülü bitmap içerdiği için yaklaşık 139 KB boyutundadır. Görsel kalite onaylandıktan sonra SVG optimizer ile metadata temizliği ayrıca yapılabilir.
