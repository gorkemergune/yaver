# Gündüz raporu — 21 Kasım 2026

Kuyruktaki 9 maddenin hepsi yapıldı. İkisinde (5, 7) bir parça canlı ortamda denenemedi;
ayrıntısı aşağıda. Gündüz 16 commit atıldı, **push yok**. `down -v` ve volume silme
yapılmadı, `.env` değiştirilmedi. Gerçek DB'deki iki migration öncesinde yedek alındı.

> **Kesinti — benim hatam.** Saat ~11:15'ten ~15:00'e kadar dev API açılmadı (unhealthy).
> Kullanım sınırı geldiğinde 7. madde yarımdı ve diskte commit'lenmemiş, bozuk bir satır
> kaldı: `ShiftContext.github: github.GitHub`. Alan adı modülü gölgeliyordu, sıcak yeniden
> yükleme bunu canlı sürece yükledi. Düzeltme ve önlemler aşağıda, "Kesinti" bölümünde.

## Özet

| # | Madde | Durum | Commit'ler |
|---|---|---|---|
| 1 | Masaüstü 401 → cihaz anahtarı (web kartı, masaüstü, Siri belgesi) | ✅ (gerçek sunucuda anahtar girişi senin) | `5408371`, `46a50fc`, `1c9884c` |
| 2 | İngilizce alan isimleri, Arda kaldırıldı, yerel Chrono alanı temizlendi | ✅ | `14b9477` |
| 3 | Spor / antrenman / check-in → Coach, canlı yönlendirme 2 tur | ✅ 19/19 iki kez | `4ba8bfb` |
| 4 | Ofis gecikmesi: 2x yürüme, yolda yön değiştirme, ≤ ~5 sn | ✅ | `442c252` |
| 5 | Metrics: Ads Manager CSV / ekran görüntüsü → tablo, önceki dönem, özet + 3 öneri | ⚠️ CSV canlıda doğrulandı; ekran görüntüsü yolu yalnızca sahte LLM'le test edildi | `2033362`, `2533307` |
| 6 | `deep` tier (Opus 5.5), işaretli haftalık işler, `DEEP_MONTHLY_BUDGET_USD=2` | ✅ | `18b7e90` |
| 7 | Venture + GitHub (salt okunur): harita, sabah teslimleri, takvim + takip, hatırlatma | ⚠️ sahte GitHub API'siyle doğrulandı; senin depon `.env`'deki yer tutucu yüzünden bağlanamadı | `11afbde` |
| 8 | Creator: web arama anahtarı olmadan haftalık içerik takvimi taslağı, paylaşım yok | ✅ canlı (Sonnet) doğrulandı | `7462f60` |
| 9 | Ofis + görev panosu ekran görüntüleri (masaüstü + 390 px), yeni isimlerle | ✅ | `601f108` |
| – | Kesinti sonrası: smoke testi + CLAUDE.md sağlık kuralı | ✅ | `e16b843` |
| – | Görev panosu: onay sütunu mesai işini değil soran sohbet görevini gösterir | ✅ | `5cfb433` |

**Son kontroller (hepsi yeşil):**
- **Backend:** ruff, ruff format, mypy (200 dosya), pytest 1036 (canlı testler hariç).
- **Web:** tsc, eslint, vitest 58.
- **Masaüstü:** tsc, eslint, vitest 15, `cargo test` 44, `clippy -D warnings`. Kurulum dosyası: `desktop/src-tauri/target/release/bundle/nsis/Yaver_0.1.0_x64-setup.exe`.
- **Çalışan API:** `docker compose ps` → `(healthy)`, `/api/health/ready` → 200. 7. ve 8. maddelerden sonra API yeniden başlatıldı, yeni mesai işleri zamanlayıcıda.

**LLM harcaması (gündüz): ≈ $0,13** ($1 sınırının altında). Canlı testlerin hepsi test DB'sinde koştu.

| Kalem | Tutar |
|---|---|
| Yönlendirme seti, 2 tur (19 mesaj) | ≈ $0,030 |
| Metrics canlı, 2 koşu (Opus analiz + Haiku cevap) | $0,0246 + $0,0382 |
| Creator canlı, 3 koşu (Sonnet) | $0,0116 + $0,0106 + $0,0133 |
| Masaüstü uçtan uca 2 mesaj (Haiku) | ≈ $0,002 |
| Gerçek DB, bugün | $0,0005 |

## Maddeler

