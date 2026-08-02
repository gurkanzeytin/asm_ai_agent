# ASM AI Agent Repository Map

Son inceleme: 2026-08-01

## 1. Yönetici özeti

Bu depo, doğal Türkçe randevu analizi sorularını güvenli, salt-okunur T-SQL sorgularına ve kullanıcıya sunulan raporlara dönüştüren iki katmanlı bir uygulamadır:

- Backend: FastAPI, LangGraph, SQLAlchemy async, SQL Server ve Pydantic.
- Frontend: React 19, TanStack Start/Router/Query, Vite, Tailwind, Recharts ve Motion.
- AI yaklaşımı: deterministik planlama ve SQL üretimi birincil yol; Ollama/Gemini/NVIDIA sağlayıcıları yedek veya anlatı üretim katmanı.
- Güvenlik yaklaşımı: SQL AST doğrulaması, salt-okunur sorgu zorunluluğu, izin verilen nesne listesi, sonuç boyutu sınırları ve PII filtreleri.

Kod tabanı kapsamlıdır: `backend/app` altında 173 Python kaynak dosyası ve yaklaşık 33.6 bin satır; `frontend/src` altında 109 TypeScript/TSX/CSS dosyası ve yaklaşık 14.1 bin satır vardır. Backend test paketi güçlüdür. Buna karşılık gerçek kimlik doğrulama, üretim deployment tanımı, çok süreçli konuşma belleği ve tekrarlanabilir bağımlılık yönetimi henüz belirgin boşluklardır.

## 2. Üst seviye dizin haritası

| Yol | Rol |
|---|---|
| `backend/app` | Üretim backend uygulaması |
| `backend/tests` | Backend birim, sözleşme, regresyon ve entegrasyon testleri |
| `backend/tools/evaluation` | Dataset tabanlı AI/SQL değerlendirme CLI'ı |
| `backend/tools/benchmark` | Model doğruluk, gecikme ve maliyet benchmark altyapısı |
| `backend/scripts` | Veritabanı, LLM, yürütme ve rapor doğrulama yardımcıları |
| `frontend/src` | TanStack Start tabanlı web uygulaması |
| `scripts/smoke_test_runner.py` | Çalışan API'ye karşı kara-kutu smoke testi |
| `tests/evaluation` | Smoke runner senaryoları ve testleri |
| `benchmark` | Benchmark girdileri, sonuçları ve grafik çıktıları |
| `artifacts` | Smoke test raporları ve üretilmiş doğrulama çıktıları |
| `docs` | Özellik bazlı plan, walkthrough ve engineering review belgeleri |
| `outputs` | Sunum ve render edilmiş görsel çıktılar; uygulama runtime'ının parçası değil |
| `.vscode`, `.claude` | Yerel geliştirme ve araç çalıştırma ayarları |

Depo kökünde `.git` bulunmadığı için branch, commit geçmişi, izlenen/izlenmeyen dosyalar ve mevcut diff doğrulanamadı.

## 3. Çalıştırma giriş noktaları

### Backend

- `backend/app/main.py`: `app.main:app` FastAPI uygulaması; CORS, hata eşleyicileri, kök sağlık rotaları ve `/api/v1` router'ını kurar.
- `backend/app/bootstrap.py`: `AppContainer` composition root'u. Veritabanı, repository, şema keşfi, prompt, LLM, SQL doğrulama, servisler, LangGraph ve konuşma belleğini singleton olarak bağlar.
- `backend/app/api/v1/api.py`: `/health`, `/report` ve `/context` alt router'larını birleştirir.
- `backend/app/agent/graph.py`: LangGraph düğümlerini ve koşullu geçişleri derler.

### Frontend

- `frontend/src/routes/__root.tsx`: HTML shell, global hata/not-found sınırları ve QueryClient sağlayıcısı.
- `frontend/src/routes/index.tsx`: Ana sohbet ve sonuç ekranı.
- `frontend/src/routes/login.tsx`: Login görünümü; şu anda gerçek oturum açma servisine bağlı değildir.
- `frontend/src/router.tsx`: TanStack Router oluşturma noktası.
- `frontend/src/start.ts`: TanStack Start request middleware ve SSR hata işleme.
- `frontend/src/server.ts`: Nitro/TanStack server entry wrapper'ı.
- `frontend/vite.config.ts`: Vite geliştirme sunucusu ve `/api` -> backend proxy'si.

