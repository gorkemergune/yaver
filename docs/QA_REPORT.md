# QA raporu — uçtan uca testler ve backend incelemesi

Tarih: 2026-11-21 · Branch: `test/e2e-qa` (taban `2533307`) · Ortam: izole `yaver-e2e` stack'i
(web 8090, api 8001, db 5433; ana stack'e ve gerçek veritabanına dokunulmadı).

## Özet

**Testler.** `e2e/` altında Playwright (TypeScript): 17 LLM'siz test + 3 `@live` test.
- LLM'siz: **15 geçti, 2 kırmızı.** İkisi de gerçek bir hatayı yakalıyor (aşağıda Y3): sohbet
  akışına sunucu hiç cevap vermezse arayüz **sonsuza kadar "yazıyor…"** gösteriyor, akış
  `done`/`error` gelmeden kapanırsa da cevap **sessizce boş** kalıyor, hata görünmüyor.
- `@live`: **3/3 geçti**. Sohbet cevabı ~1-2 sn'de geliyor; sohbetten eklenen etkinlik "Geri al"
  ile siliniyor; bir çalışanla doğrudan sohbet çalışıyor. Toplam harcama **$0.0031** (Groq
  $0.0023 + Haiku failover $0.0008), sınır $0.30.
- Kapsanan akışlar: `/api/health/ready` (doğrudan + nginx), korumalı uçlar parolasız 401,
  giriş ekranı (yanlış/doğru parola, yeniden yüklemede oturum), ofis + çalışan listesi + SSE
  (`snapshot` ilk olay), çalışan paneli (defter, gelen kutusu, doğrudan sohbet), görev panosu
  (4 sütun, Bitti), Takvim (Bugün/Yarın/Hafta, etkinliğin doğru yerel güne düşmesi), Geri al
  (UI → API → DB, yeniden yüklemede "Geri alındı", ikinci geri alma 404), mock'lu hata yolları
  (500, bağlantı reddi, `llm_unavailable`, `internal`, ofis "Son cevap", doğrudan sohbet).

**İnceleme.** 3 yüksek, 5 orta, 6 düşük bulgu. Yüksek olanların üçü de e2e stack'inde
**elle doğrulandı**:
1. **Y1** — Her açık ofis sekmesi (SSE) bir DB bağlantısını *idle in transaction* olarak
   sonsuza kadar tutuyor. 15 sekme/bağlantıda havuz (5+10) doluyor ve **tüm API** 30 sn
   bekleyip 500/503 dönüyor (`/api/health/ready` dahil).
2. **Y2** — Giriş deneme sınırı `X-Forwarded-For` başlığı değiştirilerek atlanıyor (nginx
   üzerinden 12 yanlış deneme, hiç 429 yok) → parola kaba kuvvete açık.
3. **Y3** — Sohbet akışında ne istemci ne sunucu tarafında süre sınırı / kalp atışı var;
   "yazıyor…" sonsuz kalabiliyor (yukarıdaki iki kırmızı test).

Ayrıca: `agents.yaml`'daki tek bir YAML hatası ya da `.env`'de `BRIEFING_TIME=9:00` gibi bir
değer API'nin **hiç açılmamasına** yol açıyor (O1, doğrulandı); takvim abonelik token'ı api ve
nginx erişim loglarına yazılıyor (O3, doğrulandı); `shift_jobs.py`'de bugünkü `github` hatasıyla
aynı desende bir isim gölgelemesi var (O2, şu an çalışıyor ama kırılgan).

Kod değiştirilmedi (kural gereği); düzeltmeler öneri olarak yazıldı.

---

## Önem dereceleri

| Derece | Anlamı |
|---|---|
| **Yüksek** | Normal kullanımda veri/erişim kaybı, güvenlik açığı ya da uygulamanın kilitlenmesi |
| **Orta** | Belirli bir yanlış yapılandırma / bağımlılık değişikliğinde çökme, sızıntı, kırılgan kod |
| **Düşük** | Kenar durum, performans, temizlik |

Her bulguda **Doğrulama** satırı nasıl teyit edildiğini söyler: *e2e'de doğrulandı* (izole
stack'te çalıştırıldı), *testle doğrulandı* (Playwright testi kırmızı), *okuma* (yalnız kod
incelemesi).

