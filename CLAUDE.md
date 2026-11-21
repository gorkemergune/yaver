# CLAUDE.md — Yaver

Claude Code bu dosyayı her oturumda okur. Proje kuralları ve mimari kararlar burada; ilerleme ROADMAP.md ve TASKS.md'de.

## Proje özeti
Yaver: chat + ses ile yönetilen, self-hosted kişisel AI asistan. Kullanıcı buton kullanmaz, doğal dille söyler; ajan tool-calling ile veritabanını günceller, değişikliği diff olarak gösterir, geri alınabilir.

Ana ekran izometrik bir **ofis** (`docs/OFFICE.md`, prototip `design/office-prototype/`): her ajan masası, defteri ve gelen kutusu olan bir çalışan. Ofis fazları O1–O5 `ROADMAP.md`'de.

Sahibi: Görkem (Yeditepe Bilgisayar Müh.). Geliştirme Windows 11 + Docker Desktop (WSL2) üzerinde. Kullanım: Windows, Mac, iPhone (PWA).

## Temel ilkeler
1. **Chat-first.** UI sadece okumak içindir; her yazma işlemi ajan araçlarından geçer. (UI'de olabilecek tek "buton": Geri al.)
2. **Her mutasyon geri alınabilir.** Tüm yazma araçları `change_log`'a before/after JSON yazar; her asistan cevabı bir `change_set_id` taşır.
3. **Tarih hesabını model yapmaz.** "Yarın", "gelecek perşembe" gibi ifadeler `core/time_resolver.py` ile kodda çözülür. Modele her istekte bugünün tarihi + önümüzdeki 14 günün listesi verilir; araçlar sadece ISO tarih kabul eder.
4. **Tek kullanıcı / instance.** Her kişi kendi Docker'ını çalıştırır. Kodda `user_id` yok; çoklu kullanıcı hedef değil.
5. **BYOK + provider-agnostic.** Tüm LLM çağrıları `llm/router.py` üzerinden. Doğrudan SDK çağrısı yasak.
6. **Kişisel veri repoda olmaz.** Seed dosyaları `data/` altında ve `.gitignore`'da. Örnekler `examples/` altında, uydurma verilerle.
7. **Zaman dilimi:** Anlar (instant) DB'de UTC `timestamptz` (`UTCDateTime` naive datetime'ı reddeder), hesap ve gösterim `APP_TIMEZONE` (varsayılan Europe/Istanbul). Haftalık tekrar eden saatler istisna: yerel duvar saati (`time`) olarak saklanır ki DST'de kaymasın.
8. **Ofiste hiçbir şey sahte değil.** Bir çalışanın `working` / `meeting` / `needs_user` durumu yalnızca backend'den (`office/state.py`) gelir ve gerçek bir LLM/araç çağrısına, delegasyona ya da bekleyen soruya karşılık gelir. Boşta görünüm (`break` → kahve, kanepe, koridor) frontend'in görsel çeşitlemesidir.

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
      api/                   # routers: chat, office, employees, schedule, briefing, materials, usage, push
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
      office/                # ofis motoru: çalışanlar, durum, olay akışı
        state.py             # Office.set_state: tek yazma noktası + SSE yayını, snapshot
        activity.py          # bir mesaj boyunca kim çalışıyor / toplantıda (koordinatör kullanır)
        sync.py              # agents.yaml -> employees
        budget.py            # çalışan başına günlük harcama
        shifts.py            # mesai işi sarmalayıcı: working -> break, bütçe aşılınca durur
        shift_jobs.py        # agents.yaml `shift_jobs` (web_scan, ads_report, social_reminders, followup_watch,
                             #   deadline_watch) -> "shift:<çalışan>:<iş>" zamanlayıcı işleri, sonuç deftere (LLM yok)
        rituals.py           # standup (brifingin içinde), gün sonu raporu, Pazar toplantısı (meeting bağlamı)
        board.py             # görev panosu: Bekliyor / Çalışıyor / Onay bekliyor / Bitti
        notebook.py          # write_note (çalışan yoksa yazmaz, durum notları günde bir), record_shift (gelen kutusu)
      integrations/          # web_search.py (Tavily/Brave, anahtar yoksa None), meta_ads.py (iskelet)
        labels.py            # araç adı -> "Takvime bakıyor" gibi görev metni
      jobs/                  # scheduler işleri
      rag/                   # ingest, chunk, embed, retrieve
    alembic/
    tests/
  web/                       # React PWA (mobile-first)
    src/api/                 # tipler, istemci, TanStack Query kancaları, SSE chat
    src/chat/                # sohbet: model.ts (akış olayları → görünüm, saf + testli), useChat, bileşenler
    src/office/              # ana ekran: scene/*.svg + layout.json (scripts/office_scene.py üretir, elle düzenlenmez),
                             #   geometry.ts (engeller, ızgara + A*, koltuklar, z-sırası), model.ts (SSE -> figür, saf + testli),
                             #   useOffice (snapshot + SSE, yeniden bağlanma), OfficeScene, EmployeePanel
    src/plan/, src/status/   # Takvim sekmesi (Bugün/Yarın/Hafta, salt okunur), devamsızlık + harcama
    src/i18n/tr.ts           # kullanıcıya görünen tüm metinler
  desktop/                   # Tauri (Faz 4)
  config/
    providers.example.yaml   # repoda; local kopya providers.yaml (gitignore)
    agents.example.yaml      # repoda; local kopya agents.yaml (gitignore) — çalışanlar: isim, rol, masa, alan, araçlar, bütçe
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
- `conversations`, `messages` — `messages.agent_id` hangi çalışanın konuştuğunu tutar; `conversations.pending_action` ekibin cevap beklediği soru (aşağıda); `conversations.employee_id` doğrudan bir çalışanla açılan sohbet (NULL = Yaver'le genel sohbet)
- `employees` — agents.yaml'dan senkron (id = agent id: `yaver`, `academic`…): ad, rol, renk, masa (`desk_row` office|back|front + `desk_col`), kişilik, araçlar, `daily_budget_usd`, `active` (yaml'dan çıkan çalışan silinmez, pasifleşir)
- `employee_state` — çalışan başına tek satır: activity (working|meeting|break|off), current_task, tool, meeting_with, needs_user + needs_user_reason (question|budget), since
- `employee_notes` — defter: kısa tarihli notlar (`add_note`, mesai işleri); change_log'a girer, geri alınır
- `employee_tasks` — gelen kutusu: source (user|yaver|shift), requested_by, instruction, status (running|done|failed), result, conversation_id, change_set_id
- `change_log` — change_set_id, entity, entity_id, op, before_json, after_json
- `llm_usage` — provider, model, tier, purpose, in/out/cached tokens, cost_usd
- `push_subscriptions` — Web Push
- `screen_sessions`, `app_limits` (Faz 4)