### 1. Masaüstü 401 → cihaz anahtarı
**Sebep:** masaüstü uygulaması hiç giriş yapmamıştı (`%APPDATA%\com.yaver.desktop\session.json` yoktu). `APP_PASSWORD` gerçek bir değer olunca `GET /api/team` ve `POST /api/chat` 401 döndü.

**Çözüm:**
- **Anahtar:** `yvk_` + 43 karakter. Sunucu yalnızca SHA-256'sını saklıyor (`device_keys` tablosu). Anahtarın süresi dolmuyor, istenince iptal ediliyor. API: `GET/POST /api/devices`, `DELETE /api/devices/{id}`.
- **Web:** Durum → **Cihaz anahtarları** kartı: oluştur (anahtar bir kez görünür, kopyala), son kullanım, iptal.
- **Masaüstü:** parola alanının yerini cihaz anahtarı aldı. Anahtar kaydedilmeden önce sunucuya sorulur. İlk açılışta ya da sunucu anahtarı reddettiğinde sohbet paneli kendiliğinden ⚙ Ayarlar'da açılır: "bu bilgisayara bir cihaz anahtarı gerekiyor".
- **Siri:** `docs/tr/cihaz-anahtari.md` (Kestirmeler: Dikte → `POST /api/chat`, `Authorization: Bearer yvk_…` → cevabı seslendir).

**Uçtan uca doğrulama** (dev masaüstü, parolalı test API'si, test DB'si):
1. İlk açılış anahtar ekranına geldi.
2. Anahtar kabul edildi.
3. "Yarın ne var?" gerçek bir cevap aldı: "Yarın, Pazar 22 Kasım, planında hiçbir şey yok…".
4. Anahtar iptal edilince uygulama tekrar anahtar istedi.

### 2–4, 9
Bunlar sabah bitti (yukarıdaki commit'ler). Yönlendirme: koordinatör prompt'unda spor / antrenman / ekran süresi kuralı var ve canlı set iki turda 19/19.

### 5. Metrics: dosyadan reklam analizi
- **CSV:** kodda ayrıştırılır, LLM yok. Türkçe/İngilizce başlıklar, `;` ve `,` ayırıcılar, `1.234,50` biçimi, toplam satırı atlanır. Eksik CTR, CPC ve sonuç başı maliyet hesaplanır.
- **Ekran görüntüsü:** `image_contents` → `ad_report` → `ads_image` (Sonnet). Tarih aralığı yazıldığı gibi alınır, kodda çözülür.
- **Kayıt:** `ad_reports` + `ad_metrics`, mesajın change_set'iyle (Geri al). Aynı dosya iki kez kaydedilmez.
- **Karşılaştırma:** önceki dönemle kodda (değişim yüzdeleri, toplam satırı).
- **Analiz:** kodda tek bir çağrı (`ads_weekly_report` → deep, Opus): özet + tam 3 öneri. Rapora ve Metrics'in defterine yazılır, Metrics cevapta aktarır.
- **Uydurma örnekler:** `examples/meta-ads/` ("Örnek Kafe", iki hafta).

**Canlıda bulunan sorun:** Opus ilk koşuda 3 öneriyi tek bir dizgeye yazdı ve şema reddetti. Analiz düzgün düştü ("yapılamadı"). Düzeltme: tek dizgedeki numaralı öneriler kodda bölünüyor, olmazsa bir kez yeniden soruluyor. İkinci koşuda öneriler sayılarla tutarlı geldi.

**Canlıda denenmeyen:** ekran görüntüsü yolu (elimde gerçek bir Ads Manager ekran görüntüsü yok).

### 6. deep tier
- **Yapılandırma:** `providers.example.yaml` ve yerel `providers.yaml`'da `deep: claude-opus-5-5` (`effort: high`; Opus 5.5'te thinking kapatılamaz). Model kimliği sağlayıcıda var (`check_models` OK).
- **Kim kullanabilir:** `routing.explicit_only: [deep]`. Yalnızca `routing.purposes`'ta deep'e bağlı amaçlar kullanabilir: `ads_weekly_report`, `startup_weekly_review`. Başka bir çağrı kodda `ValueError` alır. Varsayılan, failover ya da bütçe adımı deep'e çıkamaz (doğrulayıcı reddeder).
- **Bütçe:** `budget.tier_limits.deep` → `DEEP_MONTHLY_BUDGET_USD` (varsayılan 2). Dolunca `smart`'a iner. Opus harcaması Claude bütçesine de sayılır: %80'de Haiku, %100'de Claude yok.
- **Görünüm:** Durum ekranında ayrı bir Opus çubuğu.