### Araç ve değerlendirme giriş noktaları

- `python benchmark.py`: Ollama modellerini production iş akışına karşı ölçer ve rapor/grafik üretir.
- `cd backend && python -m tools.evaluation ...`: Dataset tabanlı white-box/e2e değerlendirmeleri çalıştırır.
- `python scripts/smoke_test_runner.py ...`: Çalışan HTTP API'yi dışarıdan test eder.
- `backend/scripts/verify_*.py`, `quick_test.py`, `compare_insight_modes.py`: Operasyonel doğrulama ve teşhis yardımcılarıdır.

## 4. Backend paketleri ve sorumlulukları

| Paket | Sorumluluk |
|---|---|
| `agent` | Graph state, düğümler ve LangGraph akış topolojisi |
| `api` | HTTP transport, dependency injection erişimi ve hata sözleşmeleri |
| `application_models` | Katmanlar arası tipli workflow DTO'ları |
| `context` | Konuşma hafızası, takip sorusu sinyalleri, bağlam birleştirme ve çözümleme |
| `core` | Pydantic settings ve logging kurulumu |
| `database` | Async SQLAlchemy engine/session kurulumu |
| `database_intelligence` | Şema keşfi, cache, graph, embedding, synonym ve gerçek değer katalogları |
| `semantics` | Metrik/boyut katalogları, ontology, eşleştirme ve anlamsal strateji |
| `planning` | `QueryPlan`, predicate'ler, değer çözümleme, kapsama ve plan-uyum denetimi |
| `services` | Use-case orkestrasyonu, deterministik SQL, yürütme, raporlama ve sonuç güvenliği |
| `repositories` | Veritabanı erişim arayüzü ve scoped async uygulaması |
| `sql_validator` | `sqlglot` AST güvenlik denetimi ve nesne whitelist'i |
| `llm` | Ollama, Gemini ve NVIDIA sağlayıcı adaptörleri ile factory |
| `prompts` | Markdown prompt şablonları, loader ve renderer |
| `parsers` | LLM çıktı ayrıştırma sınırı |
| `analytics` | Sonuç şekli, KPI, trend, karşılaştırma ve grafik önerileri |
| `insights` | Deterministik/yerel/uzak insight routing ve anlatı doğrulama |
| `intelligence` | Kural tabanlı gözlem üretimi |
| `reporting` | Çıktı politikası, sınıflandırma, sunum etiketleri ve şablon render'ı |
| `schemas` | FastAPI request/response sözleşmeleri |
| `shared` | Ortak exception, metin normalizasyonu ve sonuç limitleri |
| `resources` | JSON kataloglar, golden/evaluation datasetleri ve yardım metinleri |

Veritabanına API rotalarından doğrudan erişim görülmedi. Rotalar `ReportingService` ve `ContextManager` bağımlılıklarını alıyor; analitik SQL çalıştırma `ScopedAnalyticalRepository` üzerinden yapılıyor. LLM çağrıları da endpoint içinde değil, provider/service katmanında tutuluyor.

## 5. Frontend paketleri ve sorumlulukları

| Paket | Sorumluluk |
|---|---|
| `routes` | `/`, `/login`, root shell ve route tree |
| `components/asm` | Ürüne özgü sohbet, tablo, grafik, SQL, sidebar, login ve bilgi paneli |
| `components/ui` | Radix tabanlı genel UI primitive'leri |
| `hooks/use-chat-controller.ts` | Konuşma state'i, streaming request, iptal, response mapping ve UI sonuç state'i |
| `lib/api.ts` | Backend HTTP/NDJSON istemcisi ve Zod response doğrulaması |
| `lib/output-intent.ts` | Backend cevabından görünür UI bölümlerini belirleme |
| `lib/presentation.ts` | KPI, metrik ve sunum formatlama |
| `lib/result-limits.ts` | UI satır sınırları |
| `lib/error-*`, `loveable-*` | Client/SSR hata yakalama ve Lovable raporlama |
| `locales/tr.ts` | Türkçe ürün metinleri |

