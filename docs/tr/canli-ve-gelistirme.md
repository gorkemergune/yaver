# Canlı ve geliştirme kurulumu

Bugüne kadar tek bir stack vardı (`yaver`): gerçek veritabanı, kod değişince kendini yeniden
yükleyen geliştirme sunucusu, port 8080. Yarım kalmış bir kod değişikliği, telefondaki,
masaüstündeki ve Siri'deki Yaver'i doğrudan bozabiliyordu (21 Kasım'daki 11:15-15:00 kesintisi
böyleydi). Artık iki ayrı kurulum var:

| | **Canlı** (`yaver-live`) | **Geliştirme** (`yaver-dev`) |
|---|---|---|
| Ne için | Her gün kullandığın Yaver: telefon, masaüstü, Siri, takvim aboneliği | Kod yazmak, denemek |
| Adres | http://localhost:8080 (Tailscale'deki adres de bu) | http://localhost:8180 · api :8100 · db :5532 (yalnız bu bilgisayar) |
| Kod | `main`'in test edilmiş bir commit'inden **build edilmiş imaj**; reload yok | Çalışma klasörü, kaydettiğin an yeniden yüklenir |
| Veritabanı | Gerçek veri: mevcut `yaver_pgdata` volume'ü | Ayrı test veritabanı: `yaver-dev_pgdata` |
| Yüklemeler / yedekler | `uploads\`, `backups\` | Kendi volume'leri (gerçeklere karışmaz) |
| Zamanlayıcı (brifing, check-in, mesai) | Açık | Kapalı (`DEV_SCHEDULER_ENABLED=true` ile açılır) |
| Nasıl güncellenir | Yalnızca `.\scripts\deploy-live.ps1` | `docker compose up -d` |
| Dosya | `docker-compose.live.yml` | `docker-compose.yml` + `docker-compose.override.yml` |

İki kurulum aynı anda çalışır. Her ikisi de aynı `.env`'i okur (LLM anahtarları, parola);
geliştirmede yaptığın LLM çağrıları da gerçek paradır.

> Komutların hepsi PowerShell 7'de (`pwsh`), repo klasöründen (`C:\Users\PC\Desktop\yaver`).

---

## Geçiş (bir kere)

**Bu gece yapılmayacak.** Uygun bir zamanda, yaklaşık 20-30 dakika ayırarak:

### 0. Hazırlık

- `feat/live-deploy` branch'i `main`'e merge edilmiş olsun ve açık bir kod çalışması kalmasın
  (geçişten sonra `docker compose` komutları geliştirme stack'ini yönetir).
- `.env`'e şu satırları ekle (`.env.example`'da da var). Eski `WEB_PORT` / `API_PORT` /
  `DB_PORT` satırları artık kullanılmıyor, silebilirsin:
  ```
  LIVE_WEB_PORT=8080
  DEV_WEB_PORT=8180
  DEV_API_PORT=8100
  DEV_DB_PORT=5532
  DEV_SCHEDULER_ENABLED=false
  ```
  `.env`'de backend'i Docker dışında çalıştırmak için bir `DATABASE_URL` varsa portunu `5532`
  yap (geliştirme veritabanı; canlı veritabanının dışarıya açık portu yok).

### 1. Elle bir yedek al (eski stack hâlâ çalışırken)

```powershell
$env:YAVER_LIVE_PROJECT = "yaver"; .\scripts\backup.ps1; Remove-Item Env:YAVER_LIVE_PROJECT
```
Çıktıda `backups\yaver-....sql.gz` yazmalı. (Geçişten sonra `.\scripts\backup.ps1` doğrudan canlıyı yedekler.)

### 2. Eski stack'i durdur (silme)

```powershell
docker stop yaver-web-1 yaver-api-1 yaver-db-1
```
Konteynerler silinmez; geçiş ters giderse aynı komutun `start`'ıyla geri gelir. Gerçek veritabanı
`yaver_pgdata` volume'ünde durur. **`docker compose down -v` yazma.**

Neden durdurmak şart: aynı veritabanı klasörünü iki PostgreSQL aynı anda açarsa veri bozulur.
Deploy betiği bunu kontrol eder ve eski stack çalışıyorsa başlamaz.

### 3. İlk deploy

```powershell
.\scripts\deploy-live.ps1
```
İlk sefer imajlar sıfırdan build edildiği için 5-10 dakika sürer. Ne yaptığı aşağıda
("Canlıya almak"). Sonunda yeşil `DEPLOYED <etiket>` görmelisin.

### 4. Kontrol et

- Tarayıcıda http://localhost:8080 → giriş, Ofis, Sohbet, Takvim. Verilerin yerinde olmalı.
- Telefonda Tailscale adresi (aynı 8080'e gider), masaüstü uygulaması, Siri kısayolu: değişen bir
  şey yok, aynı adres ve aynı cihaz anahtarları.
- `.\scripts\live.ps1 status` → `current: <etiket>`.
- `.\scripts\smoke.ps1 -NoChat` → `all checks passed`.

### 5. Geliştirme stack'ini kur

```powershell
docker compose up -d --build
docker compose exec api alembic upgrade head
```
http://localhost:8180 boş bir Yaver açar. Gerçek verinin bir kopyasıyla denemek istersen (yerel
kalır, ama dev'de yaptığın değişiklikler gerçeğe gitmez):
```powershell
.\scripts\backup.ps1 -Stack dev restore backups\yaver-....sql.gz yaver -Yes
docker compose restart api
```

### 6. Birkaç gün sorunsuz geçtikten sonra

Eski konteynerleri kaldır (volume'e dokunmaz; `yaver_pgdata`'yı artık canlı kullanıyor):
```powershell
docker rm yaver-web-1 yaver-api-1 yaver-db-1
```

### Geçiş ters giderse

`deploy-live.ps1` ilk deploy'da hata verirse canlı api/web başlatılmaz ve ne olduğunu yazar.
Eski stack'e dönmek için:
```powershell
docker stop yaver-live-web-1 yaver-live-api-1 yaver-live-db-1   # varsa
docker start yaver-db-1 yaver-api-1 yaver-web-1
```
Deploy, geçişten (migration) önce yedeği `backups\predeploy\` altına alır; şema değiştiyse ve
geri dönmek gerekirse oradan geri yüklenebilir (bkz. "Geri almak").

---

## Günlük kullanım

### Geliştirmek

1. Kodu değiştir; geliştirme stack'i (`:8180`) kendini yeniden yükler. Canlı etkilenmez.
2. Testler: `docker compose exec api pytest`, `cd web; npm run check`, gerekirse e2e (`e2e/README.md`).
3. Commit → `main`.

`docker compose ...` komutlarının hepsi (CLAUDE.md'dekiler dahil) artık geliştirme stack'ine gider.

### Canlıya almak

```powershell
.\scripts\deploy-live.ps1                 # main'in son commit'i
.\scripts\deploy-live.ps1 -Ref 1a2b3c4    # belirli bir commit
```

Sırasıyla:

1. **Dışa aktarma:** commit, çalışma klasöründen bağımsız ayrı bir klasöre çıkarılır
   (`%USERPROFILE%\yaver-releases\yaver-live\releases\<etiket>`). Yarım kalmış, commit'lenmemiş
   hiçbir şey canlıya gitmez. Etiket: `YYYYMMDD-HHMM-<kısa sha>`.
2. **Build:** `yaver-live-api:<etiket>`, `yaver-live-web:<etiket>` ve testler için bir geliştirme imajı.
3. **Test** — geçici bir stack'te (`yaver-e2e-release`, portlar 8092/8003/5435, boş veritabanı):
   - `pytest` (gerçek LLM çağıran testler hariç),
   - smoke kontrolleri (sağlık, giriş, ekip, ofis, plan, harcama),
   - Playwright e2e testleri (LLM'siz).
4. **Yedek:** canlı veritabanının tam yedeği → `backups\predeploy\yaver-predeploy-<etiket>.sql.gz`
   (son 5 tanesi tutulur).
5. **Migration provası:** bu yedeğin bir kopyası geçici stack'e yüklenir ve yeni sürümün
   migration'ları onun üzerinde çalıştırılır. Bugünkü verinde patlayacak bir migration canlıya
   dokunmadan yakalanır.
6. **Geçiş:** eski api/web durur, migration canlı veritabanında çalışır, yeni imajlar başlar.
   Kesinti genelde 20-40 saniye.
7. **Sağlık kontrolü:** api konteyneri *healthy* olmalı, `/api/health/ready` 200 dönmeli ve smoke
   kontrolleri 8080 üzerinden (girişle) geçmeli.

**1-5'te bir şey başarısız olursa** canlıya hiç dokunulmaz; eski sürüm çalışmaya devam eder ve
betik kırmızı `DEPLOY FAILED at stage '<aşama>': <neden>` yazar.
**6-7'de başarısız olursa** otomatik olarak önceki sürüme döner; migration şemayı değiştirmişse
önce yedeği geri yükler (geçiş sırasında api kapalı olduğu için arada yazılan bir şey kaybolmaz).

Her deploy'un tam çıktısı `%USERPROFILE%\yaver-releases\yaver-live\logs\deploy-<etiket>.log`'da,
özeti `state.json`'da. Son 3 başarılı sürümün imajları ve klasörleri tutulur, eskileri silinir.

Seçenekler: `-KeepCandidate` (test stack'i incelemek için açık bırakır; sonra
`docker compose -p yaver-e2e-release down -v`), `-SkipE2E` (yalnızca acil durumda; pytest ve
smoke yine çalışır).

### Geri almak

```powershell
.\scripts\rollback-live.ps1 -List            # tutulan sürümler ve son deploy'lar
.\scripts\rollback-live.ps1                  # bir önceki sürüme dön
.\scripts\rollback-live.ps1 -To 20261121-2215-1a2b3c4
.\scripts\rollback-live.ps1 -RestoreBackup   # + veritabanını o deploy'dan hemen önceki hâline getir
```

Varsayılan olarak veritabanına dokunmaz: yalnızca imajlar değişir. Mevcut sürüm şemayı eski
kodun okuyamayacağı şekilde değiştirdiyse betik uyarır; o zaman `-RestoreBackup` kullan. Bu,
o deploy'dan sonra yazılan her şeyi (sohbetler, eklenen etkinlikler) siler; betik "evet" diye
onay ister.

### Canlıyı yönetmek

`docker compose` yerine `.\scripts\live.ps1` (doğru proje, doğru dosya, doğru imaj etiketi):

```powershell
.\scripts\live.ps1 status                    # hangi sürüm, son deploy'lar
.\scripts\live.ps1 ps
.\scripts\live.ps1 logs -f --tail 100 api
.\scripts\live.ps1 restart api               # config\*.yaml değişince
.\scripts\live.ps1 up -d                     # .env değişince (restart .env'i yeniden okumaz)
.\scripts\live.ps1 exec api python -m app.llm.check_models
.\scripts\smoke.ps1 -NoChat                  # canlı sağlam mı
.\scripts\smoke.ps1                          # + gerçek bir sohbet mesajı ve geri alma (birkaç sent)
```

`live.ps1 down -v` reddedilir; canlı veritabanı volume'ü zaten "external" olduğu için compose
onu hiçbir komutla silemez.

### Yedek

```powershell
.\scripts\backup.ps1                         # canlı (varsayılan)
.\scripts\backup.ps1 -Stack dev              # geliştirme -> backups\dev\
.\scripts\backup.ps1 list
```
Canlı api açılışta, son yedek 24 saatten eskiyse kendisi de yedek alır. Ayrıntı: [yedekleme.md](yedekleme.md).

---

## Nerede ne var

| Ne | Nerede |
|---|---|
| Canlı tanımı | `docker-compose.live.yml` (her sürüm kendi kopyasıyla çalışır) |
| Geliştirme tanımı | `docker-compose.yml` + `docker-compose.override.yml` |
| Betikler | `scripts\deploy-live.ps1`, `rollback-live.ps1`, `live.ps1`, `live-common.ps1`, `smoke.ps1`, `backup.ps1` |
| Sürümler, loglar, durum | `%USERPROFILE%\yaver-releases\yaver-live\` (`state.json`, `releases\`, `logs\`) — `.env`'de `YAVER_RELEASES` ile değişir |
| Deploy öncesi yedekler | `backups\predeploy\` |
| Gerçek veritabanı | Docker volume `yaver_pgdata` |
| Geliştirme veritabanı | Docker volume `yaver-dev_pgdata` |

## Sorunlar

| Belirti | Ne yap |
|---|---|
| `the database volume yaver_pgdata is in use by yaver-db-1` | Eski stack çalışıyor: `docker stop yaver-web-1 yaver-api-1 yaver-db-1` |
| `database volume yaver_pgdata does not exist` | Gerçek veritabanı bulunamadı: `docker volume ls`'de adı farklı mı (`.env`'de `YAVER_LIVE_DB_VOLUME`)? Yalnızca **yepyeni** bir kurulumda `-NewDatabase` ile çalıştır (boş veritabanı oluşturur). |
| `another deploy seems to be running` | Gerçekten çalışan bir deploy yoksa `...\yaver-releases\yaver-live\deploy.lock`'u sil |
| `DEPLOY FAILED at stage 'tests'` | Logda hangi test: pytest / smoke / Playwright. Canlı etkilenmedi. Düzelt, commit'le, tekrar dene. `-KeepCandidate` ile test stack'i açık kalır (http://localhost:8092, parola `e2e-test-password`). |
| `stage 'rehearsal'` | Yeni bir migration bugünkü verinle çalışmıyor. Canlı etkilenmedi. |
| `stage 'health'` ve "Back on ..." | Yeni sürüm açılmadı, eskisine dönüldü. `logs\deploy-<etiket>.log`'un sonuna ve yeni api'nin hatasına bak. |
| `ROLLBACK FAILED` | `.\scripts\rollback-live.ps1 -List`, sonra `.\scripts\rollback-live.ps1`. O da olmazsa `-RestoreBackup`. |
| Port 8080 dolu | Eski stack'in web'i açık olabilir (`docker ps`). |
| Disk doluyor | Her sürüm ~1.5 GB imaj; son 3'ü tutulur. `docker image prune` kullanılmayanları siler. |

## Deploy betiğini denemek (geliştirici notu)

Betikler gerçek canlıya hiç dokunmadan ayrı bir "kum havuzu"nda denenebilir: proje adı, port,
volume, imaj öneki ve durum klasörü ortam değişkeniyle değişir (`scripts\live-common.ps1`'in
başı). Örnek: `YAVER_LIVE_PROJECT=yaver-sandbox`, `LIVE_WEB_PORT=8095`,
`YAVER_LIVE_DB_VOLUME=yaver-sandbox_pgdata` (önce `docker volume create`),
`YAVER_LIVE_MODELS_VOLUME=yaver-sandbox_models`, `YAVER_LIVE_IMAGE=yaver-sandbox`,
`YAVER_RELEASES=<geçici klasör>`, `SCHEDULER_ENABLED=false`, `BACKUP_DIR=<geçici klasör>`,
`YAVER_CANDIDATE_PROJECT=yaver-e2e-sbx`. `-SimulateFailure tests|health` başarısızlık yollarını dener.