### 7. Venture + GitHub (salt okunur)
- **İstemci:** `integrations/github.py`. `ReadOnlyTransport` GET/HEAD dışındaki her isteği kodda reddeder (test edildi).
- **Ayarlar:** `.env.example`'a `GITHUB_TOKEN`, `GITHUB_STARTUP_REPO` eklendi. Fine-grained, salt okunur izinler.
- **Sabah 08:15 (`github_watch`):**
  - İlk sefer depo haritasını deftere yazar: README, hafta klasörleri, toplantı notları, issue'lar, milestone'lar, son 7 günün commit'leri, ekip.
  - Son hafta klasörüne kimin teslim ettiğine bakar.
  - Toplantı notu, issue ve milestone'lardaki tarihli maddeleri takvime (tüm gün teslim) ve o güne takibe ekler. Bir kez ekler, tek change_set, geri alınabilir.
  - 3 gün içindeki bir iş için dosya/PR yoksa hatırlatır; varsa takibi kapatır.
- **Token yoksa:** "GitHub entegrasyonu bekliyor" notu (günde bir).
- **Doğrulama:** sahte GitHub API'si (hafta-01..03, toplantı notu, issue #4 + "Closes #4" PR'ı, milestone, demo PR'ı). 14 test.
- **Senin deponda neden denenmedi:** `.env`'deki `GITHUB_STARTUP_REPO` yer tutucu (`…/<startup>`). Değerin kendisini, doğrulayıcı açılışta onu reddedince hata mesajında gördüm; `.env` dosyasını açmadım. Artık geçersiz değer uygulamayı durdurmuyor, entegrasyonu kapalı sayıp logda uyarıyor.

### 8. Creator: içerik takvimi
- **Ne zaman:** haftalık mesai işi `content_calendar` (Pazartesi 10:30) ve sohbet aracı `draft_content_calendar`.
- **Bağlam (kodda toplanır):**
  - `agents.yaml`'daki `topics` (yerelde "Nexa Lab", örnekte "Örnek Girişim"; marka adı koda gömülü değil),
  - bu markadan bahseden hatıralar,
  - Venture'ın son 14 günkü notları (entegrasyon-bekliyor notları hariç),
  - önümüzdeki 14 günün ilgili etkinlikleri,
  - web arama anahtarı varsa trendler. Yoksa "trend yok, anahtar gelince eklerim" denir.
- **Üretim:** tek `smart` çağrısı. Gün adları tarihe kodda çevrilir. Sonuç deftere "taslak, paylaşılmadı" diye yazılır. **Paylaşan araç yok** (test: kayıtta post/publish/share benzeri araç yok).
- **Canlıda bulunan sorun:** model, Cumartesi olan provayı Perşembe "bugün", Cuma "dün" diye yazdı. Modele haftanın gün-tarih listesi ve etkinliklerin gün adları verildi, kural eklendi. Son koşuda Cuma "yarın prova", Cumartesi "bugün prova".

## Kesinti (11:15–15:00) ve önlemler
- **Sebep:** commit'lenmemiş ara durumda `github` alanı aynı adlı modülü gölgeledi. Dev konteyneri sıcak yeniden yükleme yaptığı için canlı süreç `AttributeError` ile açılamadı. Benim testlerim o ana kadar koşmamıştı; kullanım sınırı tam o anda geldi.
- **Düzeltme:** modül `github as gh`, `web_search` da `websearch` takma adıyla alındı. Tüm backend AST ile tarandı; kırılan başka çakışma yok.
- **Önlemler:**
  - `tests/test_smoke.py`: `app.main:app` `/health`'e cevap veriyor ve `app/` altındaki her modül içe aktarılıyor. Hatayı geri getirince test kırmızıya döndü.
  - CLAUDE.md: her maddeden sonra `docker compose ps` healthy + `/api/health/ready` 200 kontrolü.
  - CLAUDE.md: sınıf alanı modül adını gölgelemez.
  - CLAUDE.md: geçersiz bir `.env` değeri uygulamayı düşürmez.

