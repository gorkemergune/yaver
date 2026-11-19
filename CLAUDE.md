# CLAUDE.md — Yaver

Claude Code bu dosyayı her oturumda okur. Proje kuralları ve mimari kararlar burada; ilerleme ROADMAP.md ve TASKS.md'de.

## Proje özeti
Yaver: chat + ses ile yönetilen, self-hosted kişisel AI asistan. Kullanıcı buton kullanmaz, doğal dille söyler; ajan tool-calling ile veritabanını günceller, değişikliği diff olarak gösterir, geri alınabilir.

Sahibi: Görkem (Yeditepe Bilgisayar Müh.). Geliştirme Windows 11 + Docker Desktop (WSL2) üzerinde. Kullanım: Windows, Mac, iPhone (PWA).

## Temel ilkeler
1. **Chat-first.** UI sadece okumak içindir; her yazma işlemi ajan araçlarından geçer. (UI'de olabilecek tek "buton": Geri al.)
2. **Her mutasyon geri alınabilir.** Tüm yazma araçları `change_log`'a before/after JSON yazar; her asistan cevabı bir `change_set_id` taşır.
3. **Tarih hesabını model yapmaz.** "Yarın", "gelecek perşembe" gibi ifadeler `core/time_resolver.py` ile kodda çözülür. Modele her istekte bugünün tarihi + önümüzdeki 14 günün listesi verilir; araçlar sadece ISO tarih kabul eder.
4. **Tek kullanıcı / instance.** Her kişi kendi Docker'ını çalıştırır. Kodda `user_id` yok; çoklu kullanıcı hedef değil.
5. **BYOK + provider-agnostic.** Tüm LLM çağrıları `llm/router.py` üzerinden. Doğrudan SDK çağrısı yasak.
6. **Kişisel veri repoda olmaz.** Seed dosyaları `data/` altında ve `.gitignore`'da. Örnekler `examples/` altında, uydurma verilerle.
7. **Zaman dilimi:** Anlar (instant) DB'de UTC `timestamptz` (`UTCDateTime` naive datetime'ı reddeder), hesap ve gösterim `APP_TIMEZONE` (varsayılan Europe/Istanbul). Haftalık tekrar eden saatler istisna: yerel duvar saati (`time`) olarak saklanır ki DST'de kaymasın.

## Stack
| Katman | Seçim |
|---|---|
| Backend | Python 3.12, FastAPI, SQLAlchemy 2 (async), Alembic, Pydantic v2 |
| DB | PostgreSQL 16 + pgvector |
| Scheduler | APScheduler (DB jobstore, `misfire_grace_time` + açılışta catch-up) |
| Frontend | React + TypeScript + Vite + Tailwind + TanStack Query, PWA (vite-plugin-pwa) |
| Desktop | Tauri v2 (Faz 4) |
| STT | Groq Whisper (varsayılan), faster-whisper (opsiyonel, local) |
| Embedding | Local multilingual model (sentence-transformers), CPU'da |
| Paketleme | docker compose: `db`, `api`, `web` (nginx) |

Dayframe'den (gorkemergune/dayframe) desenler taşınabilir: proje yapısı, Alembic kurulumu, recurring_blocks/schedule_events ayrımı.

## Klasör yapısı
```
yaver/
  backend/
    app/
      main.py
      config.py              # pydantic-settings, .env
      db/                    # session, base, models/
      api/                   # routers: chat, schedule, briefing, materials, usage, push
      agent/
        coordinator.py       # isteği böler, delegate eder, birleştirir
        team.py              # agents.yaml yükleme, yaver tanımları
        loop.py              # tool-call döngüsü (max 6 adım), her yaver için ortak
        prompts/             # system prompt şablonları (Jinja2)
        tools/               # her araç bir dosya; schema + handler
      llm/
        router.py            # tek giriş noktası: tier seçimi, failover, araç çağrısı doğrulama, kırpma
        providers/           # openai_compat.py (Groq/OpenRouter/Ollama), anthropic.py (prompt caching)
        budget.py            # aylık Claude bütçesi
        usage.py             # maliyet hesabı, llm_usage kaydı, aylık özet
        check_models.py      # `python -m app.llm.check_models`
        pricing.yaml         # USD / 1M token; OpenRouter maliyeti kendisi bildirir
      core/
        time_resolver.py
        change_log.py        # undo altyapısı
        briefing.py
      jobs/                  # scheduler işleri
      rag/                   # ingest, chunk, embed, retrieve
    alembic/
    tests/
  web/                       # React PWA
  desktop/                   # Tauri (Faz 4)
  config/
    providers.example.yaml   # repoda; local kopya providers.yaml (gitignore)
    agents.example.yaml      # repoda; local kopya agents.yaml (gitignore) — yaver ekibi: isimler, alanlar, araçlar
  examples/                  # uydurma örnek ders programı vb.
  docker-compose.yml
  .env.example
```