## Ofis çalışanları (çoklu ajan)
Sistem adı Yaver; ofiste isimleri kullanıcı tarafından verilen uzman **çalışanlar** (kodda hâlâ "agent"/"yaver") çalışır. Tanımlar `config/agents.yaml`'da, koda gömülmez; `employees` tablosu açılışta oradan senkronlanır. Örnek dosyadaki isimler `docs/OFFICE.md`'deki nötr kadro (Scholar, Chrono, Coach…); yerel dosya kendi isimlerini korur (id'ler aynı kalır).

```
Kullanıcı ──► Yaver (Chief of Staff, koordinatör, kendi odası)
                 ├─ delegate("academic",   "...")  → Scholar  (dersler, devamsızlık, sınav, materyal)
                 ├─ delegate("agenda",     "...")  → Chrono  (toplantı, iş, etkinlik, followup, görevler)
                 └─ delegate("discipline", "...")  → Coach   (spor, alışkanlık, ekran süresi)
   O3: Mentor (kariyer), Venture (startup), Metrics (reklam), Creator (içerik), Buddy (sosyal)
```

Ofis durumu (O1):
- `office/state.py` `Office.set_state(...)` tek yazma noktası: `employee_state`'i yazar, değişiklik varsa olayı SSE'ye yayınlar (aynı durum tekrar yayınlanmaz). Durum hataları sohbeti asla bozmaz (loglanır).
- Kod tarafı kimin ne yaptığını `office/activity.py` ile söyler: mesaj başında konuşan çalışan `working`; her araç çağrısından önce `working` + görev metni (`labels.py`); `delegate` başlarken koordinatör ve çalışan `meeting` (`meeting_with` birbirini gösterir), çalışan ilk aracını çağırınca toplantı biter (çalışan masasında `working`, koordinatör `working`); işi biten `break`. Aynı anda iki mesaj aynı çalışanı kullanıyorsa sonuncusu bitene kadar `break`'e düşmez.
- Açık soru bırakan çalışan (`pending_action.agent_id`) `needs_user` (reason `question`); cevaplanınca/soru düşünce kalkar. Günlük bütçesini (`daily_budget_usd`, yoksa `office.daily_budget_usd`; bugünkü `llm_usage` toplamı) aşan çalışan `needs_user` (reason `budget`) olur ve mesai işleri (`office/shifts.py`) çalışmaz; kullanıcının sohbeti çalışmaya devam eder.
- Her mesaj, konuşan ve delege edilen her çalışan için `employee_tasks`'a satır yazar (sohbetle aynı transaction: mesaj iptal olursa o da yok).
- `break` dışındaki boşta görünümler (`idle_walk`) frontend'de seçilir; backend `idle_walk` yazmaz. `off` O5'te.

Kurallar:
- Kullanıcı genel sohbette koordinatörle konuşur; ofiste bir çalışana tıklayıp doğrudan da yazabilir (`POST /api/employees/{id}/chat`, o çalışanın prompt'u ve araçları, aynı change_set/undo). Koordinatör karışık mesajı parçalara böler, `delegate` ile ilgili yavere gönderir, sonuçları tek cevapta birleştirir.
- Her yaverin sadece kendi araçları ve kısa kendi prompt'u vardır (`agents.yaml` → `tools`). Bu hem doğruluk hem token tasarrufu içindir.
- Bir kullanıcı mesajındaki tüm delegasyonlar **aynı `change_set_id`'yi** paylaşır; tek "Geri al" hepsini geri alır.
- Yaverler birbirini doğrudan çağırmaz; sadece koordinatör delege eder (döngü riski yok). Delegasyon derinliği = 1.
- Kullanıcı bir yaveri adıyla çağırırsa ("Scholar, yarın ne var?") koordinatör doğrudan ona yönlendirir.
- Cevaplarda hangi yaverin ne yaptığı gösterilir (UI'de isim + renk etiketi).
- Brifing: her yaver kendi bölümünü üretir; `briefing_style` = `sections` ise kendi adıyla, `single_voice` ise koordinatör ağzından.
- Yeni çalışan eklemek = `agents.yaml`'a kayıt (rol, masa, renk) + gerekirse yeni araç + ofiste boş masa (5 masa çifti: `back` 0-4, `front` 0-4). Koordinatör prompt'u çalışan listesini config'den otomatik alır.
- Defter: her çalışan `add_note` (kendi defterine kısa not, yalnızca kullanıcı isteyince ya da kalıcı bir gözlem için) ve `get_notes` (kendi ya da başkasının defteri) araçlarını otomatik alır; koordinatör `get_notes`'u alır ("Scholar'ın defterinde ne var?").
- Maliyet: delegasyon ekstra bir LLM çağrısıdır. Tek alanlı basit mesajlarda (ör. sadece "EE211'e gitmedim") koordinatör ilgili aracı doğrudan çağırabilsin diye `fast_path` opsiyonu düşünülür (Faz 0 sonu değerlendirme).

## Ajan araçları (ilk set)
`resolve_date(expression, direction)`, `get_day_plan(date)`, `get_week_plan(date)`, `add_recurring_block`, `update_recurring_block`, `cancel_block_on(date, block)`, `move_block_on`, `add_event`, `update_event`, `delete_event`, `log_attendance`, `get_attendance_summary`, `set_absence_limit`, `add_task`, `complete_task`, `add_followup`, `update_followup`, `remember`, `forget`, `search_materials` (Faz 3), `generate_study_sheet` (Faz 3), `undo(change_set_id)`.

Kurallar:
- Belirsiz eşleşmede (iki "linear" bloğu varsa) araç hata döner, ajan kullanıcıya sorar.
- Tarih ifadeleri `core/time_resolver.resolve()` ile çözülür (kısa ifade: "haftaya salı akşam", cümle değil). `ambiguous` dönerse ajan adaylardan birini seçmez, kullanıcıya adaylarla sorar ("20 Kasım Cuma mı, 27 Kasım Cuma mı?"); `unresolved` dönerse ifadeyi netleştirmesini ister. Saat de aynı ifadede verilebilir ("yarın 14'te", "cumartesi 11-13"); "yarın 9'da" gibi sabah/akşam belli olmayan saatte `am_or_pm` döner, ajan sorar.
- `resolve()`'un `direction` parametresi araca göre sabittir, modele bırakılmaz: **ekleme/planlama araçları** (`add_event`, `add_recurring_block`, `move_block_on`, `add_task`, `add_followup`…) `direction="future"`, **geçmiş kayıt araçları** (`log_attendance`, geçmiş bir günü sorgulayan/işaretleyen araçlar) `direction="past"`, salt okuma (`get_day_plan`) `"any"` kullanır. Böylece "bu salı" ekleme aracında gelecek salıya, "bu salı gitmedim"de geçen salıya çözülür.
- Toplu silme (>3 kayıt) için ajan önce onay ister.
- Araç çıktıları kısa JSON; asistan cevabında değişiklik özeti + geri al.
- Araçlar sadece ISO tarih (`YYYY-MM-DD`) ve `HH:MM` kabul eder; göreli ifadeler önce `resolve_date`'ten geçer. Her araç `app/agent/tools/` altında, Pydantic argüman modeli + handler; şema `json_schema()` ile üretilir. Saat alanlarında JSON-schema `format: time` kullanılmaz (Groq şemayı sunucuda RFC 3339'a göre doğrular, "09:00"ı reddeder) - `HH:MM` regex'i kullanılır.
- Belirsiz eşleşmede araç `candidates` döner; değiştirilecek bir şey yoksa ajan başka tarih/blok seçmez, sorar.
- Koordinatör `delegate` talimatına kullanıcının kelimelerini aynen yazar; tarih/saat eklemez.
- Her cevap `trace` (tüm araç çağrıları + argümanlar) taşır; prompt ayarı yaparken canlı senaryo çıktısına bakılır.
- HTTP: `POST /api/chat/stream` (SSE: turn/text/reset/tool/delegate/agent_reply, sonra done/error; bağlantı koparsa mesaj iptal ve rollback), `POST /api/chat` (akışsız), `POST /api/changes/{change_set_id}/undo` ("Geri al" butonu). Ofis: `GET /api/office/snapshot` (çalışanlar + durum + bugünkü harcama), `GET /api/office/stream` (SSE: önce `snapshot`, sonra `state` / `note` olayları, 15 sn'de bir `ping` olayı; tarayıcı 40 sn hiçbir olay görmezse bağlantıyı kapatıp yeniden bağlanır), `GET /api/employees/{id}/notes`, `/tasks`, `POST /api/employees/{id}/chat` ve `/chat/stream` (sohbetle aynı olaylar). Arayüz verisi: `/api/team`, `/api/plan/day`, `/api/plan/week`, `/api/attendance`, `/api/conversations/...`, `/api/usage/month`.
- Yaver etiket rengi `agents.yaml`'da (`color`); yoksa varsayılan palet.
- İlk kurulum: `conversations.mode = onboarding` olan konuşma kurulum asistanına (`prompts/onboarding.md.j2`) gider; `finish_onboarding` normal sohbete çevirir. Yapıştırılan ders programı `propose_schedule` ile öneriye (`schedule_proposals`) dönüşür, tablo gösterilir, ancak kullanıcı onaylayınca `apply_schedule` tek change_set ile yazar. Uzun metin `routing.purposes.schedule_parse` (smart) ile ayrıştırılır.
- Görseller: önce `POST /api/uploads` (yeniden kodlanır: EXIF/konum yok, HEIC→JPEG, uzun kenar `IMAGE_MAX_EDGE`), sonra mesaj `attachment_ids` ile. `agent/vision.py` görseli ekipten önce kodda okur; sadece Claude okur (vision olmayan sağlayıcıyı router atlar, Groq'a görsel gitmez). Ekip sonucu `[Görsel N ... -> öneri #N]` metni olarak görür; `messages.context`'te saklanır, geçmişle tekrar gider. Ders programı/etkinlik önerisi aynı mesajda uygulanamaz (`apply_proposal` ve `add_event`/`add_recurring_block` kodda engellenir), kullanıcı "evet" deyince uygulanır. Duyuru tarihleri modelden "yazıldığı gibi" alınır, kodda çözülür; gün adı tutmayan / tek gün olmayan tarih "belirsiz".
- PDF'ler: `POST /api/uploads` olduğu gibi saklar (`attachments.filename` atıf için). `agent/documents.py` metni kodda çıkarır (pypdf), `document_classify` (fast) ne olduğunu söyler; syllabus `syllabus_parse` (Sonnet) ile `öneri #N` (kind=syllabus) olur, "evet" ile `syllabus_weeks` + `course_materials` + `material_chunks` yazılır. Embedding yerel (fastembed, çok dilli MiniLM, 384 boyut, `MODEL_CACHE_DIR`); model ~128 token okuduğu için parçalar ~500 karakter. `search_materials` / `get_syllabus` akademik çalışanda (academic); cevapta kaynak "(dosya, s. N)".
- Bekleyen soru (`agent/pending.py`, `conversations.pending_action`): bir araç sonucu açık soru bırakırsa (`log_attendance` başka gün önerir, `candidates` döner, öneri tablosu gösterilir) her seçenek o işi bitiren araç çağrısı olarak saklanır. Kullanıcının kısa cevabı ("evet", "çarşamba", "2.si", "lab olan") kodda bir seçeneğe eşlenirse araç kodda çalışır, soran yaver sonucu araçsız tek turda bildirir. Eşlenmeyen kısa cevap soran yavere kendi sorusuyla birlikte gider; "hayır", soru ya da uzun mesaj normal akışa (koordinatör) gider. Her mesaj durumu yeniler; zamanlayıcı mesajı eskisini siler, 24 saatte düşer.
- Dil: son cevap İngilizce görünürse (`looks_english`) bir kez Türkçeye çevrilir (`language_fix`), akışta metin değiştirilir.
- Prompt boyutu: `PYTHONPATH=. uv run python scripts/measure_prompts.py` (ajan başına token). Prompt/araç eklerken ölç; her çağrıda giden metin Groq kotasını doğrudan yer.

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
`@pytest.mark.live` testleri normal `pytest`'te çalışmaz. Elle: `docker compose exec api pytest -m live -v -s`. Sağlayıcı testleri harcamayı gerçek `llm_usage` tablosuna yazar. Prompt veya araç değişikliğinden sonra uçtan uca senaryolar: `docker compose exec api pytest -m live -k scenarios -s` (test DB'sinde 5 mesaj; adım başına tier/maliyet, sonda failover oranı ve geçersiz araç çağrıları).

## Kontroller (commit öncesi)
```bash
# backend (yerelde uv ile ya da `docker compose exec api ...`)
cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest
# frontend
cd web && npm run check        # tsc + eslint + vitest
```
