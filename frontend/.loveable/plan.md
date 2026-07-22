Hedef
-----

Mevcut SQL sonuç tablosunu ve yan paneldeki sohbet listesini genişleterek:

1. Gelişmiş filtreleme ve sütun yönetimi
2. Toplu satır seçimi ve işlemleri
3. Ek dışa aktarım formatları (Excel, JSON, SQL INSERT)
4. Sohbet geçmişi ve favorilerin localStorage ile kalıcı hale getirilmesi
   özelliklerini eklemek.

Kapsam
------

1. Gelişmiş filtreleme ve sütun yönetimi (SqlResultsTable)
    - Her sütun başlığına küçük bir filtre menüsü butonu eklenir.
    - Operatörler: eşit, içerir, büyüktür, küçüktür, boş, boş değil.
    - Birden fazla sütuna filtre uygulanabilir; varsayılan mantık AND.
    - Sütunları gizleme / gösterme dropdown'u eklenir.
    - Sütun genişliği fare ile ayarlanabilir hale getirilir.
    - Sütun sıralaması sürükle-bırak ile değiştirilebilir.

2. Toplu satır seçimi ve işlemleri (SqlResultsTable)
    - Tablo başına bir "seçim" kolonu eklenir (checkbox).
    - Header'da "Tümünü seç / Seçimi temizle" kontrolü olur.
    - Seçili satırlar için ayrı bir araç çubuğu görünür.
    - Toplu kopyalama ve toplu dışa aktarma (CSV/JSON) yapılabilir.
    - Seçili satırların sayısı canlı olarak gösterilir.

3. Ek dışa aktarım formatları
    - Mevcut CSV butonunun yanına JSON, Excel (.xlsx) ve SQL INSERT seçenekleri eklenir.
    - JSON: düz array/object çıktısı.
    - Excel: `xlsx` paketi kullanılarak client-side oluşturulur ve indirilir.
    - SQL INSERT: tablo adı sorulur (varsayılan `results`) ve INSERT ifadeleri oluşturulur.

4. Sohbet geçmişi ve favoriler (index route)
    - Mevcut `conversations` state'i localStorage'a yazılır/okunur.
    - Sayfa yenilendiğinde sohbetler ve mesajlar korunur.
    - Favori sohbetler zaten var olan `favorite` flag'iyle sidebar'da öne çıkarılır.
    - Yeni sohbet, silme, favori toggle işlemleri localStorage'ı günceller.

Teknik Detaylar
---------------

- SqlResultsTable içinde filtre state'i (`Array<{column, operator, value}>`) ve görünür/sıralı kolon listesi tutulur.
- Filtreleme mevcut `filtered` `useMemo` zincirine entegre edilir; sanallaştırma ve sayfalama bundan sonra çalışmaya devam eder.
- Sütun resize için başlık hücrelerine sağ kenarlık (resize handle) eklenir; mouse move ile genişlik state'i güncellenir.
- Sütun sürükle-bırak için `@dnd-kit/sortable` veya hafif bir HTML5 drag-drop implementasyonu kullanılabilir. Mevcut bağımlılıklarda dnd-kit yok; eklenmesi gerekir.
- Excel export için `xlsx` paketi eklenecektir. Client-side event handler içinde çalıştığı için Worker/SSR kısıtlamasına takılmaz.
- localStorage key: `asm-conversations-v1`. JSON parse hatalarına karşı try/catch ve fallback uygulanır.
- ARIA: yeni kontroller (checkbox, filtre menüleri, export menü) keyboard navigasyonu ve `aria-label` ile desteklenir.

Bağımlılıklar
-------------

- `xlsx` — Excel dosyası oluşturmak için.
- Opsiyonel: `@dnd-kit/core`, `@dnd-kit/sortable`, `@dnd-kit/utilities` — sütun sürükle-bırak için. Basit HTML5 drag-drop ile başlanabilir; karmaşıklık artarsa dnd-kit'e geçilebilir.

Dosyalar
--------

- `src/components/asm/SqlResultsTable.tsx` — filtreleme, sütun yönetimi, toplu seçim, export menüsü.
- `src/components/asm/SqlChartPanel.tsx` — etkilenmemesi için korunur.
- `src/components/asm/SqlSummaryStats.tsx` — etkilenmemesi için korunur.
- `src/routes/index.tsx` — localStorage persist ve sohbet yönetimi.
- `package.json` — `xlsx` ekleme.

Riskler / Dikkat Edilecekler
----------------------------

- Sanallaştırılmış tablo ile sütun resize/sürükle-bırak uyumu test edilmeli.
- `xlsx` paketinin bundle boyutu yüksek olabilir; ihtiyaç halinde dinamik import (`import('xlsx')`) düşünülebilir.
- Filtre + sıralama + sayfalama kombinasyonunda performans korunmalı.

Onayınızı bekliyorum. İsterseniz tümünü tek seferde, isterseniz önce filtreleme/sütun yönetimi ile başlayıp adım adım ilerleyebilirim.