## Kararlar
- **karar:** Yaver'in rolü "Chief of Staff"; diğerlerinin rolleri Türkçe kaldı. Arda'nın `deadline_watch` işi Chrono'ya geçti, masası boş.
- **karar:** README ekran görüntüleri yeniden adlandırmadan sonra, örnek ekip ve uydurma verilerle bir kez çekildi. Geliştirici ritüel çubuğu görüntülere girmedi.
- **karar:** ofiste figür adımı 450 ms (adım boyu aynı, A* garantisi korunur). Toplantı/masa bekleme 3 sn / 2 sn. Grup bekleme kuralı kaldırıldı (yürüyenleri de tutuyordu).
- **karar:** görev panosunun "Onay bekliyor" sütunu mesai işlerini saymaz; soran sohbet görevini gösterir.
- **karar:** cihaz anahtarı oturumdan ayrı bir tablo: süresiz, hash'li, cihaz başına bir anahtar. Masaüstü anahtarı kaydetmeden önce sunucuya doğrulatır.
- **karar:** `deep` yalnızca amaç eşlemesiyle açılır, kod zorlar. Opus kendi sınırına (2 $) ek olarak Claude bütçesine de sayılır. %80'de deep → Haiku (`fallback`; yerelde `fast`).
- **karar:** reklam raporu, dosya gönderilince hemen kaydedilir (öneri/onay akışı yok): kullanıcı dosyayı analiz için atıyor ve Geri al hepsini siler. Analiz, modelin atlayabileceği bir araç değil, kodda tek bir çağrı.
- **karar:** reklam analizi `ads_weekly_report` amacıyla deep'te çalışır (haftalık rapor = haftalık dosya). `startup_weekly_review` deep'e bağlı ama henüz onu çağıran iş yok. Haftalık startup değerlendirmesi, GitHub verisi gelince eklenecek.
- **karar:** GitHub'dan gelen tarihli maddeler takvime ve takibe kendiliğinden yazılır (kullanıcının açık isteği). Notta değişiklik kimliği yazar, geri alınabilir. Yılsız tarih bugüne en yakın yıl sayılır.
- **karar:** mesai işleri LLM kullanmaz; tek istisna `content_calendar` (haftada bir `smart` çağrısı, Creator'ın günlük bütçesi geçerli).
- **karar:** tarih aralıklarında düz `-` kullanıldı ("9-15 Kas 2026"), en-dash yok (ruff RUF001).

## Akşam senin adımların
1. **GitHub (Venture).** Ayrıntı: `docs/tr/venture-github.md`.
   - `.env`'de `GITHUB_STARTUP_REPO`'yu gerçek `sahip/depo` yap. Şu an yer tutucu, entegrasyon kapalı.
   - `GITHUB_TOKEN` dolu görünüyor (değerine bakmadım). Fine-grained, yalnızca o depo, Contents / Issues / Pull requests / Metadata **Read-only** olduğundan emin ol.
   - `docker compose up -d api`, sonra hemen denemek için:
     ```
     curl -X POST -H "Authorization: Bearer yvk_..." http://localhost:8000/api/jobs/shift:startup:github_watch/run
     ```
     Sonuç Venture'ın defterine düşer: ilk seferde harita, ardından sabah notu.
2. **Cihaz anahtarı (masaüstü).** Ayrıntı: `docs/tr/cihaz-anahtari.md`.
   - Web → Durum → Cihaz anahtarları → ad "Masaüstü" → **Cihaz anahtarı oluştur** → Kopyala.
   - Yeni masaüstü sürümünü kur: `desktop\src-tauri\target\release\bundle\nsis\Yaver_0.1.0_x64-setup.exe`. Eski kurulu uygulamayı test için kapatmıştım.
   - İlk açılışta ayarlar kendiliğinden açılır: anahtarı yapıştır → Kaydet → sohbette bir mesaj dene.
3. **Siri.** Ayrı bir "iPhone Siri" anahtarı oluştur, Kestirmeler'deki 4 adımı aynı belgeden kur. Telefonun Tailscale'den erişmesi gerekir.
4. **İsteğe bağlı:** `.env`'e `DEEP_MONTHLY_BUDGET_USD=2` (yazmazsan da varsayılan 2).
5. **Metrics'i dene:** `examples/meta-ads/` içindeki iki CSV'yi sırayla sohbete at. Gerçek DB'ye rapor yazar; "Geri al" ile silinir. Gerçek bir Ads Manager ekran görüntüsüyle de bir kez dene (canlıda denenmeyen tek yol).
6. **Migration'lar:** gerçek DB'ye uygulandı (`ad7c26be72b1` device_keys, `d37bc5b1bb0c` ad_reports). Önceki yedekler: `backups/yaver-20261121-074436.sql.gz`, `backups/yaver-20261121-081154.sql.gz`.
7. Bakıp memnunsan **push** (ben push etmedim).

**Bilinen eksik:** `docs/tr/KULLANIM.md`'nin ekip tablosunda hâlâ eski isimler var (Friday / Jarvis / Karen). Bugünkü kuyrukta değildi, dokunmadım.