Sohbetler frontend belleğinde tutulur; testler özellikle konuşmaların `localStorage`'a yazılmadığını doğrular. Sayfa yenilemesi frontend konuşma geçmişini kaybettirir.

## 6. Temel veri akışları

### 6.1 Standart rapor akışı

1. Kullanıcı ana sayfadaki prompt kutusuna Türkçe soru girer.
2. `use-chat-controller` conversation ID'yi backend `session_id` olarak gönderir.
3. Frontend önce `POST /api/v1/report/stream` ile NDJSON akışını açar; endpoint yoksa normal `POST /api/v1/report/` çağrısına düşer.
4. `ReportingService` mevcut session bağlamını çözer, raw/resolved soruyu ve başlangıç `AgentState`'ini üretir.
5. LangGraph `analyze_intent` düğümünden başlar.
6. Veri sorusunda `retrieve_context` şema ve semantik bağlamı toplar; `resolve_filter_values` serbest metin değerlerini gerçek veri kataloglarına bağlar.
7. `generate_sql`, öncelikle `QueryPlan` -> `DeterministicSQLBuilder` yolunu kullanır; gerektiğinde LLM fallback'i devreye girer.
8. `validate_sql`, plan uyumu ve `SQLValidator` güvenlik kontrollerini uygular.
9. `execute_sql`, `ExecutionService` -> `ScopedAnalyticalRepository` -> async SQL Server yoluyla sorguyu çalıştırır. Yeniden yazılabilir execution hatasında SQL üretimine yalnızca bir kez dönülür.
10. `analyze_results`, tipli analitik/KPI/grafik metadata'sı üretir ve gerektiğinde doktor etiketlerini zenginleştirir.
11. İstenen moda göre akış burada sonlanabilir (`data`, `visualization`) veya insight -> observation -> report üretimine devam eder.
12. API iç modelini `ReportResponse` sözleşmesine map eder, sonuç satırlarını sınırlar ve frontend tablo/grafik/metin görünümüne dönüştürür.

### 6.2 Kısa devre yolları

- Genel sohbet -> `generate_chat_response` -> son.
- Yardım -> `generate_help` -> son.
- Belirsiz istek/değer -> `generate_clarification` -> son.
- Şema dışında soru veya güvenli olmayan yazma isteği -> `generate_out_of_scope` -> son.
- Konuşma hakkında meta soru -> `generate_conversation_memory` -> son.
- Yalnız SQL isteği -> doğrulama sonrası DB çalıştırmadan son.

### 6.3 Konuşma belleği

- `SessionStore` süreç içi, thread-safe bir sözlüktür.
- Varsayılan pencere 8 turn, TTL 1800 saniyedir.
- Başarılı ve otoritatif sonuçlar belleği günceller; hata/clarification gibi sonuçlar geçerli bağlamı ezmez.
- Birden fazla backend worker kullanılırsa her worker bağımsız bellek taşır; process restart belleği siler.

### 6.4 Remote LLM veri sınırı

- `LLMFactory` Ollama, Gemini ve NVIDIA sağlayıcılarını cache'li singleton olarak oluşturur.
- Insight routing basit vakaları deterministik, daha karmaşık vakaları yerel veya opsiyonel uzak sağlayıcıya yönlendirir.
- `result_safety` identifier/PII kolonlarını ve LLM'e giden satır penceresini sınırlar.
- `llm/remote_policy.py` uzak sağlayıcıya veri gönderme politikasının özel sınırıdır.

## 7. API yüzeyi

| Metot | Yol | Amaç |
|---|---|---|
| GET | `/` | Basit API mesajı |
| GET | `/health` | Statik servis sağlık cevabı |
| GET | `/api/v1/health/` | Versiyonlu statik sağlık cevabı |
| POST | `/api/v1/report/` | Tam workflow, tek JSON response |
| POST | `/api/v1/report/stream` | İlerleme event'leri ve final response içeren NDJSON |
| DELETE | `/api/v1/context/{session_id}` | Tek konuşma belleğini idempotent sıfırlama |

Tespit edilen auth dependency, token doğrulama, kullanıcı/rol modeli veya endpoint authorization kontrolü yoktur.