## Veri modeli (özet)
- `terms` — dönem başı/sonu
- `holidays` — tatil aralıkları (`term_id` NULL = tüm dönemler); class/lab blokları o günlerde yok
- `courses` — `term_id`, kod, ad, hoca, `absence_limit`, renk
- `recurring_blocks` — haftalık tekrar: `kind` (class|lab|sport|work|other), weekday (0=Pzt), start/end_time (**yerel duvar saati**, end<=start → ertesi gün biter), location, `course_id?`, valid_from/to
- `block_overrides` — tek occurrence için iptal/taşıma: `block_id`, date (orijinal yerel tarih), action (cancel|move), new_start_at/new_end_at (UTC, başka güne taşınabilir), reason
- `events` — tek seferlik: `kind` (exam|quiz|makeup|meeting|deadline|hackathon|other), start_at/end_at (UTC; end NULL = an), all_day, `course_id?`, notes
- `attendance` — course_id, date, status (present|absent|excused)
- `tasks` — günlük/haftalık görevler: title, scope (day|week), date/week_start, status, source (user|agent|weekly_plan)
- `followups` — takip: title, status (waiting|positive|negative|done), check_rule (daily|every_n_days|on_date), next_check_at, related_event_id
- `memories` — kalıcı bilgiler ("Cuma günleri Medipol'deyim"): category, content, active
- `course_materials` + `material_chunks` (pgvector) — syllabus, notlar, slaytlar; week_no
- `study_sheets` — course_id, week_no, content_md, model
- `conversations`, `messages` — `messages.agent_id` hangi yaverin konuştuğunu tutar
- `change_log` — change_set_id, entity, entity_id, op, before_json, after_json
- `llm_usage` — provider, model, tier, purpose, in/out/cached tokens, cost_usd
- `push_subscriptions` — Web Push
- `screen_sessions`, `app_limits` (Faz 4)

## Yaver ekibi (çoklu ajan)
Sistem adı Yaver; içinde isimleri kullanıcı tarafından verilen uzman yaverler çalışır. Tanımlar `config/agents.yaml`'da, koda gömülmez.

```
Kullanıcı ──► Koordinatör (Yaver)
                 ├─ delegate("academic",   "...")  → Friday  (dersler, devamsızlık, sınav, materyal)
                 ├─ delegate("agenda",     "...")  → Jarvis  (toplantı, iş, etkinlik, followup)
                 └─ delegate("discipline", "...")  → Karen   (spor, alışkanlık, ekran süresi)
```

