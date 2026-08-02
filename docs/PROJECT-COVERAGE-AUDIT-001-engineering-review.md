# PROJECT-COVERAGE-AUDIT-001 — Engineering Review

## Doğruluk

- Yeni eşanlamlılar mevcut doğrulanmış metrik/kohortlara bağlanır; yeni kolon veya durum değeri icat edilmez.
- Kohort boyutlandırması `RandevuDurumu` için mevcut durum sayı/oran kolonlarını korur; diğer güvenli boyutları GROUP BY'a taşır.
- Kompozit bölüm alanı SQL Server 2012 compatibility-safe XML ayrıştırma yolunu kullanır.
- İki açık dönem, genel “fark var mı” varyans sinyalinden daha yüksek önceliklidir.
- Kendi içinde gün başına ortalama hesaplayan oran formülü yalnız açık trend sözü varsa zaman serisine yükseltilir.

## Güvenlik

- Tüm SQL yolları salt-okunur deterministik builder ve `SQLValidator` sınırında kalır.
- Maaş/ödeme/telefon/iptal gibi görünüm dışı kavramlarda SQL veya metrik uydurulmaz.
- Doğrulanmamış `ProtokolIslemState` eşlemesi açılmadı.
- Kullanıcı girdisi SQL identifier veya operator olarak serbestçe eklenmez; mevcut allow-list ve predicate renderer korunur.

## Performans

- Çok metrikli performans özeti LLM çağrısını kaldırır ve deterministik tek SQL üretir.
- Oran formülleri için scalar alt sorgular kullanılır; canlı veri hacminde maliyet pazartesi execution plan ile ölçülmelidir.
- Bölüm kohortu XML split yapar; compatibility zorunluluğu nedeniyle doğru fakat pahalı olabilir. Canlı indeks/row-count bilgisi olmadan optimizasyon tahmini yapılmadı.

## Bakım yapılabilirlik

- Değişiklikler katalog, reasoning, planner ve builder sorumluluklarında tutuldu; API rotalarına iş mantığı eklenmedi.
- Prompt eklenmedi ve LLM endpoint'ten çağrılmadı.
- Yeni regression dosyası soru ailelerini açıkça belgeler.
- `planner.py` ve `deterministic_sql_builder.py` büyümeye devam ediyor; sonraki refactor characterization testleriyle yapılmalı.

## Kalan bulgular

- Blocker: canlı SQL Server/UI sonucu henüz doğrulanmadı.
- Important: partial reading yalnız loglanıyor, zenginleştirme rotasına bağlı değil.
- Important: frontend bağımlılık kurulumu eksik.
- Important: auth, CI/CD, paylaşımlı memory ve readiness yok.
- Optional/borç: repo-geneli 655 Ruff bulgusu kademeli temizlenmeli.

## Varsayımlar

- “Geç/acele/24 saat kala” 0–24 saat lead-time olarak yorumlanır ve cevapta varsayım olarak görünür.
- Pazartesiye kadar canlı kategorik değerler ve protokol kodları tahmin edilmez.
- Bu turda mevcut kullanıcı değişiklikleri korunmuş, destructive Git işlemi yapılmamıştır.
