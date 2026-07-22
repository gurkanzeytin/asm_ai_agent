# Temel Gösterge Kart Düzeni - Walkthrough

`buildAnalyticsCards`, tek bir çözülmüş metrik varsa bu adı `context` alanında taşır. KPI etiketi yalnızca `Toplam`, `Ortalama`, `En Yüksek Kategori` gibi ayırt edici kısmı içerir.

`ChatMessage`, bütün kartların bağlamı aynıysa metrik adını "Temel göstergeler" başlığının yanında bir kez gösterir. Grid dört eşit sütun kullanır. Kart değerleri uzunluğa göre üç sabit yazı boyutundan birini seçer; değer ve etiket alanları iki satırla sınırlıdır.

Uzun metinler karttan taşmaz. Kesilen tam içerik fareyle üzerine gelindiğinde tarayıcı başlığında görülebilir.
