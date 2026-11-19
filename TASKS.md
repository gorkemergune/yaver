# TASKS — Faz 0

Claude Code ile sırayla. Her madde ayrı commit. Bitince `[x]`.

## 0.1 İskelet
- [ ] Repo yapısı (CLAUDE.md'deki klasör yapısı), `.gitignore`, `.env.example`
- [ ] `docker-compose.yml`: `db` (pgvector/pgvector:pg16), `api` (FastAPI, uvicorn --reload dev'de), `web` (Vite dev / nginx prod)
- [ ] Backend: FastAPI app, `config.py` (pydantic-settings), `/health`
- [ ] Alembic kurulumu, async SQLAlchemy session
- [ ] Frontend: Vite + React + TS + Tailwind + TanStack Query, boş sohbet ekranı
- [ ] ruff, mypy, pytest, eslint ayarları

## 0.2 Veri modeli
- [ ] Modeller + ilk migration: terms, courses, recurring_blocks, block_overrides, events, attendance, tasks, followups, memories, conversations, messages, change_log, llm_usage
- [ ] `services/schedule.py`: bir tarih için "etkin plan" hesaplama (recurring + overrides + events + tasks)
- [ ] Testler: iptal edilen blok görünmüyor, taşınan blok yeni saatte, dönem dışı blok yok

## 0.3 Zaman çözümleyici
- [ ] `core/time_resolver.py`: Türkçe göreli tarihler (bugün, yarın, öbür gün, bu/gelecek <gün>, hafta sonu, "28-29 kasım", "3 hafta sonra")
- [ ] Modelin bağlamı için `build_calendar_context(today)` → bugün + 14 gün listesi (tarih, gün adı)
- [ ] Kapsamlı testler (yıl sonu geçişi, Pazar/Pazartesi hafta başı)

## 0.4 LLM router
- [ ] `config/providers.yaml` + `llm/pricing.yaml`
- [ ] OpenAI-compatible provider (Groq, OpenRouter, Ollama)
- [ ] Anthropic provider (prompt caching ile)
- [ ] Ortak tool-call formatına normalizasyon
- [ ] Failover (429/5xx, geçersiz tool call x2) ve budget guard
- [ ] Her çağrıda `llm_usage` kaydı; `GET /api/usage/month`

## 0.5 Ajan ve Yaver ekibi
- [ ] System prompt şablonları: koordinatör + yaver (persona, alan, kullanıcı adı `agents.yaml` ve `.env`'den)
- [ ] Tool registry + şema üretimi (Pydantic → JSON schema); yaver başına araç filtresi
- [ ] `team.py`: `config/agents.yaml` yükleme ve doğrulama (bilinmeyen araç adı → başlangıçta hata)
- [ ] `coordinator.py`: `delegate(agent_id, instruction)` aracı, karışık mesajı bölme, sonuçları birleştirme, ortak `change_set_id`
- [ ] Ada göre doğrudan yönlendirme ("Friday, ...")
- [ ] Senaryo testi: "Bugün linear iptal, yarın 14'te Iceberg toplantısı var, akşam spora gidemem" → 3 yaver, tek geri al
- [ ] Araçlar: get_day_plan, get_week_plan, add/update_recurring_block, cancel_block_on, move_block_on, add/update/delete_event, log_attendance, get_attendance_summary, add/complete_task, add/update_followup, remember/forget, undo
- [ ] `change_log` entegrasyonu; cevapta `change_set` özeti
- [ ] Döngü: max 6 adım, belirsizlikte soru sor, toplu silmede onay iste
- [ ] Fake-LLM ile senaryo testleri ("bugün linear iptal", "yarın quiz var", "EE211'e gitmedim")

## 0.6 Web arayüzü
- [ ] Sohbet ekranı (streaming), değişiklik kartı + Geri al
- [ ] Mesajlarda yaver adı + renk etiketi; "Ekip" sayfası (her yaverin alanı, son yaptıkları)
- [ ] Bugün / Yarın / Hafta görünümleri (salt-okunur, Dayframe stili)
- [ ] Devamsızlık özeti kartı (ders başına kalan hak)
- [ ] Aylık Claude harcaması göstergesi

## 0.7 İlk kurulum
- [ ] İlk açılışta onboarding sohbeti: ad, dönem tarihleri, ders programı (serbest metin/yapıştırma), devamsızlık limitleri, spor günleri, sabit bilgiler (ör. "Cuma Medipol")
- [ ] `examples/sample_schedule.md` (uydurma veri)
