# Canlı / geliştirme ayrımı ve deploy — rapor

Tarih: 2026-11-21 · Branch: `feat/live-deploy` (önce `main`'e fast-forward edildi, taban `0a2555b`)
· Push yok · **Geçiş yapılmadı**, yalnızca hazırlandı.

## Özet

| # | Madde | Commit | Durum |
|---|---|---|---|
| 2 | Y2 nginx: `X-Forwarded-For $remote_addr` (üzerine yazılır) | `14c7f75` | Doğrulandı |
| 3 | O3 nginx: erişim logunda `token=***` | `845a4fa` | Doğrulandı (uvicorn tarafı açık, aşağıda) |
| 4 | `docs/tr/KULLANIM.md`: yeni kadro ve kullanım | `fcfbec2` | Yazıldı, araç listeleriyle karşılaştırıldı |
| 1 | Canlı/geliştirme ayrımı, `deploy-live.ps1`, `rollback-live.ps1`, rehber | `ae0654c` | Sandbox'ta uçtan uca doğrulandı |

Hiçbir zaman dokunulmadı: ana stack (`yaver-*`, 8080/8000/5432), gerçek veritabanı
(`yaver_pgdata`), `backend/`, `web/src/`.

---

## 1. Canlı / geliştirme

**Yeni düzen:**

| | Canlı `yaver-live` | Geliştirme `yaver-dev` |
|---|---|---|
| Dosya | `docker-compose.live.yml` | `docker-compose.yml` + `docker-compose.override.yml` |
| Kod | Build edilmiş imaj (`yaver-live-api:<etiket>`), reload yok | Bind mount + hot reload |
| DB | `yaver_pgdata`, **external** volume (`down -v` silemez) | `yaver-dev_pgdata` |
| Portlar | web 8080 (bugünkü gibi) | 127.0.0.1: web 8180, api 8100, db 5532 |
| Uploads / yedekler | `./uploads`, `./backups` | Kendi volume'leri |
| Zamanlayıcı | `.env`'deki gibi (açık) | Kapalı (`DEV_SCHEDULER_ENABLED`) |
| Güncelleme | Yalnız `scripts/deploy-live.ps1` | `docker compose up -d` |

Alışkanlıkla yazılan `docker compose up` artık geliştirme stack'ini açar ve gerçek veritabanına
erişemez. Canlı için `scripts/live.ps1 <compose komutu>` var (doğru proje, dosya ve imaj etiketi;
`down -v`'yi reddeder).

**`scripts/deploy-live.ps1` akışı:**
1. Ön kontrol: Docker, `.env`, kilit dosyası, DB volume'ünün varlığı. Bu volume'ü başka bir
   container kullanıyorsa (ör. eski `yaver-db-1`) çalışmayı reddeder; iki PostgreSQL aynı veriyi
   açarsa bozulur.
2. `git archive` ile commit (varsayılan `main`) `%USERPROFILE%\yaver-releases\yaver-live\releases\<etiket>`
   klasörüne çıkarılır. Commit'lenmemiş hiçbir şey canlıya gitmez.
3. Build: prod api, prod web ve pytest için dev api.
4. Geçici `yaver-e2e-release` stack'i (8092/8003/5435, boş DB) kurulur. Sırayla **pytest** (canlı LLM
   testleri hariç), **smoke** (giriş dahil) ve **Playwright e2e** (LLM'siz) çalışır.
5. Canlı DB yedeklenir (`backups\predeploy\`, son 5 tutulur). Bu yedeğin kopyasında **migration
   provası** yapılır.
6. Geçiş: eski api/web durur → `alembic upgrade head` → yeni imajlar başlar.
7. Sağlık kontrolü: container *healthy* olmalı, `/api/health/ready` cevap vermeli, 8080 üzerinden
   girişli smoke geçmeli.
8. Hata durumunda:
   - 1-5'te biterse canlıya hiç dokunulmaz.
   - 6-7'de biterse önceki imajlara dönülür; şema değiştiyse önce yedek geri yüklenir.
   - Neden kırmızıyla yazılır; tam log `logs\deploy-<etiket>.log`'a, özet `state.json`'a düşer.
9. Son 3 başarılı sürümün imajları ve klasörleri tutulur.

Ayrıca:
- `rollback-live.ps1`: `-List`, varsayılan olarak önceki sürüm, `-To <etiket>`, `-RestoreBackup`
  ("evet" onayı ister ya da `-Yes`).
- `smoke.ps1`: canlı/geliştirme/her proje için çalışır, container'ları etiketlerden bulur,
  `APP_PASSWORD` ile giriş yapar. Önceden parola açıkken `/api/team`'de 401 alıyordu.
- `backup.ps1` / `backup.sh`: varsayılan olarak canlıyı yedekler; `-Stack dev` / `STACK=dev`
  geliştirmeyi `backups\dev`'e yedekler.
- `docs/tr/canli-ve-gelistirme.md`: adım adım geçiş, günlük kullanım, sorunlar.
  `KURULUM_WINDOWS.md`, `yedekleme.md`, `venture-github.md`, `KULLANIM.md` ve `.env.example`
  yeni komutlara/portlara göre güncellendi.

**Yolda bulunan ve düzeltilen gerçek bir sorun:** prod api uid 1000 ile çalışıyor ama named
volume'ler root'a ait başlıyor. e2e stack'inde `/uploads` ve `/models` **yazılamıyordu**
(`touch: Permission denied`); embedding modelinin indirilmesi ve e2e'de yükleme bundan
etkilenirdi. Canlı, geliştirme ve e2e compose dosyalarına tek seferlik bir `volume-perms`
servisi eklendi (`chown -R 1000:1000`, zaten çekili olan pgvector imajıyla). Sandbox'ta
doğrulandı: `models-writable`, `uploads-writable`.

### Doğrulama (sandbox "canlı")

Betikler gerçek canlıya hiç dokunmadan, ayrı bir kopyada (`yaver-sandbox`, :8095, kendi DB
volume'ü, zamanlayıcı kapalı) **gerçek betiklerle** denendi. Deploy edilen, çalışma ağacının
geçici bir commit nesnesiydi (`refs/sandbox/wip`; branch'e ve index'e dokunulmadı, sonra silindi).

| Senaryo | Sonuç |
|---|---|
| İlk deploy (boş DB) | ✅ 136 sn: pytest **1043 passed** (24 sn), smoke, Playwright **19/19**, yedek, prova, geçiş, sağlık |
| İkinci deploy (`-SkipE2E`) | ✅ 69 sn, veri işareti korundu, `previous` kaydedildi |
| `rollback-live.ps1` | ✅ 11 sn, veri korundu |
| Şemayı değiştiren deploy + sağlık hatası (`-SimulateFailure health`) | ✅ Yedek geri yüklendi (revizyon `d37bc5b1bb0c` → `ad7c26be72b1`, `ad_reports` tablosu yine yok, iki veri işareti yerinde), önceki sürüme dönüldü |
| Testler başarısız (`-SimulateFailure tests`) | ✅ Canlı api yeniden başlamadı; başarısız sürümün imajları, klasörü ve test stack'i temizlendi |
| Başarılı deploy + `rollback -RestoreBackup -Yes` | ✅ Deploy'dan sonra yazılan işaret gitti, öncekiler kaldı, revizyon geri döndü |
| DB volume'ünü başka bir container kullanırken `live.ps1 up` / deploy | ✅ İkisi de reddetti (ön kontrol, canlıya dokunmadan) |
| `live.ps1 down -v` | ✅ Reddedildi |
| `backup.ps1` canlıya karşı | ✅ |
| Geliştirme stack'i (`docker compose up`) | ✅ 8180/8100/5532, ayrı volume'ler, `SCHEDULER_ENABLED=false`, migration, smoke, `backup.ps1 -Stack dev` |

Sandbox'ın bulduğu ve düzeltilen hatalar:
- `docker-compose.live.yml`'de imaj adı sabitti.
- `state.json`'da tek kayıtlık geçmiş liste yerine nesne olarak yazılıyordu.
- `rollback -RestoreBackup` yedeği, yedeği olmayan bir rollback kaydından arıyordu.
- Volume koruması, compose dışı container için yanlış komut öneriyordu.

Sonda kendi açtığım her şey kaldırıldı: dev stack, sandbox, aday stack'ler, `yaver-e2e-deploy`,
volume'leri ve imajları.

## 2-3. nginx (Y2, O3)

- **Y2:** iki `location`'da da `proxy_set_header X-Forwarded-For $remote_addr`. Benim e2e
  kopyamda (`yaver-e2e-deploy`, :8091) `login-limit.spec.ts` (her denemede yeni sahte
  `X-Forwarded-For`, nginx üzerinden) ve `auth.spec.ts` geçti; aday stack'teki 19 e2e testi de
  geçti. Not: `tailscale serve` arkasında bütün cihazlar tek adres olarak görünür, yani giriş
  sınırı tek kullanıcılı uygulamada fiilen geneldir.
- **O3:** `map $request_uri` sorgudaki `token=` değerini `***` yapıyor; `$request` log
  formatından çıkarıldı (ham URI'yi taşıyor). Doğrulama:
  `GET /api/calendar.ics?foo=1&token=QA-MASK-PROBE-123&x=2` → nginx logu
  `"GET /api/calendar.ics?foo=1&token=***&x=2 HTTP/1.1"`, sondaj dizesi nginx logunda 0 kez.
  `nginx -t` geçti.
- **Açık kalan:** api'nin kendi (uvicorn) erişim logu token'ı hâlâ yazıyor (sondaj dizesi api
  logunda 1 kez). Bu backend tarafı, benim alanım dışında. Seçenekler: `uvicorn.access`'e
  `token=` maskeleyen bir `logging.Filter`, ya da canlı compose'da `--no-access-log` (nginx
  logu zaten var).

## 4. KULLANIM.md

- Dokuz çalışan için tablo: alan + mesai.
- Bir çalışanla konuşmanın dört yolu: genel sohbet, adıyla çağırmak, ofiste tıklayıp doğrudan
  sohbet, deftere baktırmak. Görev panosunun sütunları ve kırmızı noktanın iki anlamı.
- Her çalışan için örnek cümleler.
- Metrics: Ads Manager'dan CSV dışa aktarma, dosyayı atınca ne olduğu, tekrar atınca ne olduğu,
  Geri al ve sonradan sorulabilecek sorular.
- Venture: salt okunur repo takibi (ilk harita, sabah kontrolü, takvim + takip, hatırlatma,
  GitHub'dan eklenenleri geri almak).
- Creator: Pazartesi taslakları, neye dayandıkları ve hiçbir şeyin paylaşılmadığı.
- Zamanlama tablosu güncellendi (brifing 09:00, gün sonu raporu 21:15, mesai işleri).
- Sorun giderme yeni komutlara göre güncellendi.
- Kodda henüz olmayan şeyler (`log_workout`, sohbetten uygulama limiti) örneklerden çıkarıldı.

---

## Dikkat edilecekler / yapılmayanlar

1. **`yaver-e2e` kapatılmadı.** Görev `docker compose -p yaver-e2e down` diyordu, ama o an çalışan
   `yaver-e2e` stack'i ana klasörden (`C:\Users\PC\Desktop\yaver\e2e`) birinci ajan tarafından
   açılmıştı ve kullanımdaydı. Kapatmak onun testlerini yarıda keserdi. Ben doğrulamayı kendi
   kopyalarımda yaptım (`yaver-e2e-deploy` :8091, `yaver-e2e-sbxcand` :8092) ve onları kapattım.
   İş bitince: `docker compose -p yaver-e2e down`.
2. **Merge = davranış değişikliği.** Bu branch `main`'e girince ana klasördeki `docker compose`
   komutları `yaver-dev`'i yönetir; çalışan eski `yaver` stack'i durdurulana kadar olduğu gibi
   kalır. Merge'ü geçişle aynı oturumda yapmak en temizi (rehber, Adım 0).
3. **CLAUDE.md ve README güncel değil** (yazma iznim yoktu). Geliştirme adresleri artık
   8180/8100. "Her maddeden sonra api'yi kontrol et" adımı geliştirmede
   `docker compose ps` + `http://localhost:8100/api/health/ready`, canlıda
   `.\scripts\live.ps1 ps` + `.\scripts\smoke.ps1 -NoChat` olmalı. CLAUDE.md'ye "canlıya yalnız
   `deploy-live.ps1`" kuralı eklenmeli.
4. Deploy, `main`'i **yerel** depodan alır (fetch yapmaz). Web için deploy'da `vitest` /
   `eslint` çalışmıyor; web imajının build'i `tsc -b` ile tip kontrolü yapıyor. İstenirse aday
   aşamasına `npm run check` eklenebilir.
5. İlk geçişte deploy ilk kez build ettiği için 5-10 dakika sürer. Sonrakiler önbellekle
   ~1-2,5 dakika (sandbox: 69-136 sn), kesinti yalnız geçiş anında.
6. Yepyeni bir kurulumda DB volume'ü henüz yoktur: `deploy-live.ps1 -NewDatabase`. Mevcut
   kurulumda bu bayrağa gerek yok; volume bulunamazsa betik kasıtlı olarak durur.
7. `.env`'de eski `WEB_PORT` / `API_PORT` / `DB_PORT` artık okunmuyor. Yerine `LIVE_WEB_PORT`
   ve `DEV_*` geldi; geçişte eklenmeli (rehber, Adım 0).