## 8. Shared utility ve kaynaklar

- `shared/result_limits.py`, `shared/result_window.py`, `services/result_safety.py`: DB, API, UI ve LLM katmanlarında taşınan veri boyutlarını sınırlar.
- `reporting/presentation.py` ve frontend `lib/presentation.ts`: Backend ve frontend sunum/etiketleme sorumluluklarını paylaşır; iki taraftaki sözlüklerin drift riski vardır.
- `semantics/catalog.py` ve `resources/*.json`: Metrik, kolon, ilişki, eşanlamlı ve intent bilgisinin temel kaynağıdır.
- `prompts/*.md`: SQL, şema, insight, observation ve rapor prompt'larıdır.
- `tools/evaluation` ile `resources/evaluation_*.json`: AI davranışı için tekrar üretilebilir kabul/regresyon paketi sunar.

## 9. Background işler ve concurrency

Kalıcı job queue, Celery worker, cron, scheduler veya ayrı background service tespit edilmedi.

`workflow_streaming.py` her streaming HTTP isteği için request-scoped bir `asyncio.create_task` ve `asyncio.Queue` oluşturur. Client bağlantısı kapandığında task iptal edilir. Şema cache yenilemesi uygulama içi/lazy davranıştır; zamanlanmış bağımsız job değildir.

## 10. Test ve kalite yapısı

### Backend

- 88 `backend/tests/test_*.py` modülü bulunur.
- Kapsam: API sözleşmeleri, SQL validator, planlama, semantik eşleme, konuşma hafızası, PII/sonuç güvenliği, provider'lar, insight/analytics, performans ve golden eval senaryoları.
- Runtime SQL Server olmasına rağmen testler DB bağımlılığını SQLite in-memory test double ve mock'larla izole eder.
- Belgelenen komutla (`cd backend && ../.venv/bin/python -m pytest tests -q`) sonuç: **2225 geçti, 1 atlandı**.
- Repo kökünden backend ve root testlerini birlikte çalıştırınca iki test `Path("app/prompts/...")` kullandığı için CWD'ye bağlı olarak hata verir. Bu testlerin ürün davranışından bağımsız taşınabilirlik sorunudur.

### Frontend

- 16 Vitest dosyası bulunur.
- Kapsam: API/stream parser, chat controller, tablo/grafik sunumu, scroll, formatlama, logo ve UI regresyonları.
- Mevcut workspace'te `frontend/node_modules` yoktur; `npm test` bu nedenle `vitest: command not found` ile başlamadı.

### Ek doğrulama

- Root smoke runner birim paketi: **40 geçti**.
- `pre-commit`: trailing whitespace, EOF, Black, isort ve Ruff.
- Backend için coverage eşiği, mypy/pyright veya CI workflow'u tespit edilmedi.
- Frontend için ESLint/Prettier komutları vardır; otomatik CI kapısı tespit edilmedi.

## 11. Ortam değişkenleri

### Uygulama ve API

`APP_NAME`, `APP_VERSION`, `ENVIRONMENT`, `DEBUG`, `INTENT_CONFIDENCE_THRESHOLD`, `API_V1_PREFIX`, `ALLOWED_ORIGINS`, `LOG_LEVEL`

### SQL Server

`DB_SERVER`, `DB_DATABASE`, `DB_DRIVER`, `DB_TRUSTED_CONNECTION`, `DB_TRUST_SERVER_CERTIFICATE`, `DB_ENCRYPT`, `DATABASE_URL`, `DATABASE_POOL_SIZE`, `DATABASE_ECHO`, `DATABASE_SCHEMA`/`DB_SCHEMA`, `DATABASE_ALLOWED_OBJECTS`/`DB_OBJECT`, `DATABASE_CONNECT_TIMEOUT`, `DATABASE_QUERY_TIMEOUT`, `DATABASE_MAX_PAGE_SIZE`, `SQL_DIALECT`

### LLM ve routing

