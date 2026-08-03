# ASM AI Agent — Randevu Analitiği

Doğal Türkçe sorulardan randevu raporları üreten yapay zekâ ajanı.

Kullanıcı `"2024 ve 2025 randevu sayılarını karşılaştır"` yazar; sistem soruyu anlar, güvenli SQL üretir, SQL Server üzerinde çalıştırır ve sonucu Türkçe özet, tablo veya grafik olarak sunar. Takip sorularını hatırlar: `"bunu bölüm bazında kır"` dediğinizde önceki kapsamı korur.

---

## İçindekiler

- [Ne yapar?](#ne-yapar)
- [Mimari](#mimari)
- [Teknoloji](#teknoloji)
- [Kurulum](#kurulum)
- [Çalıştırma](#çalıştırma)
- [Testler](#testler)
- [Geliştirme](#geliştirme)
- [Proje yapısı](#proje-yapısı)
- [Tasarım kararları](#tasarım-kararları)
- [Bilinen sınırlar](#bilinen-sınırlar)

---

## Ne yapar?

**Doğal dil → SQL → Rapor**

| Yetenek | Örnek soru |
|---|---|
| Temel metrikler | `2024 yılında toplam kaç randevu var?` |
| Kırılım / dağılım | `Randevuları bölüm bazında kır` |
| Sıralama & limit | `En yoğun ilk 10 bölümü getir` |
| Dönem karşılaştırma | `2024 ve 2025 randevu sayılarını karşılaştır` |
| Çoklu metrik karşılaştırma | `2024 ve 2025 için toplam, gerçekleşen ve gelmeyen randevuyu karşılaştır` |
| Yıl bazında kırılım | `2022 2023 2024 2025 randevu sayılarını tek tek ver` |
| Oran analizleri | `Gelmeme oranı en yüksek bölümler` |
| Eşik / filtre | `1000 altındaki bölümleri ele` |
| Trend | `2023 aylık randevu trendini göster` |
| Demografi | `Kaç adet türk hasta var?` · `Uyruklara göre hasta dağılımı` |
| Belirsiz yönetim sorusu | `Geçen seneye kıyasla işler nasıl gidiyor?` |
| Çıktı biçimi | `Çizgi grafik yap` · `Grafik değil, sadece tablo` · `SQL'i çalıştırmadan ver` |

### Konuşma hafızası

Takip sorularında yıl, metrik, kırılım ve filtreler korunur:

```
> 2024 gelmeyen randevu sayısı nedir?     →  30.191
> Bunu bölüm bazında kır.                 →  58 bölüm  (2024 kapsamı + metrik korunur)
> İlk 5 bölümü göster.                    →  ilk 5 satır
```

### Güvenlik ve dürüstlük ilkeleri

- Yalnızca izin verilen görünüm sorgulanır (`DATABASE_ALLOWED_OBJECTS`); üretilen SQL çalıştırılmadan önce doğrulanır.
- Bölüm/doktor gibi değerler **veritabanındaki gerçek değerlere** bağlanır. Eşleşme yoksa uydurulmaz; birden fazla eşleşme varsa kullanıcıya sorulur.
- Cevaplanamayan soru bir çökme değil, yönlendirilmiş bir cevaptır (`NO_RESULT_GUIDANCE`, `ASK_CLARIFICATION`, `OUT_OF_SCOPE`).
- Bir kısıt uygulanamadıysa cevap bunu **açıkça söyler**, sessizce kapsam daraltmaz.

### Doğrulanmış veri sözlüğü

Kategori değerleri tahmin edilmez; kaynak veritabanına karşı doğrulanır ve
katalogda hangi kümenin **tam** olduğu ayrıca işaretlenir:

| Alan | Değer | Kapsam |
|---|---|---|
| Randevu durumu | Gerçekleşti · Giriş Yapılmış · İşlem Sürmekte · Gelmedi · Beklemede | Tam küme; `İptal` bu veride yok |
| Cinsiyet | `E` · `K` · `D` | Tam küme |
| Randevu tipi | Poliklinik · Radyoloji · Kemoterapi · Ameliyat | Tam küme |
| Uyruk | 149 farklı değer | Tam liste prompt'a gömülmez; her değer canlı katalogdan bağlanır |

Bu ayrım önemlidir: "beş durumun hepsini biliyoruz" ile "149 uyruktan birini
biliyoruz" aynı şey değildir. `known_values_complete` alanı ikisini birbirinden
ayırır, böylece dil modeline eksik bir liste "tam" diye sunulmaz.

Halk dilindeki ifadeler gerçek değerlere bağlanır — `türk → Türkiye`,
`kalp → Kardiyoloji`, `KBB → Kulak Burun Boğaz`. Bağlanamayan ifade uydurulmaz;
birden fazla adaya uyuyorsa kullanıcıya sorulur.

---

## Mimari

LangGraph tabanlı çok düğümlü bir iş akışı. Her düğüm tek sorumluluk taşır ve hata durumunda çökmez — hatayı duruma yazıp akışı sürdürür.

```
                    ┌─────────────────┐
                    │  analyze_intent │   niyet + konuşma bağlamı
                    └────────┬────────┘
             ┌───────────────┼────────────────┐
             │               │                │
      sohbet / yardım   netleştirme      veri sorusu
             │               │                │
            END             END               ▼
                              ┌───────────────────────┐
                              │   retrieve_context    │  şema + NLU + QueryPlan
                              └───────────┬───────────┘
                              ┌───────────▼───────────┐
                              │ resolve_filter_values │  değerleri gerçek veriye bağla
                              └───────────┬───────────┘
                              ┌───────────▼───────────┐
                              │     generate_sql      │  deterministik üretici + LLM yedeği
                              └───────────┬───────────┘
                              ┌───────────▼───────────┐
                              │     validate_sql      │  plan uyumu + güvenlik
                              └───────────┬───────────┘
                              ┌───────────▼───────────┐
                              │      execute_sql      │  SQL Server
                              └───────────┬───────────┘
                              ┌───────────▼───────────┐
                              │    analyze_results    │  deterministik analitik
                              └───────────┬───────────┘
                              ┌───────────▼───────────┐
                              │   generate_insights   │  → observations → report
                              └───────────┬───────────┘
                                         END
```

### Deterministik çekirdek

Projenin ayırt edici yanı: **SQL'in çoğu LLM'siz üretilir.**

`QueryPlanner` soruyu tipli bir `QueryPlan`'e çevirir (metrikler, boyutlar, dönemler, filtreler, eşikler). `DeterministicSQLBuilder` bu plandan doğrudan T-SQL üretir. LLM yalnızca planın karşılamadığı durumlarda devreye girer.

Kazanç: aynı soru her seferinde aynı SQL'i üretir, saniyenin altında yanıtlanır ve `PlanComplianceValidator` üretilen SQL'in plandaki her kısıtı taşıdığını doğrular.

### Katmanlar

| Katman | Sorumluluk |
|---|---|
| `semantics/` | Anlamsal çözümleme, metrik/boyut katalogları, eşanlamlılar |
| `planning/` | `QueryPlan` üretimi, değer bağlama, plan–SQL uyum denetimi |
| `services/` | Sorgu analizi, deterministik SQL üretimi, SQL doğrulama |
| `context/` | Konuşma hafızası, takip sorusu çözümleme, plan birleştirme |
| `analytics/` | Sonuç profilleme, tipli sonuç sözleşmeleri, grafik önerisi |
| `insights/` | Bulgu üretimi ve anlatı |
| `reporting/` | Çıktı politikası (metin / tablo / grafik / SQL), Türkçe şablonlar |

---

## Teknoloji

| Alan | Teknoloji |
|---|---|
| Backend | Python 3.12 · FastAPI · LangGraph · SQLAlchemy (async) · Pydantic v2 |
| Veritabanı | Microsoft SQL Server (aioodbc · ODBC Driver 18) |
| LLM | Ollama (yerel, `qwen3:8b`) · gömme: `nomic-embed-text` · opsiyonel uzak sağlayıcı |
| Frontend | React 19 · TanStack Router/Query · Vite · Tailwind · Recharts · Motion |

---

## Kurulum

### Gereksinimler

- Python 3.12+
- Node.js 20+
- Microsoft SQL Server + ODBC Driver 18
- [Ollama](https://ollama.com) (yerel LLM için)

### 1. Python ortamı

```bash
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### 2. Ortam değişkenleri

```bash
copy .env.example .env
```

`.env` içinde en azından şunları kendi ortamınıza göre düzenleyin:

```ini
DB_SERVER=SUNUCU_ADINIZ
DB_DATABASE=VERITABANI_ADI
DB_TRUSTED_CONNECTION=true                    # Windows kimlik doğrulaması
DATABASE_ALLOWED_OBJECTS=dbo.vw_RandevuRaporu
LLM_PROVIDER=ollama
OLLAMA_MODEL=qwen3:8b
```

> `DATABASE_ALLOWED_OBJECTS` bir güvenlik sınırıdır: ajan yalnızca burada listelenen nesneleri sorgulayabilir.

### 3. LLM modelleri

```bash
ollama pull qwen3:8b
ollama pull nomic-embed-text
```

### 4. Frontend bağımlılıkları

```bash
cd frontend && npm install
```

---

## Çalıştırma

### VS Code (önerilen)

**`Ctrl+Shift+B`** — backend ve frontend birlikte başlar.

`F5` → *Backend + Frontend* ikisini hata ayıklama modunda başlatır.

### Terminal

```bash
cd backend; ..\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000 --reload
```

```bash
cd frontend; npm run dev
```

| Servis | Adres |
|---|---|
| Arayüz | http://localhost:5173 |
| API | http://localhost:8000 |
| API dokümanı | http://localhost:8000/docs |
| Sağlık kontrolü | http://localhost:8000/health |

> `uvicorn` komutunu doğrudan çağırmayın — `python -m uvicorn` kullanın. Windows'ta `uvicorn.exe` kısayolu "Erişim engellendi" hatası verebilir.

---

## Testler

```bash
cd backend; ..\.venv\Scripts\python.exe -m pytest tests -q
```

```bash
cd frontend; npm test
```

Güncel durum: **2.455 backend testi**, **142 arayüz testi**. Testler LLM veya veritabanı gerektirmez; planlama, SQL üretimi, uyum denetimi ve konuşma bağlamı sahte bağımlılıklarla uçtan uca çalışır.

### Değerlendirme paketi

Gerçek kullanıcı senaryolarını toplu koşturmak için:

```bash
cd backend; ..\.venv\Scripts\python.exe -m tools.evaluation run --suite expert
```

Vakalar `backend/app/resources/evaluation_cases.json` içinde; sonuçlar `backend/evaluation/results/` altına yazılır.

### Plan taraması

Asıl tehlike "cevap gelmemesi" değil, **cevabın gelmesi ve yanlış olması**. Bu
tarama tüm soru setini plan seviyesinde koşturup o imzayı arar: kullanıcının
adını verdiği bir değer plana yansımamış mı, metrik yanlış bir hacme mi düşmüş,
plan ile SQL uyuşuyor mu.

```bash
cd backend; ..\.venv\Scripts\python.exe -m tools.plan_sweep
```

Veritabanına gitmez, LLM çağırmaz, çalışan hiçbir şeye dokunmaz — her planlayıcı
değişikliğinden sonra koşturulabilir. 402 soru, saniyeler.

---

## Geliştirme

Kod stili `pre-commit` ile otomatik denetlenir:

```bash
pre-commit install
```

Elle çalıştırmak için:

```bash
black .            # biçimlendirme
ruff check .       # linting
isort .            # import sıralama
pre-commit run --all-files
```

---

## Proje yapısı

```
asm_ai_agent/
├── backend/
│   ├── app/
│   │   ├── main.py                    # FastAPI giriş noktası
│   │   ├── api/v1/endpoints/          # /report · /context · /health
│   │   ├── agent/
│   │   │   ├── graph.py               # LangGraph iş akışı
│   │   │   ├── state.py               # Akış durumu
│   │   │   └── nodes/                 # analyze_intent, generate_sql, ...
│   │   ├── semantics/                 # Anlamsal çözümleme ve kataloglar
│   │   ├── planning/                  # QueryPlan, değer bağlama, uyum denetimi
│   │   ├── services/                  # Sorgu analizi, deterministik SQL üretimi
│   │   ├── context/                   # Konuşma hafızası ve takip çözümleme
│   │   ├── analytics/                 # Sonuç analizi ve grafik önerisi
│   │   ├── insights/                  # Bulgu ve anlatı üretimi
│   │   ├── reporting/                 # Çıktı politikası ve Türkçe şablonlar
│   │   ├── database_intelligence/     # Şema keşfi ve değer katalogları
│   │   ├── resources/                 # Kataloglar, eşanlamlılar, test setleri
│   │   └── prompts/                   # LLM istem şablonları (markdown)
│   ├── tests/                         # Test paketi
│   └── tools/
│       ├── evaluation/                # Değerlendirme paketi
│       └── benchmark/                 # LLM başarım ölçümü
├── frontend/
│   └── src/
│       ├── components/asm/            # Sohbet arayüzü, tablo, grafik panelleri
│       ├── hooks/                     # Sohbet denetleyicisi
│       ├── lib/                       # API istemcisi, biçimlendirme, çıktı niyeti
│       └── locales/tr.ts              # Türkçe arayüz metinleri
└── docs/                              # Özellik bazlı tasarım ve inceleme notları
```

---

## Tasarım kararları

**Deterministik önce, LLM sonra.** SQL üretimi kural tabanlıdır; LLM yalnızca yedektir. Bu, tekrarlanabilirlik ve hız sağlar.

**Düğümler çökmez.** Her düğüm hatayı `state.errors`'a yazar ve akış devam eder. Kullanıcı boş ekran değil, açıklayıcı bir cevap görür.

**Değerler her zaman veriye bağlıdır.** Filtre değerleri serbest metinden türetilmez; gerçek veritabanı değerlerine eşlenir. Eşleşme yoksa uydurulmaz.

**Kısıtlar kaybolmaz.** `PlanComplianceValidator`, üretilen SQL'in plandaki her tarih, filtre, kırılım ve eşiği taşıdığını doğrular; taşımıyorsa sorgu reddedilir.

**Türkçe dil işleme yerleşiktir.** Ek çekimleri (`altındaki`, `çalıştırmadan`), eşanlamlılar (`kalp` → Kardiyoloji, `hekim` → doktor) ve olumsuzluk kalıpları (`hariç tut`, `grafik olmasın`) doğrudan desteklenir.

---

## Bilinen sınırlar

Bunlar gizlenmiş hatalar değil, ölçülmüş ve belgelenmiş sınırlardır.

**Veri tavanı.** Kaynak görünümde gelir, maliyet, memnuniyet, personel,
kapasite, tanı ve klinik sonuç alanı **yoktur**. Bu konulardaki sorular yanlış
cevaplanmaz; kapsam dışı olarak işaretlenir. Aynı şekilde `İptal` durumu bu
veride hiç bulunmadığı için iptal analizi yapılamaz.

**Bölüm kırılımı yavaştır.** `GenelRandevuBolumAdi` virgülle ayrılmış bileşik
değer tutuyor ve veritabanının uyumluluk seviyesi `STRING_SPLIT` desteklemiyor;
ayrıştırma sorgu anında, her satır için XML ile yapılıyor. 1.683.876 satırın
1.634.586'sı bileşik — ama yalnız 425 farklı değer var. Dönem filtresi olan
bölüm sorguları 10–35 sn sürer; **filtresiz olanlar 60 sn'lik veritabanı zaman
aşımına takılır** ve yönlendirilmiş bir hata döner. Çözüm ayrıştırmadan önce
ön-toplama yapmaktır; yol haritasındadır.

**Kaynak veri tam normalize değil.** `Uyruk` alanında aynı ülkeyi temsil
edebilen `Irak`/`Irak 2`, `Ingiltere`/`Birleşik Krallık`, `Dominik`/`Dominik Cum.`
çiftleri var. Sistem bunları kendiliğinden birleştirmez: birden fazla adaya
uyan bir ifade netleştirme sorar.

**Veri Eylül 2025'te bitiyor.** `bugün`, `bu ay`, `son 30 gün` gibi göreli
tarihler boş sonuç döndürür.

---

## Notlar

- Veritabanı bağlantısı Windows kimlik doğrulaması ile yapılandırılmıştır (`DB_TRUSTED_CONNECTION=true`).
- Yerel LLM yanıt süresi donanıma bağlıdır. Deterministik yolla yanıtlanan sorular LLM kullanmaz ve saniyenin altında döner.
- `docs/` klasöründe her özellik için tasarım, uygulama ve inceleme notları bulunur.
