# TASKS — Faz 0

Claude Code ile sırayla. Her madde ayrı commit. Bitince `[x]`.

## 0.1 İskelet
- [x] Repo yapısı (CLAUDE.md'deki klasör yapısı), `.gitignore`, `.env.example`
- [x] `docker-compose.yml`: `db` (pgvector/pgvector:pg16), `api` (FastAPI, uvicorn --reload dev'de), `web` (Vite dev / nginx prod)
- [x] Backend: FastAPI app, `config.py` (pydantic-settings), `/health`
- [x] Alembic kurulumu, async SQLAlchemy session
- [x] Frontend: Vite + React + TS + Tailwind + TanStack Query, boş sohbet ekranı
- [x] ruff, mypy, pytest, eslint ayarları

## 0.2 Veri modeli
- [x] Modeller + migration'lar (5 gruba bölündü): terms, courses, recurring_blocks, block_overrides, events, attendance, tasks, followups, memories, conversations, messages, change_log, llm_usage
- [x] `services/schedule.py`: bir tarih için "etkin plan" hesaplama (recurring + overrides + events + tasks)
- [x] Testler: iptal edilen blok görünmüyor, taşınan blok yeni saatte, dönem dışı blok yok

## 0.3 Zaman çözümleyici
- [x] `core/time_resolver.py`: Türkçe göreli tarihler (bugün, yarın, öbür gün, bu/gelecek <gün>, hafta sonu, "28-29 kasım", "3 hafta sonra")
- [x] Modelin bağlamı için `build_calendar_context(today)` → bugün + 14 gün listesi (tarih, gün adı)
- [x] Kapsamlı testler (yıl sonu geçişi, Pazar/Pazartesi hafta başı)

## 0.4 LLM router
- [x] `config/providers.yaml` + `llm/pricing.yaml`
- [x] OpenAI-compatible provider (Groq, OpenRouter, Ollama)
- [x] Anthropic provider (prompt caching ile)
- [x] Ortak tool-call formatına normalizasyon
- [x] Failover (429/5xx, geçersiz tool call x2) ve budget guard
- [x] Her çağrıda `llm_usage` kaydı; `GET /api/usage/month`

## 0.5 Ajan ve Yaver ekibi
- [x] System prompt şablonları: koordinatör + yaver (persona, alan, kullanıcı adı `agents.yaml` ve `.env`'den)
- [x] Tool registry + şema üretimi (Pydantic → JSON schema); yaver başına araç filtresi
- [x] `team.py`: `config/agents.yaml` yükleme ve doğrulama (bilinmeyen araç adı → başlangıçta hata)
- [x] `coordinator.py`: `delegate(agent_id, instruction)` aracı, karışık mesajı bölme, sonuçları birleştirme, ortak `change_set_id`
- [x] Ada göre doğrudan yönlendirme ("Friday, ...")
- [x] Senaryo testi: "Bugün linear iptal, yarın 14'te Iceberg toplantısı var, akşam spora gidemem" → 3 yaver, tek geri al
- [x] Araçlar: get_day_plan, get_week_plan, add/update_recurring_block, cancel_block_on, move_block_on, add/update/delete_event, log_attendance, get_attendance_summary, add/complete_task, add/update_followup, remember/forget, undo
- [x] `change_log` entegrasyonu; cevapta `change_set` özeti
- [x] Döngü: max 6 adım, belirsizlikte soru sor, toplu silmede onay iste (toplu silme aracı henüz yok; silme tekli)
- [x] Fake-LLM ile senaryo testleri ("bugün linear iptal", "yarın quiz var", "EE211'e gitmedim")

## 0.6 Web arayüzü
- [x] Sohbet ekranı (streaming), değişiklik kartı + Geri al
- [x] Mesajlarda yaver adı + renk etiketi; "Ekip" sayfası (her yaverin alanı, son yaptıkları) — Durum sekmesinde kart olarak
- [x] Bugün / Yarın / Hafta görünümleri (salt-okunur, Dayframe stili)
- [x] Devamsızlık özeti kartı (ders başına kalan hak)
- [x] Aylık Claude harcaması göstergesi

## 0.7 İlk kurulum
- [x] İlk açılışta onboarding sohbeti: ad, dönem tarihleri, ders programı (serbest metin/yapıştırma), devamsızlık limitleri, spor günleri, sabit bilgiler (ör. "Cuma Medipol")
- [x] `examples/sample_schedule.md` (uydurma veri)

## 0.8 Sohbete görsel gönderme
- [x] Web: ataş butonu, sürükle-bırak, Ctrl+V ile yapıştırma; iPhone'da kamera/galeri seçimi; gönderim öncesi küçük önizleme, birden fazla görsel
- [x] Backend: `uploads/` altına kayıt (gitignore'da), HEIC→JPEG, EXIF/konum silme, boyut sınırı + otomatik küçültme (uzun kenar ~1600px), `messages` ↔ ek bağlantısı
- [x] Görseller yalnız Claude'a (vision) gider, Groq'a gitmez: basit görsel → Haiku 5.5; ders programı/tablo/not → Sonnet 5.5 (smart tier, bütçe korumasına dahil)
- [x] Ders programı fotoğrafı: onboarding akışı - önce özet tablo, onayla yaz, tek change_set, okunamayan hücreler "belirsiz", tahmin yok
- [x] Diğer görseller (sınav duyurusu, etkinlik afişi): tarih/saat/yer çıkar, ilgili yavere öneri, onayla ekle
- [x] Testler + gerçek ekran görüntüsüyle live test