`LLM_PROVIDER`, `OLLAMA_BASE_URL`, `OLLAMA_MODEL`, `OLLAMA_EMBEDDING_MODEL`, `OLLAMA_TIMEOUT`, `LLM_RETRY_COUNT`, `GEMINI_API_KEY`, `GEMINI_MODEL`, `NVIDIA_API_KEY`, `NVIDIA_BASE_URL`, `NVIDIA_MODEL`, `NVIDIA_TIMEOUT_SECONDS`, `NVIDIA_MAX_RETRIES`, `NVIDIA_MAX_TOKENS`, `NVIDIA_TEMPERATURE`, `NVIDIA_TOP_P`, `NVIDIA_THINKING`, `OBSERVATION_LLM_WORDING`, `INSIGHT_ROUTING_ENABLED`, `INSIGHT_DETERMINISTIC_ENABLED`, `INSIGHT_LOCAL_PROVIDER`, `INSIGHT_REMOTE_PROVIDER`, `INSIGHT_REMOTE_COMPLEXITY_THRESHOLD`, `INSIGHT_DETERMINISTIC_MAX_ROWS`

### Bellek, şema ve rapor

`CHAT_MEMORY_MAX_TURNS`, `CHAT_MEMORY_TTL_SECONDS`, `SCHEMA_CACHE_ENABLED`, `SCHEMA_CACHE_TTL`, `AUTO_REFRESH_SCHEMA`, `SCHEMA_MAX_TABLES`, `SCHEMA_MAX_COLUMNS`, `SCHEMA_TOKEN_BUDGET`, `SCHEMA_GRAPH_MAX_DEPTH`, `REPORT_MAX_ROWS`, `REPORT_ANALYTICAL_ROW_THRESHOLD`

### Frontend/build

- `VITE_API_BASE_URL`: Browser API base URL override.
- `BACKEND_URL`: Vite development proxy hedefi.

`.env.example`, settings modelindeki tüm opsiyonları belgelemiyor. Özellikle chat memory, report limitleri, bazı schema limitleri, observation wording ve deterministic insight satır sınırı örnekte yoktur. Ayrıca `.env.example` CORS origin'leri 3000/3001 iken README geliştirme arayüzünü 5173 olarak gösterir; development proxy bu farkı maskeler, doğrudan cross-origin kurulumda ayar güncellenmelidir.

## 12. Deployment ve operasyon temasları

- Backend yerelde Uvicorn ile `127.0.0.1:8000` üzerinde çalıştırılıyor.
- Frontend Vite development server kullanıyor ve `/api` çağrılarını backend'e proxy'liyor.
- TanStack/Lovable Vite config yorumuna göre production build Nitro ve varsayılan Cloudflare hedefini kullanabilir; ancak depoda doğrulanabilir Cloudflare proje/deploy tanımı yoktur.
- `.vscode/tasks.json` ve `.vscode/launch.json` Windows path separator ve `.venv\\Scripts\\python.exe` kullanır; macOS/Linux geliştirici akışı için eşdeğer görev yoktur.
- Dockerfile, Compose, Kubernetes/Helm, Procfile, systemd tanımı, GitHub Actions workflow'u veya deployment script'i tespit edilmedi.
- Alembic bağımlılığı vardır ancak `alembic.ini` ve migration dizini tespit edilmedi; uygulama şu an izin verilen mevcut view üzerinden analitik okuma yapıyor.
- Production reverse proxy, TLS termination, secret manager, process/worker sayısı, log aggregation, metrics/tracing ve rollback yöntemi bilinmiyor.

## 13. Bilinen belirsizlikler

- Git metadata olmadığı için kodun hangi branch/commit'ten geldiği ve dosyaların repository'de izlenip izlenmediği bilinmiyor.
- Gerçek SQL Server şeması yalnızca config ve resource kataloglarından çıkarılabiliyor; canlı DB introspection bu incelemede yapılmadı.
- Gerçek production hosting topolojisi ve Lovable/Cloudflare yayın akışı depoda tanımlı değil.
- API'nin ağ seviyesinde VPN, reverse proxy veya başka bir kimlik doğrulama katmanıyla korunup korunmadığı bilinmiyor.
- Uzak LLM'e production'da hangi veri sınıflarının fiilen gönderildiği smoke testi yapılmadan yalnızca policy kodundan doğrulanabilir.
- `frontend/node_modules` olmadığı için frontend testlerinin güncel makinedeki gerçek geçiş durumu doğrulanamadı.
- `outputs`, `artifacts`, benchmark sonuçları ve cache dosyalarının Git'te izlenme durumu Git metadata olmadan bilinmiyor.