---

## Yüksek

### Y1 — Kimlik doğrulama oturumu akış (SSE) boyunca DB bağlantısını tutuyor; havuz dolunca tüm API kilitleniyor

- **Yer:** `backend/app/api/auth.py:52-72` (`require_auth`, `Depends(get_session)`),
  `backend/app/main.py:92-108` (tüm korumalı router'lara bağımlılık),
  `backend/app/db/session.py:32-35`, akışlar: `backend/app/api/office.py:63-67`,
  `backend/app/api/chat.py:140-165`, `backend/app/api/employees.py:186` (`/chat/stream`).
- **Neden sorun:** `require_auth` yield'li `get_session` bağımlılığını kullanıyor ve
  `check_session` bir `SELECT` çalıştırıyor (autobegin → bağlantı havuzdan alınır). FastAPI
  0.165'te yield'li bağımlılıkların çıkışı **cevap gönderildikten sonra** çalışır; uzun süren
  bir `StreamingResponse`'ta bu "akış bitince" demek. `/api/office/stream` sonsuz bir akış:
  her açık ofis sekmesi / PWA / masaüstü uygulaması bir bağlantıyı *idle in transaction*
  olarak tutar. Tarayıcının 40 sn kuralıyla yeniden bağlanması sırasında eski akış ≤15 sn
  (sonraki ping) daha yaşar. Her sohbet mesajı da 2 bağlantı tutar (auth + mesaj oturumu).
  Havuz varsayılanı 5 + 10 overflow; dolunca her istek `pool_timeout` (30 sn) bekleyip hata
  verir. Ayrıca açık transaction `auth_sessions` / `device_keys` üzerinde AccessShareLock
  tutar: bu tablolara dokunan bir `alembic upgrade` sekmeler açıkken bekler (okuma; denenmedi).
- **Doğrulama (e2e'de doğrulandı):** 6 akış → `pg_stat_activity`'de 6 *idle in transaction*;
  akışlar kapanınca 0. 16 akış → 15 *idle in transaction*, `GET /api/office/board` **500 /
  30.0 sn**, `GET /api/health/ready` **503 / 30.0 sn**; akışlar kapanınca tekrar 200 / 18 ms.
- **Öneri:** Kimlik kontrolü kısa ömürlü kendi oturumunu açıp kapatsın, istek oturumunu
  paylaşmasın:
  ```python
  async def require_auth(request: Request, settings: Settings = Depends(get_settings)) -> None:
      if not auth_enabled(settings):
          return
      async with get_sessionmaker()() as session:   # kontrol bitince bağlantı havuza döner
          ...
  ```
  (Alternatif: `Depends(get_session, scope="function")` — çıkış cevaptan önce çalışır.) Akış
  uçları (`office/stream`, `chat/stream`) başka bir istek-oturumu bağımlılığı almamalı.
  Ek olarak `office_events` döngüsünde `await request.is_disconnected()` kontrolü eski
  akışları ping'i beklemeden kapatır. Bir regresyon testi: N > havuz boyutu kadar akış açıp
  `/api/health/ready`'nin hâlâ 200 döndüğünü kontrol eden pytest.

### Y2 — Giriş deneme sınırı `X-Forwarded-For` ile atlanıyor (parola kaba kuvvete açık)

- **Yer:** `backend/app/api/auth.py:40-44` (`_client_key`: başlığın **ilk** değeri),
  `web/nginx.conf:20` (`proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;`),
  `backend/app/services/auth.py:118-148` (`LoginLimiter`, bellekte sınırsız `dict`).
- **Neden sorun:** `$proxy_add_x_forwarded_for` istemcinin gönderdiği başlığa nginx'in gördüğü
  adresi **ekler**; ilk değer istemcinin uydurduğu adrestir. Her denemede farklı bir
  `X-Forwarded-For` göndermek 5 deneme / 10 dk sınırını tamamen kaldırır. Tek kullanıcılı,
  Tailscale ile telefona açılan bir uygulamada parola tek savunma hattı. Yan etki: her sahte
  adres `LoginLimiter.failures`'a yeni bir anahtar ekler; bellek sınırsız büyür.
- **Doğrulama (e2e'de doğrulandı):** nginx (8090) üzerinden aynı istemci → 5×401, sonra 429.
  Her denemede farklı `X-Forwarded-For: 10.9.8.N` → **12×401, hiç 429 yok**.
- **Öneri:** nginx'te başlığı üzerine yaz: `proxy_set_header X-Forwarded-For $remote_addr;`
  (ya da uvicorn `--proxy-headers --forwarded-allow-ips=<nginx ağı>` ile `request.client.host`
  kullan, başlığı uygulamada hiç okuma). Tek kullanıcılı olduğu için ayrıca **global** bir sınır
  ekle (ör. tüm istemciler toplamı 20 yanlış / 10 dk) ve `failures` sözlüğünü boyutla sınırla.
  `_https` (`auth.py:47-49`) de aynı şekilde istemci başlığına güveniyor (bkz. D6).

### Y3 — Sohbet akışında süre sınırı yok: sonsuz "yazıyor…" ve sessiz boş cevap

- **Yer (istemci):** `web/src/api/chat.ts:13-24` ve `:36-45` (`fetch` + `readEvents`, zaman
  aşımı / terminal olay kontrolü yok), `web/src/chat/useChat.ts:110-141`
  (`finally` yalnız `streaming:false` yapıyor, hata koymuyor), aynısı
  `web/src/office/useEmployeeChat.ts`.
  **Yer (sunucu):** `backend/app/api/chat.py:110-137` (`stream_reply`: kalp atışı yok, toplam
  süre sınırı yok).
- **Neden sorun:**
  1. Sunucu isteği kabul edip hiç byte göndermezse (asılı LLM çağrısı, Y1'deki gibi havuz
     beklemesi, bir proxy'nin tamponlaması) `fetch` sonsuza kadar bekler; arayüz "yazıyor…"da
     kalır, composer kilitli kalır. Bugün yaşanan belirti bu.
  2. Akış `done` ya da `error` gelmeden kapanırsa (api yeniden başladı, uvicorn `--reload`,
     nginx `proxy_read_timeout 300s`, ağ kesildi) `finally` sadece `streaming:false` yapar;
     metin boşsa kullanıcı **hiçbir şey** görmez — ne cevap ne hata.
  3. Sunucuda bir mesajın toplam süresi sınırsız: sağlayıcı başına 60 sn (okumalar arası)
     zaman aşımı × failover zinciri × en fazla 6 araç adımı × delegasyonlar dakikaları bulabilir;
     bu sürede istemciye hiçbir olay gitmeyebilir ve nginx 300 sn'de bağlantıyı keser (→ madde 2).
- **Doğrulama (testle doğrulandı):** `e2e/tests/chat-errors.spec.ts`
  - "a stream that never answers ends with an error, not endless 'yazıyor…'" — 80 sn sonra hâlâ
    "yazıyor…", hata yok → **kırmızı**.
  - "a stream that closes without done/error does not leave a silent empty answer" — boş balon,
    hata yok → **kırmızı**.
  - Karşılaştırma: HTTP 500, bağlantı reddi, `error` olayı (`llm_unavailable`, `internal`) doğru
    hata metnini gösteriyor (yeşil).
- **Öneri:**
  - İstemci: `streamChat` bir terminal olay (`done`/`error`) görmeden biterse
    `onEvent({type:"error", code:"network"})` (ya da yeni bir `interrupted` kodu) çağırsın.
    Bir hareketsizlik bekçisi ekle: X sn (ör. 45) hiçbir olay gelmezse `AbortController.abort()`
    + `error: "timeout"` ("Cevap gecikti, tekrar dene."). Aynısı `streamEmployeeChat` için.
  - Sunucu: `stream_reply`'da kuyruğu `asyncio.wait_for(queue.get(), 15)` ile oku, zaman
    aşımında `{"type":"ping"}` (ya da SSE yorumu `: ping`) gönder; `answer(emit)`'i
    `asyncio.timeout(CHAT_DEADLINE_SECONDS)` (ör. 150 sn, nginx'in 300 sn'sinin altında) ile
    sar ve süre dolunca `{"type":"error","code":"timeout"}` yayınla (mesaj rollback olur).
  - İki kırmızı test bu düzeltmelerden sonra yeşile dönmeli.

---

## Orta

### O1 — Tek bir yapılandırma hatası API'nin hiç açılmamasına yol açıyor

- **Yer:** `backend/app/main.py:58` (`get_office()` lifespan'de senkron çağrılıyor) →
  `backend/app/office/state.py:405-411` → `load_team_config()` (YAML/Pydantic hatası
  yakalanmıyor). `backend/app/main.py:112` (`app = create_app()` import anında
  `get_settings()`), `backend/app/config.py:117-133` (`_hhmm`, saat aralığı doğrulayıcıları),
  `:99-105` (`APP_TIMEZONE`).
- **Neden sorun:** `agents.yaml`'da kapanmamış bir tırnak, `.env`'de `BRIEFING_TIME=9:00`
  (`dt.time.fromisoformat("9:00")` 3.12'de hata), `APP_TIMEZONE=Istanbul` ya da
  `CLAUDE_MONTHLY_BUDGET_USD=4$` gibi tek bir değer sürecin açılmasını engelliyor; giriş, takvim
  abonelikleri, sağlık kontrolü dahil her şey düşüyor ve `restart: unless-stopped` ile sonsuz
  yeniden başlama döngüsüne giriyor. Ofis zaten "DB yoksa ready=False" ile kendini
  koruyor; config hatası bu korumanın dışında kalıyor. (Not: `main`'deki `e16b843` bu kuralı
  CLAUDE.md'ye yazmış ve bir smoke testi eklemiş; bu branch'teki kod hâlâ çöküyor.)
- **Doğrulama (e2e'de doğrulandı):** e2e api imajı ile
  `docker run -e BRIEFING_TIME=9:00 … python -c "import app.main"` →
  `Value error, expected HH:MM, got '9:00'`. Bozuk `agents.yaml` mount edilince
  `yaml.scanner.ScannerError … ERROR: Application startup failed. Exiting.`
- **Öneri:** `get_office()` / `load_team_config()` çağrısını lifespan'de `try/except` içine al;
  hata varsa logla ve ofisi `ready=False` ile başlat (sohbet, giriş ve takvim çalışmaya devam
  etsin; `/api/office/snapshot` hatayı göstersin). Settings'te `H:MM`'yi de kabul et ve
  geçersiz değerlerde varsayılana düşüp uyar (ör. `field_validator(mode="wrap")`); yalnızca
  `DATABASE_URL` gibi gerçekten zorunlu alanlar süreci durdursun.

### O2 — `ShiftContext.search` alanı `search` modülünü gölgeliyor (bugünkü `github` hatasıyla aynı desen)

- **Yer:** `backend/app/office/shift_jobs.py:24`
  (`from app.integrations import web_search as search`) ve `:74`
  (`search: search.WebSearch | None` — `@dataclass(frozen=True, slots=True)` içinde).
- **Neden sorun:** Python 3.12'de çalışıyor, çünkü anotasyon değer bağlanmadan önce sınıf
  gövdesinde değerlendiriliyor ve alanın varsayılanı yok. Ama: (a) `search: ... = None`
  varsayılanı eklenirse ya da alandan sonra `search.X` kullanan bir anotasyon / varsayılan
  gelirse sınıf tanımı `AttributeError` ile **import anında** çöker → `office.board` →
  `api.office` → `app.main` zinciriyle API açılmaz; (b) Python 3.14'ün ertelenmiş
  anotasyonlarında (PEP 649/749) anotasyon geç değerlendirildiği için `get_type_hints`
  benzeri bir introspeksiyon `search`'ü sınıf ad alanında (slot tanımlayıcısı) bulup kırılabilir
  (denenmedi); (c) aynı dosyada
  fonksiyonlarda `ctx.search` ve `search.PENDING_NOTE` yan yana okunuyor, karışıklığa açık.
- **Doğrulama (okuma + AST taraması):** `e2e/tools/shadow_scan.py` tüm `backend/app`'i taradı;
  sınıf alanı → sonraki anotasyonda kullanılan import deseninde tek eşleşme bu.
  (`api/health.py:16,22`'deki `status` alanları `fastapi.status` importunu gölgeliyor ama sınıf
  içinde kullanılmadığı için zararsız.)
- **Öneri:** Import'u `from app.integrations import web_search` olarak bırakıp
  `web_search.WebSearch` / `web_search.PENDING_NOTE` kullan ya da alanı `searcher` yap.
  `shadow_scan.py`'yi (veya ruff `A` kuralları + `main`'deki smoke testi) CI'a ekle.

### O3 — Takvim abonelik token'ı erişim loglarına yazılıyor

- **Yer:** `backend/app/api/calendar.py:36-43` (`GET /api/calendar.ics?token=...`),
  uvicorn erişim logu, `web/nginx.conf` (`location /api/` için erişim logu açık).
- **Neden sorun:** Token takvim akışının tek anahtarı (girişsiz); sorgu dizesi uvicorn'un ve
  nginx'in erişim loglarına tam olarak düşüyor. `docker compose logs` çıktısı paylaşıldığında
  (hata ayıklarken sık yapılır) ders programı, sınavlar, konumlar dahil takvim herkese açılır.
- **Doğrulama (e2e'de doğrulandı):** `GET /api/calendar.ics?token=QA-SECRET-TOKEN-PROBE` →
  token hem `yaver-e2e-api-1` hem `yaver-e2e-web-1` loglarında bulundu.
- **Öneri:** nginx'te `location = /api/calendar.ics { access_log off; proxy_pass ...; }` (ya da
  `$uri` ile argümansız bir `log_format`); uvicorn tarafında `uvicorn.access` logger'ına
  `token=` değerini maskeleyen bir `logging.Filter`. iOS takvimi başlık gönderemediği için token
  URL'de kalmak zorunda; çözüm loglarda.

### O4 — `httpx2` doğrudan import ediliyor ama bağımlılık olarak bildirilmemiş

- **Yer:** `backend/app/integrations/web_search.py:10` (`import httpx2`),
  `backend/pyproject.toml` (`dependencies` listesinde yok; `uv.lock`'ta yalnız `anthropic 2.10`
  bağımlılığı olarak geliyor).
- **Neden sorun:** `anthropic` bir sürümde HTTP istemcisini değiştirir/bırakırsa `uv lock
  --upgrade` sonrası `import httpx2` başarısız olur; modül `shift_jobs` → `office.board` →
  `api.office` → `app.main` zincirinde olduğundan **API açılmaz** (açılışta çökebilecek import).
- **Doğrulama (okuma):** `uv.lock:97-108`.
- **Öneri:** `pyproject.toml`'a `"httpx2>=..."` ekle (ya da `openai`'nin kullandığı `httpx`'i
  açıkça bildirip onu kullan). Smoke test (`main`'deki `test_smoke.py`) her modülün import
  edildiğini kontrol ettiği için bunu yakalar; ama ancak bağımlılık zaten kaybolduktan sonra.

### O5 — Doğrudan sohbet başka bir konuşmanın id'siyle o konuşmaya yazabiliyor

- **Yer:** `backend/app/agent/coordinator.py:697-700` (`_conversation`).
- **Neden sorun:** Var olan bir `conversation_id` gelirse `employee_id`/`mode` kontrolü
  yapılmadan o konuşma döndürülüyor: Scholar'ın panelinden ana sohbetin (ya da Chrono'nun)
  id'siyle yazılırsa mesaj ve bekleyen soru (`pending_action`) yanlış konuşmaya karışır; ana
  sohbetin geçmişi o çalışanın prompt'uyla yeniden oynatılır. Bilinmeyen bir id ise sessizce
  yeni konuşma açıyor (localStorage'daki eski id, DB sıfırlandıktan sonra). İstemci şu an
  ayrı anahtarlar tuttuğu için olasılık düşük, ama sunucu bunu garanti etmiyor.
- **Doğrulama (e2e'de doğrulandı, ikinci kısım):** `conversation_id: 987654` ile gönderilen
  mesaj hatasız yeni konuşma `1`'e yazıldı.
- **Öneri:** `existing.employee_id != employee_id` ise 409/422 dön (ya da yeni konuşma aç);
  bilinmeyen id için 404 dönüp istemcinin `storeConversation(null)` yapmasını sağla.

---

## Düşük

### D1 — Hata yolunda `rollback` başarısız olursa çalışan ofiste "working"de takılı kalıyor
- **Yer:** `backend/app/agent/coordinator.py:241-244`.
- **Neden:** `await session.rollback()` istisna atarsa (bağlantı kopmuş) `activity.close()`
  çalışmaz; `_busy` sayacı düşmez, çalışan bir sonraki yeniden başlatmaya kadar `working`
  görünür (ilke 8: "ofiste hiçbir şey sahte değil"). Orijinal hata da maskelenir.
- **Öneri:** `try: await session.rollback() finally: await activity.close()`.
- **Doğrulama:** okuma.

### D2 — Otomatik yedek sıkıştırmayı event loop'ta yapıyor; stderr geç okunuyor
- **Yer:** `backend/app/services/backup.py:89-92`.
- **Neden:** `gzip.open(...).write` CPU işini event loop'ta yapıyor: açılıştaki yedek büyük bir
  DB'de sürerken tüm istekler (sohbet dahil) duraklar. `stderr` ancak `stdout` bitince
  okunuyor; pg_dump 64 KB'tan fazla uyarı yazarsa iki süreç birbirini bekler (deadlock).
- **Öneri:** `pg_dump -Fp | gzip`'i `-Z`/`--compress` ile pg_dump'a bırak ya da yazmayı
  `asyncio.to_thread`'e al; stderr'i `asyncio.gather` ile eşzamanlı oku.
- **Doğrulama:** okuma.

### D3 — Ek dosyalar event loop'ta senkron okunuyor
- **Yer:** `backend/app/agent/coordinator.py:726-727` (`read_bytes()`), 6 × 20 MB'a kadar.
- **Öneri:** `await asyncio.to_thread(path.read_bytes)` (materials.py zaten böyle yapıyor).
- **Doğrulama:** okuma.

### D4 — Çoklu yüklemede sonraki dosya reddedilirse öncekiler diskte sahipsiz kalıyor
- **Yer:** `backend/app/api/uploads.py:72-131`.
- **Neden:** Her dosya diske hemen yazılıyor; sonraki bir dosya 413/415 ile reddedilince
  transaction commit edilmiyor ama dosyalar `UPLOAD_DIR`'de kalıyor.
- **Öneri:** Önce hepsini doğrula, sonra yaz; ya da hata yolunda yazılanları sil.
- **Doğrulama:** okuma.

### D5 — `Secure` çerez kararı istemcinin `X-Forwarded-Proto` başlığından
- **Yer:** `backend/app/api/auth.py:47-49`, `web/nginx.conf:3-6` (istemci başlığı doluysa aynen
  geçiyor).
- **Neden:** HTTPS'te istemci `X-Forwarded-Proto: http` gönderirse çerez `Secure` olmadan
  verilir. Pratik etkisi düşük (Tailscale serve başlığı kendisi koyar), ama Y2 ile aynı kök:
  uygulama proxy başlıklarına koşulsuz güveniyor.
- **Öneri:** Başlığı yalnız güvenilen proxy'den kabul et (uvicorn `--forwarded-allow-ips`).
- **Doğrulama:** okuma.

### D6 — DST'li bir `APP_TIMEZONE`'da var olmayan / iki kez yaşanan saatler (potansiyel)
- **Yer:** `backend/app/services/schedule.py:160-162` ve benzeri
  `dt.datetime.combine(..., tzinfo=ZoneInfo)` kullanımları.
- **Neden:** `Europe/Istanbul`'da DST yok (2016'dan beri +03), bu yüzden bugün etkisiz. Ama
  `APP_TIMEZONE` yapılandırılabilir; ör. `Europe/Berlin`'de ilkbahar geçişindeki 02:30 bloğu
  var olmayan bir saat olur (`fold=0` ile 1 saat kayar) ve aynı `tzinfo`'lu iki aware
  datetime'ın farkı duvar saatiyle hesaplanır. Zaman dilimi disiplini genel olarak iyi:
  tüm `now()` çağrıları `dt.UTC` ile, DB oturumu UTC, `UTCDateTime` naive değeri reddediyor,
  gün sınırları `settings.tz` ile; naive `datetime.now()` / `date.today()` / `utcnow` yok.
- **Öneri:** Süre hesaplarını UTC'ye çevirip yap; DST'li bir dilimle (ör. Europe/Berlin, Mart'ın
  son pazarı) birkaç time_resolver/schedule testi ekle.
- **Doğrulama:** okuma (denenmedi).

---

## İncelenen ve sorun bulunmayan alanlar

- **Auth kapsamı:** `health`, `auth` ve token kontrollü `calendar.feed_router` dışındaki tüm
  router'lar `require_auth` ile korunuyor (`main.py:92-108`). e2e testi 10 uçta parolasız
  401'i doğruluyor. Cihaz anahtarları hash'li, iptal kontrolü var; parola ve takvim token'ı
  `hmac.compare_digest` ile karşılaştırılıyor. `/docs` ve `/openapi.json` api portunda açık
  ama nginx yalnız `/api/` ve `/health`'i proxy'liyor, dev portu `127.0.0.1`'e bağlı.
- **Secret loglama:** API anahtarları `SecretStr`; log çağrılarında anahtar/parola yok;
  pg_dump parolası argv yerine `PGPASSWORD` ortam değişkeniyle. Tek sızıntı O3.
- **Yükleme dosya yolu:** `resolve_stored` `UPLOAD_DIR` dışını reddediyor; görseller yeniden
  kodlanıyor (EXIF yok).
- **Kapanış:** Açık bir ofis SSE akışı uvicorn'un kapanmasını geciktirmiyor (`docker stop`
  akışlı/akışsız 2 sn). `uvicorn --reload` altında uygulama import hatası verirse istekler
  asılı kalmıyor, bağlantı hemen kapanıyor (denendi) — yani bugünkü "sonsuz yazıyor"un sebebi
  bu değil; istemci tarafındaki süresizlik (Y3) her durumda sorunu büyütüyor.

---

## E2E altyapısı

| Dosya | Ne yapar |
|---|---|
| `e2e/docker-compose.e2e.yml` | `yaver-e2e` projesi: db 5433, api 8001, web 8090 (prod imajları), kendi volume'leri, `APP_PASSWORD=e2e-test-password`, zamanlayıcı/yedek/model kontrolü kapalı, `CLAUDE_MONTHLY_BUDGET_USD=0.30`, `DEEP_MONTHLY_BUDGET_USD=0`. `.env`'den yalnız 3 LLM anahtarı okunur. |
| `e2e/stack.sh`, `e2e/stack.ps1` | `up` (build, başlat, `alembic upgrade head`, api yeniden başlat, hazır olmayı bekle), `down`, `reset`, `logs` |
| `e2e/global-setup.ts` | hazır olmayı bekler, bir kez giriş yapar, çerezi `.auth/state.json`'a yazar |
| `e2e/helpers/seed.ts` | LLM'siz senaryolar için e2e DB'sine doğrudan veri: change set'li cevap (Geri al), defter notu, gelen kutusu işi, etkinlik |
| `e2e/tests/auth.spec.ts` | sağlık, 401'ler, giriş ekranı |
| `e2e/tests/office.spec.ts` | ofis, çalışan listesi, SSE, çalışan paneli, görev panosu |
| `e2e/tests/calendar-undo.spec.ts` | Takvim sekmeleri, Geri al |
| `e2e/tests/chat-errors.spec.ts` | mock'lu hata yolları (sonsuz "yazıyor…" testi dahil) |
| `e2e/tests/live.spec.ts` | `@live`: gerçek sohbet, ekle + Geri al, doğrudan sohbet; bütçe bekçisi |
| `e2e/tools/shadow_scan.py` | isim gölgeleme AST taraması |

Çalıştırma: `e2e/README.md`. Son koşu: LLM'siz 15/17 (2 bilinçli kırmızı, Y3), `@live` 3/3,
harcama $0.0031. İzole stack iş bitince `docker compose -p yaver-e2e down` ile durduruldu
(volume'ler duruyor; `./e2e/stack.sh reset` siler).