Kurallar:
- Kullanıcı her zaman koordinatörle konuşur. Koordinatör karışık mesajı parçalara böler, `delegate` ile ilgili yavere gönderir, sonuçları tek cevapta birleştirir.
- Her yaverin sadece kendi araçları ve kısa kendi prompt'u vardır (`agents.yaml` → `tools`). Bu hem doğruluk hem token tasarrufu içindir.
- Bir kullanıcı mesajındaki tüm delegasyonlar **aynı `change_set_id`'yi** paylaşır; tek "Geri al" hepsini geri alır.
- Yaverler birbirini doğrudan çağırmaz; sadece koordinatör delege eder (döngü riski yok). Delegasyon derinliği = 1.
- Kullanıcı bir yaveri adıyla çağırırsa ("Friday, yarın ne var?") koordinatör doğrudan ona yönlendirir.
- Cevaplarda hangi yaverin ne yaptığı gösterilir (UI'de isim + renk etiketi).
- Brifing: her yaver kendi bölümünü üretir; `briefing_style` = `sections` ise kendi adıyla, `single_voice` ise koordinatör ağzından.
- Yeni yaver eklemek = `agents.yaml`'a kayıt + gerekirse yeni araç. Koordinatör prompt'u yaver listesini config'den otomatik alır.
- Maliyet: delegasyon ekstra bir LLM çağrısıdır. Tek alanlı basit mesajlarda (ör. sadece "EE211'e gitmedim") koordinatör ilgili aracı doğrudan çağırabilsin diye `fast_path` opsiyonu düşünülür (Faz 0 sonu değerlendirme).

## Ajan araçları (ilk set)
`get_day_plan(date)`, `get_week_plan(week_start)`, `add_recurring_block`, `update_recurring_block`, `cancel_block_on(date, block)`, `move_block_on`, `add_event`, `update_event`, `delete_event`, `log_attendance`, `get_attendance_summary`, `add_task`, `complete_task`, `add_followup`, `update_followup`, `remember`, `forget`, `search_materials` (Faz 3), `generate_study_sheet` (Faz 3), `undo(change_set_id)`.

Kurallar:
- Belirsiz eşleşmede (iki "linear" bloğu varsa) araç hata döner, ajan kullanıcıya sorar.
- Tarih ifadeleri `core/time_resolver.resolve()` ile çözülür (kısa ifade: "haftaya salı akşam", cümle değil). `ambiguous` dönerse ajan adaylardan birini seçmez, kullanıcıya adaylarla sorar ("20 Kasım Cuma mı, 27 Kasım Cuma mı?"); `unresolved` dönerse ifadeyi netleştirmesini ister. Saat de aynı ifadede verilebilir ("yarın 14'te", "cumartesi 11-13"); "yarın 9'da" gibi sabah/akşam belli olmayan saatte `am_or_pm` döner, ajan sorar.
- `resolve()`'un `direction` parametresi araca göre sabittir, modele bırakılmaz: **ekleme/planlama araçları** (`add_event`, `add_recurring_block`, `move_block_on`, `add_task`, `add_followup`…) `direction="future"`, **geçmiş kayıt araçları** (`log_attendance`, geçmiş bir günü sorgulayan/işaretleyen araçlar) `direction="past"`, salt okuma (`get_day_plan`) `"any"` kullanır. Böylece "bu salı" ekleme aracında gelecek salıya, "bu salı gitmedim"de geçen salıya çözülür.
- Toplu silme (>3 kayıt) için ajan önce onay ister.
- Araç çıktıları kısa JSON; asistan cevabında değişiklik özeti + geri al.

## LLM router
- Tier'lar: `fast` (Groq), `fallback` (Claude Haiku 5.5), `smart` (Claude Sonnet 5.5), `local` (Ollama). Model ID'leri `config/providers.yaml`'da, koda gömülmez.
- Failover: 429/5xx veya aynı turda 2 geçersiz tool call → bir üst tier.
- Budget guard: `CLAUDE_MONTHLY_BUDGET_USD`. %80'de `smart` → `fallback`, %100'de sadece `fast`/`local`.
- Prompt caching: system prompt + araç şemaları sabit tutulup cache'lenir. System prompt'a **bugünün tarihi, kullanıcıya özel veya istek başına değişen hiçbir şey yazılmaz** (prefix değişir, cache hiç tutmaz); takvim bağlamı ve tarih mesajlara eklenir. Araç listesi deterministik sırada verilir.
- Haiku 5.5'te prompt 100k token'ı geçmemeli (fiyat 5 katına çıkar); `max_prompt_tokens` olan tier'da router uyarı loglar ve en eski turları atar.
- Anthropic isteklerinde `temperature`/`top_p`/`top_k` gönderilmez (güncel API sürümünde 400). Opus/Sonnet 5.5 zorunlu `tool_choice` kabul etmez: `required` → `auto` + router doğrulaması (araç çağrılmazsa geçersiz sayılır).
- Her deneme (hatalı olanlar dahil) `llm_usage`'a yazılır; aylık özet `GET /api/usage/month`.
- Model ID'leri sağlayıcıda var mı: `python -m app.llm.check_models` (açılışta da arka planda çalışır, `LLM_CHECK_MODELS_ON_STARTUP`).

## Kod kuralları
- Kod, değişken, commit mesajı İngilizce; kullanıcıya dönen metinler Türkçe (i18n dosyası ile).
- Her araç için en az bir pytest (fake LLM ile).
- `ruff` + `mypy` backend'de, `eslint` + `tsc` frontend'de.
- Secret'lar sadece `.env`'de. `.env` asla commit edilmez.
- Küçük, odaklı commit'ler. Her faz sonunda ROADMAP.md güncellenir.
- Her TASKS.md maddesi bitince küçük bir commit at, **ASLA push yapma** (push'u Görkem yapar).
- Commit öncesi `git status` kontrol et; `.env`, `config/agents.yaml`, `config/providers.yaml`, `data/`, `uploads/` asla stage edilmez.
- ORM modellerinde (`app/db/`) `datetime` modülü her zaman `import datetime as dt` ile alınır, tipler `Mapped[dt.date]`, `Mapped[dt.datetime]`, `Mapped[dt.time]` diye yazılır. `from datetime import date` yasak: `date` adlı bir kolon (ör. `tasks.date`, `attendance.date`) class gövdesinde tipi gölgeler ve SQLAlchemy `MappedAnnotationError` verir.
- Config yükleyici önce `config/<ad>.yaml`, yoksa `config/<ad>.example.yaml` okur. Yeni config alanı eklenirse example dosyası da güncellenir.

## Çalıştırma
```bash
# Geliştirme: docker-compose.override.yml otomatik yüklenir (hot reload, Vite dev server)
docker compose up -d --build          # web: http://localhost:8080, api: http://localhost:8000/docs
docker compose exec api alembic upgrade head
docker compose exec api pytest

# Prod benzeri (nginx + build edilmiş web, override'sız)
docker compose -f docker-compose.yml up -d --build
```
`web/package.json` değişince node_modules volume'ünü yenile: `docker compose up -d --build -V web`.

## Canlı LLM testleri (gerçek para)
`@pytest.mark.live` testleri normal `pytest`'te çalışmaz. Elle: `docker compose exec api pytest -m live -v -s`. Harcama gerçek `llm_usage` tablosuna yazılır. Claude'u çağırmayan değişikliklerde gerekmez.

## Kontroller (commit öncesi)
```bash
# backend (yerelde uv ile ya da `docker compose exec api ...`)
cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest
# frontend
cd web && npm run check        # tsc + eslint
```
