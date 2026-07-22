# ASM AI Agent Smoke-Test Runner

`scripts/smoke_test_runner.py`, çalışan ASM AI Agent backend'ini yalnızca herkese açık
`POST /api/v1/report/` sözleşmesi üzerinden sınayan bağımsız bir HTTP smoke-test ve
değerlendirme aracıdır. Üretim planner, resolver, SQL builder, analytics, context veya
rapor üretim modüllerini import etmez ve değiştirmez.

## Ön koşullar

Backend'i ayrı bir terminalde başlatın:

```powershell
Set-Location backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

Varsayılan hedef `http://localhost:8000/api/v1/report/` adresidir. Runner, mevcut
proje sanal ortamındaki `httpx` paketini kullanır; yeni bir çalışma zamanı bağımlılığı
eklemez.

## Kullanım

Tam paketi çalıştırmak için:

```powershell
.\.venv\Scripts\python.exe scripts\smoke_test_runner.py
```

Toplantı öncesi kısa paket:

```powershell
.\.venv\Scripts\python.exe scripts\smoke_test_runner.py --preset meeting
```

Kimlik, başlık, kategori veya oturum grubuna göre filtrelemek için seçenek birden
çok kez veya virgülle ayrılmış olarak verilebilir:

```powershell
.\.venv\Scripts\python.exe scripts\smoke_test_runner.py `
  --scenario-filter year-only `
  --scenario-filter grounded,clarification
```

Farklı bir sunucu ve çıktı dizini:

```powershell
.\.venv\Scripts\python.exe scripts\smoke_test_runner.py `
  --base-url http://127.0.0.1:9000 `
  --timeout 90 `
  --output-dir artifacts\release-smoke
```

`--session-mode isolated`, her senaryoya ayrı bir oturum verir; aynı senaryonun
takip turları bu oturumu paylaşır. `grouped` (varsayılan), aynı `session_group`
değerindeki senaryoları da aynı oturum zincirinde çalıştırır. Backend canonical bir
`session_id` döndürürse izleyen turda bu değer kullanılır.

## Senaryo kataloğu

Senaryolar `tests/evaluation/smoke_scenarios.json` dosyasındadır. Katalog 12 senaryo
ve 15 tur içerir; additive follow-up, dimension override ve year-only follow-up
senaryoları iki turludur. JSON seçilmesinin nedeni ek YAML bağımlılığı gerektirmemesidir.

Yeni senaryo eklerken benzersiz `id`, `title`, `category`, `question`, `session_group`
ve beklenen alanları tanımlayın. Çok turlu akışlarda `turns` dizisi kullanılır; her tur
üst düzey beklentileri miras alır ve gerekli alanları override edebilir. Ek kontroller
`assertions` dizisiyle eklenebilir. Desteklenen ortak kontroller şunlardır:

- eşitlik, içerme ve içermeme;
- alt-küme ve boolean doğrulama;
- sayısal üst sınır;
- SQL clause içerme/içermeme;
- görünür UI metni;
- provider/model yönlendirmesi;
- bağlam mirası ve katalogdaki özel iş kuralları.

Assertion önem seviyeleri `CRITICAL`, `MAJOR` ve `MINOR` değerleridir. Bir critical
veya en az iki major hata `FAIL`; tek major ya da herhangi bir minor hata `PARTIAL`;
başarısız assertion yoksa `PASS` üretir. Runner'ın process çıkış kodu, herhangi bir
`FAIL` varsa `1`, filtre eşleşmezse `2`, aksi halde `0` olur.

## Çıktılar

Her çalıştırma varsayılan olarak `artifacts/smoke_tests/<timestamp>/` altında şunları
üretir ve aynı dört dosyayı `artifacts/smoke_tests/latest/` altında günceller:

- `smoke_test_results.json`: tam makine-okunur sonuç ve assertion kanıtı;
- `smoke_test_results.csv`: analiz için düz özet;
- `smoke_test_report.md`: Türkçe insan-okunur detay raporu;
- `smoke_test_summary.html`: bağımsız, açılır-kapanır detaylara sahip koyu lacivert özet.

Terminalde test, kategori, sonuç, provider, süre ve kritik sorun tablosu gösterilir.
Timestamp geçmişi silinmez; `latest` yalnızca kolay erişim kopyasıdır.

## Güvenlik ve API görünürlüğü

Runner query satırlarını hiçbir artifact'e yazmaz. Yalnızca `row_count`, kolonlar,
ilk satırın alan adları ve API'nin aggregate analytics/KPI özetleri tutulur. Secret,
token, parola, bearer header ve kimlik bilgisi içeren URL biçimleri tüm serileştirme
öncesinde redact edilir.

Mevcut API response sözleşmesi `sql_source` ve backend'in server-side stack trace'ini
başarılı response'larda garanti etmez. Runner bu alanları uydurmaz; ilgili turda
`unavailable_fields` içine ekler. HTTP client timeout/bağlantı traceback'i varsa
secret redaction sonrasında tanılama olarak saklanır. Backend loglarına doğrudan
erişilmez.

## Testler

Runner bir backend gerektirmeden mocked transport ile doğrulanır:

```powershell
New-Item -ItemType Directory -Force .tmp | Out-Null
.\.venv\Scripts\python.exe -m pytest -q tests\evaluation `
  --basetemp .tmp\pytest-smoke -p no:cacheprovider
```

Testler katalog parse'ı, assertion türleri ve sınıflandırma, çok turlu session reuse,
redaction, güvenli row metadata çıkarımı, timeout/HTTP hata davranışı ve dört artifact
formatını kapsar.