## 14. En yüksek kaldıraçlı 10 iyileştirme fırsatı

1. **Gerçek kimlik doğrulama ve yetkilendirme ekleyin.** `/login` şu anda yalnızca dolu email/şifre sonrası `/` rotasına gider; backend rapor ve context endpoint'leri korumasızdır. Kurumsal SSO/OIDC, kullanıcı kimliği, rol/tenant sınırı ve audit kaydı ilk üretim güvenlik kapısı olmalı.
2. **Üretim deployment ve CI/CD sözleşmesini kodlaştırın.** Backend/frontend build, test, lint, secret/env doğrulama, migration kararı, health/readiness, deploy, smoke test ve rollback adımlarını tek bir pipeline ve runbook'a bağlayın.
3. **Konuşma belleğini paylaşımlı bir store'a taşıyın.** Redis benzeri TTL destekli bir uygulama, restart ve çok-worker tutarlılığını sağlar. Repository-style `SessionStore` arayüzü korunarak küçük bir adapter değişikliği yapılabilir.
4. **Composition root'u lazy ve lifecycle-aware yapın.** `container = AppContainer()` import sırasında DB engine, LLM provider ve graph kuruyor; bu test/CLI importlarını ağırlaştırır ve provider client'larının kapanışı lifespan içinde görünmüyor. Startup'ta kurup shutdown'da engine/provider kapatmak daha güvenli olur.
5. **Büyük hotspot modüllerini güvenli dilimlere ayırın.** `planning/planner.py` (2246), `deterministic_sql_builder.py` (1916), `query_analyzer.py` (1216) ve `SqlResultsTable.tsx` (1523 satır) değişiklik riskini yükseltiyor. Önce characterization testleriyle public davranışı sabitleyip strategy/helper bileşenlerine bölün.
6. **Testleri CWD ve işletim sisteminden bağımsızlaştırın.** Prompt testleri dosya yollarını `__file__`/repo root üzerinden çözmeli; VS Code görevleri platforma göre ayrılmalı. Kökten tek komutla backend + frontend + smoke paketini çalıştıran task runner ekleyin.
7. **Bağımlılıkları tekrarlanabilir hale getirin.** Backend requirement'ları geniş alt sınırlar kullanıyor ve lock dosyası yok; frontend'de hem `bun.lock` hem `package-lock.json` var. Tek package manager seçin, Python lock/constraints üretin ve dependency update bot/CI kontrolü ekleyin.
8. **Config ve doküman drift'ini kapatın.** `.env.example` tüm settings alanlarını içermeli; README port/CORS/Python/platform komutları gerçek config'le eşleşmeli. Settings modelinden env referansı üretmek drift'i kalıcı olarak azaltır.
9. **Prompt yerleşim politikasını netleştirin.** Kök `AGENTS.md` promptların yalnız `/prompts` altında olmasını isterken runtime `backend/app/prompts` kullanıyor. Politika mı kod mu kaynak gerçek olacak kararlaştırılmalı; loader ve testler tek kök üzerinde birleştirilmeli.
10. **Readiness ve gözlemlenebilirliği production seviyesine çıkarın.** Mevcut health endpoint'leri statik cevap veriyor. DB, zorunlu local LLM, opsiyonel remote provider ve schema cache için ayrı liveness/readiness; request/workflow correlation ID; latency/error metricleri ve gerçekten JSON üreten yapılandırılmış log ekleyin.

## 15. Doğrulama adımları

```bash
cd backend
../.venv/bin/python -m pytest tests -q
```

```bash
cd frontend
npm install
npm test
npm run lint
npm run build
```

```bash
cd ..
.venv/bin/python -m pytest tests/evaluation/test_smoke_test_runner.py -q
```

Canlı bağımlılıklar hazırsa son aşamada backend, frontend ve Ollama başlatılıp `scripts/smoke_test_runner.py` ile HTTP sözleşmesi; `backend/scripts/verify_database.py` ile SQL Server bağlantısı doğrulanmalıdır.
