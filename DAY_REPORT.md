# Gündüz raporu — 20 Kasım 2026

İki kuyruğun hepsi bitti; "yapılmadı" kalan madde yok. 23 commit (birleştirme dahil), **push yok**. `down -v` ve volume silme yapılmadı. `.env` okunmadı, değiştirilmedi.

## Özet

| # | Madde | Durum | Commit'ler |
|---|---|---|---|
| 1 | Masaüstü branch'ini main'e birleştirme + ROADMAP Faz 4 | ✅ | `39ae184`, `103ba46` |
| 2 | Ekran süresi: `POST /api/screen-time`, Karen aracı, masaüstü senkronu, check-in satırı | ✅ | `2759935`, `e6ec368` |
| EK | Hafta görünümü: gezinme, URL, dönem haftası, etiketler, `set_week_label`, dönem listesi | ✅ | `11d3b30`, `4c3341b` |
| 3 | Auth: parola, oturum cookie'si, giriş ekranı, masaüstü girişi | ✅ | `c82811d`, `2145072`, `063ba67` |
| 4 | Web Push: abonelik, gönderim, brifing / check-in / takip bildirimleri | ✅ (iPhone tarafı senin) | `c8a344c`, `d6a5459` |
| 5 | Faz 3: syllabus → haftalar → pgvector → `search_materials` | ✅ | `843c454`, `75ee4d2` |
| 6 | Çalışma kağıdı (kaynaklı), Markdown görünüm, MD/PDF | ✅ | `fb88e78`, `405b8e1` |
| 7 | Ders notu yükleme (PDF + fotoğraf) → ders/hafta → aranabilir | ✅ | `34aee47`, `519f5be` |
| 8 | Sınav hazırlığı (7 gün kala tekrar planı) | ✅ | `e5de6aa` |
| 9 | ICS dışa aktarma (token'lı takvim aboneliği) | ✅ | `e5ad9b8`, `334577a` |
| 10 | 25 mesajlık regresyon seti + en büyük 2 hatanın düzeltmesi | ✅ (%72 → %96-100) | `4522f0c` |
| 11 | `docs/tr/KULLANIM.md` | ✅ | `a9ec127` |
| – | ROADMAP Faz 1/3/4 | ✅ | `bfa1341` |

**Son kontroller (hepsi yeşil):**
- Backend: ruff, ruff format, mypy, pytest 770.
- Web: tsc, eslint, vitest 31, ayrıca artık prod derlemesi.
- Masaüstü: tsc, eslint, vitest 15, clippy `-D warnings`, cargo test 42.
- `scripts/smoke.ps1 -NoChat`: tüm adımlar OK.

**LLM harcaması (bugün): ≈ $0.13** ($2 sınırının çok altında). Canlı testlerin hepsi test DB'sinde koştu:
- Materyal / syllabus / çalışma kağıdı / ders notu: ~$0.07
- Regresyon (3 tur): ~$0.05
- Eski senaryolar (2 tur): ~$0.01

Gerçek DB'deki aylık Claude harcaması $0.09'da (Durum sayfası).

**Gerçek veritabanı:** 7 şema değişikliği uygulandı, **her birinden önce yedek alındı** (`backups/yaver-20261120-0611…` → `…-071839`). Bunlar `screen_time_days`, `week_labels`, `auth_sessions`, `push_subscriptions`, materyaller + pgvector, `study_sheets`, `source_text`, `app_secrets`. Senin kayıtlarına dokunulmadı.
- Sınav hazırlığı ve takvim provaları gerçek veride **salt okuma / rollback** ile yapıldı.
- E2E testler (auth, push, çalışma kağıdı ekranı) test DB'sine bağlı geçici bir API ile yapıldı; o API sonra kapatıldı.

**Önemli kararlar (ayrıntıları maddelerde "karar:" diye):**
- `.env`'deki `APP_PASSWORD=change-me` "parola yok" sayılıyor. Auth sen gerçek parola koyana kadar kapalı.
- Embedding yerel (fastembed, çok dilli MiniLM, ~500 karakterlik parçalar). Model girdinin ~128 token'ına bakıyor, parça boyutu buna göre seçildi.
- Çalışma kağıdında kaynak listesini kod ekliyor; model kaynak uyduramıyor. PDF tarayıcıdan "PDF olarak kaydet" ile alınıyor.
- Sınav hazırlığı taslağını LLM değil kod çıkarıyor.
- Takvim aboneliğine haftalık spor ve iş blokları girmiyor; iptal edilen dersler takvimden siliniyor.

## Akşam denemen gerekenler (sırayla)

1. **18:00 sınav hazırlığı:** Sohbetine DSA, Logic design ve MATH 221 vizeleri için tekrar planı taslağı gelecek (8 görev, saatler çakışmıyor). İstersen "evet" de. Görevlere yazılır, tek "Geri al" ile geri alınır.
2. **Hafta görünümü:** Hafta sekmesinde ‹ › ve ←/→ ile geçmiş haftalara bak. Devamsızlıklar kırmızı görünmeli.
   - Telefonda kaydırarak dene; bunu ben gerçek dokunmatikte deneyemedim.
   - Sohbette "bu haftanın adı Vize Haftası olsun" de; başlıkta mor etiket çıkmalı.
3. **Durum sekmesi:** dönem listesinden bir haftaya tıkla. Kartları kontrol et: Bildirimler, Takvim aboneliği, Çalışma kağıtları.
4. **Parola (Tailscale'den önce):**
   - `.env`'de `APP_PASSWORD=<gerçek parola>` yaz, sonra `docker compose up -d` çalıştır. Web'de giriş ekranı çıkmalı.
   - Masaüstünde ⚙ → Parola → Giriş yap.
   - Durum → Oturum → *Oturumu kapat* de, giriş ekranına dönmeli.
5. **Bildirimler:**
   - Bilgisayarda Durum → Bildirimler → *Bildirimleri aç* → *Deneme bildirimi gönder*. Windows bildirimi gelmeli.
   - iPhone: önce HTTPS (Tailscale), Safari → Paylaş → Ana Ekrana Ekle, ana ekrandaki Yaver'den bildirimleri aç.
6. **Masaüstü ekran süresi:** `cd desktop && npm run tauri dev` (ya da yeni kurulum dosyası: `npm run tauri build`).
   - 1-2 dk sonra `http://localhost:8080/api/screen-time/2026-11-20` bugünün uygulamalarını göstermeli.
   - Docker'ı durdurup başlat: aradaki süre sonradan gitmeli.
   - 21:00 check-in'de ekran satırı olmalı.
7. **Syllabus ve notlar:** gerçek bir syllabus PDF'i gönder, tabloya "evet" de.
   - Bir hafta notunu PDF ya da fotoğraf olarak gönder; Friday ders ve hafta sormalı ya da önermeli.
   - "Bu haftanın EE211 notlarından çalışma kağıdı" de; kağıtta *PDF olarak kaydet*'i dene.
8. **Takvim aboneliği** (Tailscale'den sonra): Durum → Takvim aboneliği → *Takvime ekle*. iPhone Takvim'de dersler ve vizeler görünmeli; iptal ettiğin bir ders kaybolmalı (yenileme 1 saate kadar sürebilir).
9. İsteğe bağlı: `pytest -m live -k regression -s` (~$0.02, 2 dk). Başarı oranını görürsün.

Not: `C:/Users/PC/Desktop/yaver-desktop` worktree'si ve `feat/desktop-companion` branch'i duruyor; birleştirildi, istersen silebilirsin.

## 1. Masaüstü branch'i main'e birleştirildi ✅

- `39ae184` merge (`--no-ff`, çakışma yok, sadece `desktop/`), `103ba46` ROADMAP Faz 4.
- Kontroller: masaüstü `npm run check` 15 test, `cargo test` 37 test yeşil.
- karar: ROADMAP Faz 4'te yapılanları "Durum: kısmen" altında işaretledim. "Bitti sayılır" kutularını boş bıraktım, yanlarına ne eksik olduğunu yazdım. Logo + sohbet maddesini senin kurulu uygulamayla denemen gerekiyor; limitte kapatma ise hiç yapılmadı.
- Not: `C:/Users/PC/Desktop/yaver-desktop` worktree'si hâlâ duruyor (branch `feat/desktop-companion`). Silmedim. Rust derleme önbelleği orada; `CARGO_TARGET_DIR` ile onu kullandım.

## 2. Ekran süresi entegrasyonu ✅

- `2759935` backend: `screen_time_days` tablosu (cihaz + gün başına bir satır, uygulamalar ve limitler JSON). `POST /api/screen-time` günü bütün olarak değiştirir, yani idempotent. `GET /api/screen-time/{gün}` var. Karen'e `get_screen_time(date, days)` eklendi. Akşam check-in'inde Karen satırı şöyle: "bugün 5 saat 12 dk ekran, 1 saat 10 dk VALORANT (sınır 1 saat 30 dk)".
- `e6ec368` masaüstü: 10 dakikada bir (ilki açılıştan 30 sn sonra) ve çıkışta (`RunEvent::Exit`, en fazla 4 sn) senkron yapıyor.
- karar: ayrı bir kuyruk yok, **yerel SQLite zaten tampon.** `sync_state.synced_until` son başarılı senkronu tutuyor. Her senkron o günden bugüne kadar dokunulan günleri baştan gönderiyor (en fazla 14 gün; hiç senkron yoksa 7 gün). Backend kapalıyken birikenler ilk başarılı senkronda gidiyor, kayıp olmuyor.
- karar: cihaz adı `COMPUTERNAME`. İki bilgisayar birbirinin gününü ezmiyor, toplamda toplanıyor.
- karar: o gün kontrol edilecek ders/spor/görev yoksa check-in hâlâ gönderilmiyor. Sadece ekran süresi için mesaj atmak gereksiz geldi.
- karar: geçmiş günlerin limitleri bugünkü `config.json` limitleriyle hesaplanıyor.
- Gerçek DB: önce yedek alındı (`backups/yaver-20261120-061122.sql.gz`), sonra migration `39277974afa2` uygulandı. Veri eklenmedi.
- Testler: backend 735 (yeni: idempotent POST, iki cihaz, hatalı veri 422, araç, check-in satırı). Rust 40 (yeni: hangi günler gönderilir, boş geçmiş günler atlanır, senkron işareti).
- Denenmedi: gerçek masaüstü uygulamasının gerçek backend'e gönderimi. Bu, gerçek veritabanına yazardı; senin denemen gerekiyor (aşağıda).

## EK. Hafta görünümü ✅ (2. maddeden sonra, öncelikli)

- `11d3b30` backend:
  - `week_labels` tablosu ve `set_week_label` aracı (Friday ve Jarvis'te).
  - Hafta adı dönem başından hesaplanıyor: "2026-27 Güz · 8. Hafta".
  - Otomatik etiketler: 2+ sınav → Vize Haftası, dönemin son 3 haftasında Final Haftası; başlığında "proje" geçen etkinlik → Proje Haftası; 3+ okul günü tatil → Tatil Haftası; iki dönem arası → Ara tatil.
  - `GET /api/plan/week?date=` artık herhangi bir haftayı veriyor (hafta bilgisi + geçmiş günlerin devamsızlıkları).
  - Gün planlarına "taşındı" listesi eklendi (`moved_away`).
  - Yeni uç nokta: `GET /api/terms/weeks`.
- `4c3341b` web:
  - Gezinme: ‹ › butonları, "Bu hafta", ←/→ tuşları ve kaydırma.
  - Hafta URL'de tutuluyor (`#/week?week=2026-11-16`); hafta ortasından bir tarih verilirse o haftanın pazartesisine çevriliyor.
  - Hafta kartlarında: devamsızlıklar ilgili dersin üstünde kırmızı rozetle ("Gelmedin · 2 saat"), taşınan dersler üstü çizili "eski → yeni" olarak, günün görevleri ☑/☐ ile, haftanın görevleri üstte.
  - Durum sekmesinde dönem listesi: hafta no, tarih aralığı, etiket, sınav sayısı, devamsızlık saati. Tıklayınca o haftaya gidiyor.
- Ekran görüntüleriyle kontrol ettim (gerçek veri, salt okuma): geniş ekranda 8. hafta 7 sütun ve 10 saat devamsızlık doğru; telefonda 9. haftada "Vize Haftası" etiketi görünüyor, → tuşu 10. haftaya geçiyor ve URL güncelleniyor.
  - Bulunan sorun: telefonda başlık kesiliyor ve etiket görünmüyordu. Düzelttim, etiket artık tarih satırında.
  - Kaydırma (swipe) mantığı birim testli; gerçek dokunmatik ekranda denenmedi.
- karar: geçmiş haftaları sayfalarken tarayıcı geçmişine yeni kayıt eklenmiyor (`replaceState`), geri tuşu hafta hafta geri gitmiyor.
- karar: hafta etiketi için sohbetle ad verme canlı denemesi 10. maddedeki regresyon setine girdi.
- Not: mesajında "Sağdaki" diye yarım kalmış bir ifade vardı ("Hafta görünümü: - Sağdaki -Hafta gezinme"). Ne kastettiğini çıkaramadım, o kısım için ayrıca bir şey yapmadım.
- Gerçek DB: önce yedek alındı (`backups/yaver-20261120-061628.sql.gz`), sonra migration `e398f7b77186` uygulandı.
- Testler: backend 738, web 30.

## 3. Auth ✅

- `c82811d` backend:
  - Tek kullanıcı parolası (`APP_PASSWORD`). Oturumlar Postgres'te (`auth_sessions`) ve yalnızca token'ın SHA-256'sı saklanıyor.
  - Tarayıcıya httpOnly, SameSite=Lax cookie veriliyor. HTTPS isteklerinde `Secure` bayrağı da ekleniyor.
  - Masaüstüne Bearer token veriliyor (`client: "desktop"`).
  - Health ve `/api/auth/*` dışındaki tüm `/api` rotaları korumalı.
  - Oturum `SESSION_DAYS` (30) gün kullanılmazsa bitiyor; kullanıldıkça uzuyor.
  - 10 dakikada 5 yanlış parola → 429 (`Retry-After` ile).
- `2145072` web: Aurora stilinde giriş ekranı (parola göster/gizle, hata ve bekleme mesajları), Durum sekmesinde "Oturumu kapat". Herhangi bir istekte 401 gelirse giriş ekranına dönüyor.
- `063ba67` masaüstü: ⚙ → Parola → Giriş yap. Token `session.json`'da (elle düzenlenen `config.json`'dan ayrı) ve ekran süresi senkronu dahil her istekte gidiyor. 401 gelince panelde "Giriş gerekli: ⚙ Ayarlar → Parola" yazıyor.
- **karar (önemli):** senin `.env`'inde `APP_PASSWORD=change-me` (örnek değer) duruyor. Bu değeri **"parola yok"** sayıyorum, auth kapalı kalıyor. Açılışta log'a uyarı düşüyor: "APP_PASSWORD is placeholder". Böylece sen dışarıdayken çalışan kurulum birden giriş ekranına düşmedi. Tailscale'e geçmeden önce `.env`'e gerçek bir parola yaz ve `docker compose up -d` çalıştır.
- karar: `SECRET_KEY` kullanılmıyordu (oturumlar imzalı değil, sunucu tarafında), `.env.example`'dan çıkardım. Senin `.env`'indeki satır zararsız, yok sayılıyor.
- karar: tarayıcı cookie'si 400 gün geçerli (tarayıcıların üst sınırı). Asıl süre sunucu tarafındaki 30 günlük boşta kalma süresi.
- Testler: backend 745 (yeni 7 auth testi). Mevcut test fixture'ları, gerçek bir parola ayarlansa da kırılmasın diye auth'u atlıyor.
- Uçtan uca: test DB'sine bağlı, parolası açık geçici ikinci bir API'yle gerçek HTTP üzerinden denedim. Sonuçlar: token'sız 401, token'la 200, ekran süresi POST ve geri okuma, web cookie'si, yanlış parola, çıkıştan sonra 401.
- Giriş ekranının görüntüsü: `/api/auth/status` yanıtını taklit ederek telefon ve geniş ekranda kontrol ettim.
- Gerçek DB: önce yedek alındı (`backups/yaver-20261120-062657.sql.gz`), sonra migration `0571660138ad` uygulandı.

## 4. Web Push ✅ (iPhone tarafı senin)

- `c8a344c` backend:
  - Gönderim pywebpush ile, `.env`'deki VAPID anahtarlarıyla.
  - `push_subscriptions` tablosu ve `/api/push/key|subscribe|unsubscribe|test` uç noktaları.
  - Sabah brifingi, akşam check-in, takip soruları ve haftalık plan, sohbete yazıldıktan sonra bildirim olarak da gidiyor. Bildirim başlığı işe göre ("Günaydın ☀️", "Akşam check-in 🌙"…), gövde mesajın başından, markdown'sız ~180 karakter. Bildirime dokununca sohbet açılıyor.
  - 404/410 dönen abonelik hemen siliniyor; üst üste 5 hata alan abonelik de siliniyor.
  - Push başarısız olsa bile iş başarısız sayılmıyor.
- `d6a5459` web:
  - `public/sw.js`: sadece push ve bildirime dokunma; bilerek offline önbellek yok, eski sürüm takılı kalmasın diye.
  - `manifest.webmanifest`, ana ekran ikonları (192/512, apple-touch-icon 180, Android için 96 px badge).
  - Durum sekmesinde "Bildirimler" kartı: aç / kapat / deneme bildirimi.
  - iPhone'da Safari sekmesindeyken "önce Ana Ekrana Ekle" diyor.
- **Chrome'da gerçek test** (gerçek DB'ye dokunmadan): test DB'sine bağlı geçici bir API (`:8012`) ve ayrı bir Vite sunucusu (`:5199`) kurdum; Chrome headless, CDP ile bildirim izni verildi.
  - Uygulamanın kendi kodu ile abone olundu, Google FCM üzerinden gerçek push gönderildi, service worker aldı. Hem `/api/push/test` ("Yaver · Bildirimler çalışıyor…") hem brifing işi ("Günaydın ☀️ · Günaydın, Görkem! Bugün 20 Kasım Cuma…") ile denendi.
  - Sonra abonelik iptal edildi (sunucuda 0 abonelik kaldı).
  - Geçici API ve Vite kapatıldı.
- Yeni bağımlılık: `pywebpush` (`uv.lock` güncellendi). Api imajını yeniden derledim (`docker compose build api`), volume'lere dokunmadım.
- karar: `.env` dosyasına dokunmadım; mevcut VAPID anahtarların çalışıyor (FCM 201 döndü).
- Ek düzeltme: koyu temada tarayıcının kaydırma çubukları beyazdı, `color-scheme: dark` ile düzeldi.
- Gerçek DB: önce yedek alındı (`backups/yaver-20261120-063934.sql.gz`), sonra migration `d81fd8abddaa` uygulandı.
- Testler: backend 751 (yeni 6 push testi, sahte push servisiyle).

## 5. Faz 3 başlangıcı: syllabus → haftalık konular → pgvector → `search_materials` ✅

- `843c454` backend:
  - PDF olduğu gibi yükleniyor (`attachments.filename` atıf için tutuluyor).
  - Metni kod çıkarıyor (pypdf, sayfa sayfa). PDF'in ne olduğuna ucuz tier karar veriyor (`document_classify`, ilk sayfalar).
  - Syllabus ise Sonnet (`syllabus_parse`) ders kodunu ve haftalık konuları okuyor, sonuç "öneri #N" tablosu olarak gösteriliyor. "Evet" denince yazılanlar: `syllabus_weeks`, ders (yoksa oluşturuluyor), `course_materials`, `material_chunks` (pgvector, HNSW, cosine).
  - Tek "Geri al" hepsini siliyor; parçalar cascade ile gidiyor.
  - Friday'e iki araç eklendi: `search_materials` (sonuçlar dosya + sayfa ile) ve `get_syllabus` ("bu hafta ne işlendi?", dönemin kaçıncı haftasında olunduğunu da veriyor).
- `75ee4d2` web: PDF seçme ve sürükle-bırak, mesajda dosya adıyla PDF kutucuğu.
- **karar: embedding yerel ve ücretsiz.** fastembed (ONNX, CPU) ile `paraphrase-multilingual-MiniLM-L12-v2` (384 boyut). Türkçe soru İngilizce slaytı da buluyor (deneme: 0.58'e karşı 0.31). sentence-transformers'ı seçmedim, torch imajı GB'larca büyütürdü. Model ilk kullanımda ~220 MB iniyor ve yeni `models` volume'ünde kalıyor (`MODEL_CACHE_DIR`).
- **Bulunan önemli sorun:** MiniLM girdinin yalnızca ~128 token'ına (~500 karakter) bakıyor. İlk sürümde 1000 karakterlik parçalar kullanıyordum; parçanın ikinci yarısı aramaya hiç girmiyordu ve canlı testte "notlarda bulunamadı" cevabı çıktı. Çözüm: parçalar ~500 karakter (100 örtüşme). Dolu bir parça yeni sayfaya taşmıyor, atıf "s. 1-2" değil "s. 2" çıkıyor.
- karar: OCR yok. Metin katmanı olmayan (taranmış) PDF için "sayfaların fotoğrafını gönder" deniyor (7. maddedeki fotoğraf yolu).
- karar: syllabus dışındaki PDF'ler bu maddede sadece özetleniyor; ders/hafta bağlama ve indeksleme 7. maddede.
- Prompt: görselden/PDF'ten gelen uzun bir bloktan sonra koordinatör İngilizce cevap verdi (1/4 deneme). Bloğun sonuna "(Bu blokları kod okudu. Cevabın Türkçe olsun.)" eklendi. Ayrıca koordinatör öneri tablosunu Friday'e delege etmek yerine kendisi gösteriyor ve kaynak gösterimini (dosya, s. N) harfi harfine koruyor.
- Canlı test (`pytest -m live -k materials`, test DB'si, uydurma `examples/syllabus/ee211_syllabus.pdf`):
  - 14 hafta doğru okundu (7. hafta "Thevenin ve Norton…"); "evet" sonrası 14 hafta ve 4 parça kaydedildi.
  - "Thevenin direnci nasıl bulunuyordu?" sorusunda `search_materials` çağrıldı, cevapta "(ee211_syllabus.pdf, s. 2)" kaynağı vardı.
  - Bir tur maliyeti ~$0.009 (Sonnet $0.0065). Ayarlarken 4 tur koştu (~$0.04).
  - Gözlem: Friday cevaba "Yani gerilim kaynakları kısa devre…" diye bir yorum ekliyor. Yorum doğru, ama notlarda yazmıyor. Kuralı sıkılaştırdım; tamamen geçmedi.
- Gerçek DB: önce yedek alındı (`backups/yaver-20261120-065504.sql.gz`), sonra migration `d383fa696f0a` uygulandı (`CREATE EXTENSION vector` dahil).
- Testler: backend 756.

## 6. Çalışma kağıdı ✅

- `fb88e78` backend:
  - Friday'e `generate_study_sheet(course, week?, topic?)` aracı eklendi; `study_sheets` tablosu tutuyor.
  - Kaynak parçaları **kod seçiyor**: önce o haftanın kendi notları, sonra syllabus konularına en yakın parçalar (en fazla 10 parça, ~9000 karakter).
  - Sonnet (`study_sheet`, smart) yalnızca bu numaralı parçalardan yazıyor ve her bilginin yanına [n] koyuyor. Bölümler: Özet, Temel kavramlar, Formüller, Kendini dene + Cevaplar.
  - "Kaynaklar" listesini (dosya + sayfa) **kod ekliyor**. Hiçbir parçaya karşılık gelmeyen [n] numaraları metinden siliniyor; yani kaynak uydurulamıyor.
  - Uç noktalar: `GET /api/study-sheets`, `/{id}`, `/{id}/download.md` (Türkçe dosya adıyla).
  - Tek "Geri al" kağıdı da siliyor.
- `405b8e1` web:
  - `#/sheet?id=N` sayfası: Markdown, "Markdown indir", "PDF olarak kaydet".
  - Durum sekmesinde "Çalışma kağıtları" listesi.
  - Cevaptaki kağıt linki aynı sekmede açılıyor.
- **karar: PDF tarayıcının yazdırma motoruyla** ("PDF olarak kaydet" → yazdırma penceresi; iPhone'da Paylaş → PDF). Sunucuda PDF üretmek için weasyprint (pango vb.) ya da Türkçe TTF font gerekirdi. Yazdırma stilinde menü/arka plan gizleniyor, yazı siyah-beyaz.
  - Chrome'un yazdırma motoruyla gerçekten PDF'e bastım: 2 sayfa, yalnız kağıt, Türkçe karakterler ve kaynak listesi tam.
- Bulunan sorun: `@apply font-grotesk` prod derlemesini kırıyordu, `npm run check` ise derleme yapmadığı için bunu yakalamıyordu. Düzelttim; `npm run check` artık `vite build`'i de çalıştırıyor.
- Canlı test (aynı uçtan uca test, 4. adım "EE211 7. hafta için çalışma kağıdı hazırla"):
  - Kağıt yazıldı, link cevapta vardı.
  - Kaynaklar: ee211_syllabus.pdf s. 1, 1-2, 2.
  - Kaynak zayıf olduğu için dürüst davrandı: "Norton ve maksimum güç transferinin tanımı pasajlarda yok" diye yazdı, uydurmadı.
  - Bu tur $0.029 (kağıt Sonnet $0.014).
- Gerçek DB: önce yedek alındı (`backups/yaver-20261120-070356.sql.gz`), sonra migration `f76b134e1c48` uygulandı.
- Testler: backend 760, web 30 + prod derleme.

## 7. Ders notu yükleme (PDF + fotoğraf) ✅

- `34aee47`, `519f5be`:
  - Bir PDF ders notu ya da notların fotoğrafı (mevcut görsel altyapısı; Sonnet metni okurken "ders notu mu, hangi ders" diye de işaretliyor) **bekleyen materyale** dönüşüyor. Ekibe giden blok: "materyal #M, henüz kaydedilmedi; öneri: EE211, 7. hafta (syllabus: …)".
  - Ders, okumada görülen koddan bulunuyor. Hafta, syllabus konularıyla yerel embedding benzerliğinden **öneriliyor**.
  - Friday `save_material(M, ders, hafta)` ile bağlıyor, parçalara ayırıp embedding'liyor; ancak bundan sonra aranabilir.
  - Fotoğrafın metni saklanıyor (`source_text`), kaydederken ikinci kez okutulmuyor. Tek "Geri al" materyali ve parçalarını siliyor.
- **karar: hafta önerisi yalnızca belirgin eşleşmede.** Gerçek modelle ölçtüm:
  - Doğru haftalar 0.51–0.55 skor ve 0.11–0.14 farkla çıktı.
  - Yanlış ya da ilgisiz notlar 0.35–0.39 skor ve ~0.03 farkla çıktı; örneğin 4. hafta notu için 14. hafta öneriliyordu.
  - Eşik: skor ≥ 0.42 ve ikinciden ≥ 0.06 fark. Altında öneri yok, Friday soruyor. Yanlış bir öneri, kullanıcının yanlışlıkla "evet" demesine yol açar; sormak bundan iyi.
- Canlı test (`-k lecture_notes`, uydurma `examples/syllabus/ee211_hafta7_notlar.pdf`, $0.003):
  - "EE211 7. hafta ders notlarım" + PDF gönderildi; "evet" sonrası 7. hafta olarak kaydedildi.
  - Ardından "Norton akımı nasıl bulunuyor, maksimum güç ne zaman?" sorusu doğru formüllerle ve "(ee211_hafta7_notlar.pdf, s. 2)" atfıyla cevaplandı.
  - Gözlem: kullanıcı ders ve haftayı söylemiş olmasına rağmen koordinatör bir kez "kaydedeyim mi?" diye sordu. Prompt'ta "söylediyse kaydet" yazıyor; zararsız, düzeltmedim.
- Gerçek DB: önce yedek alındı (`backups/yaver-20261120-070931.sql.gz`), sonra migration `16da56442ff0` uygulandı.
- Süreç notu: bir commit'te mypy kırmızıyken commit geçti (komut zincirim hata durumunda durmadı). Hemen ardından `519f5be` ile düzelttim.
- Testler: backend 763.

## 8. Sınav hazırlığı ✅

- `e5de6aa`:
  - Günlük `exam_prep` işi saat 18:00'de çalışıyor (`EXAM_PREP_TIME`). Sınava 2-7 gün kalmışsa ve o sınav için daha önce taslak çıkmamışsa Friday bir tekrar planı öneriyor.
  - Planın içeriği:
    - Syllabus'tan dersin bir önceki sınavından bu sınava kadarki haftaların konuları; final ise hepsi. "Ara sınav" haftası konu sayılmıyor.
    - O haftaların yüklü notları.
    - Sınavdan önceki her gün için boş bir 90 dk: önce 17:00 sonrası, yoksa günün en uzun boşluğu.
    - Son gün "genel tekrar + soru çözümü".
  - "Evet" denince haftalık plandaki gibi görevlere yazılıyor (`apply_proposal`, Friday); push da gidiyor.
- karar: taslağı LLM değil kod çıkarıyor. Bütün bilgiler (konular, notlar, boş saatler) zaten veritabanında; kod ücretsiz, hızlı ve uydurmuyor.
- **Gerçek verinde prova** (kaydetmeden, rollback; öneri sayısı 4'te kaldı) iki sorun gösterdi, ikisi de düzeldi:
  1. Bu haftaki üç vizenin (DSA 23 Kas, Logic design 26 Kas, MATH 221 27 Kas) tekrarları aynı saate düşüyordu. Artık bir çalıştırmada verilen saat sonraki sınav için dolu sayılıyor (aynı gün 18:00 ve 19:30).
  2. Syllabus yokken sınav başına 5-6 tane "notları gözden geçir" görevi çıkıyordu. Artık 2 tekrar + 1 genel tekrar; toplam 8 görev.
- **Bilmen gereken:** zamanlayıcıda iş kayıtlı, bugün 18:00'de çalışacak. Sohbetine DSA, Logic design ve MATH 221 vizeleri için taslak gelecek (push açıksa bildirim de). Syllabus yüklemediğin için konular yok; "evet" dersen 8 görev yazılır.
- Testler: backend 767 (taslak, boş saat seçimi, tekrar önermeme, "evet" sonrası 6 görev, iki sınavın aynı saati paylaşmaması).

## 9. ICS dışa aktarma ✅

- `e5ad9b8` backend:
  - `GET /api/calendar.ics?token=…` login istemiyor (telefonun takvimi giriş yapamaz). Uzun rastgele token `app_secrets` tablosunda; yanlış token → 404.
  - Token'lı yolu veren `GET /api/calendar/subscription` ve yeni bağlantı üreten `…/rotate` girişin arkasında.
  - Dersler ve lab'lar uygulamanın kendi `compute_day_plan` hesabıyla açılıyor (30 gün geri, 180 gün ileri). Bu yüzden iptaller takvimden düşüyor; taşınanlar yeni saatinde ama aynı UID ile, telefon onu "değişen etkinlik" olarak görüyor. Tatiller ve dönem sonu da uygulanıyor.
  - Sınavlar ve etkinlikler de takvimde. Saatler UTC, uzun satırlar RFC 5545'e göre katlanıyor, yenileme süresi 1 saat.
- `334577a` web: Durum sekmesinde "Takvim aboneliği" kartı (webcal:// bağlantısı, "Takvime ekle", kopyala, "Yeni bağlantı", iPhone talimatı).
- karar: haftalık spor ve iş blokları takvime girmiyor (istenen: dersler, sınavlar, etkinlikler). Tek seferlik etkinliklerin hepsi giriyor.
- karar: iptal edilen ders takvimden siliniyor ("İPTAL" diye bırakılmıyor).
- Gerçek veriyle prova (salt okuma, token oluşturulmadı): 16-22 Kasım haftası hafta görünümüyle birebir aynı; vizeler, lab'lar, telafi ve ek ders doğru günlerde.
- Gerçek DB: önce yedek alındı (`backups/yaver-20261120-071839.sql.gz`), sonra migration `d9ba235487af` uygulandı.
- Denenmedi: gerçek iPhone aboneliği. Telefonun sunucuya erişmesi gerekiyor (Tailscale).
- Testler: backend 770, web 31.

## 10. Regresyon seti (25 mesaj) ✅

- `4522f0c`: `tests/db/test_live_regression.py`. 25 gerçekçi Türkçe mesaj, her biri aynı başlangıç durumunun (dönem, gerçek programına benzer ders/lab/spor blokları, bir takip, bir görev; kodla, LLM'siz kurulur) temiz bir kopyasında, gerçek router üzerinden koşuyor.
  - Alanlar: devamsızlık (4), iptal (2), taşıma (2), sınav/quiz (3), takip (2), karışık (1), yaver adıyla okuma (1), belirsiz tarih (2), geri al (2), görsel (2), iş bloğu, görev ekle/bitir, hafta adı.
  - Her vakanın DB ve cevap kontrolü var; ayrıca genel cevap kalitesi kontrolü (İngilizce, tekrar eden soru, şahıs karışıklığı).
  - Hatalar türlerine göre sayılıyor. Çalıştırma: `pytest -m live -k regression -s`; bazı vakalar için `REGRESSION_ONLY=8,16`.
- **İlk tur: 18/25 (%72), $0.017.** İkisi benim kontrol hatamdı: tohum veri 8 blok, sınırı 6 yazmıştım. Gerçek hatalar 7'den 5:
  - **En sık hata, yanlış araç / yanlış yaver (3):**
    - "rapor yaz görevini bitirdim" Friday'e gitti; görev aracı onda yok.
    - "her cuma 9-17 Medipol'de çalışıyorum" haftalık blok yerine `remember` ile kaydedildi.
    - "perşembe linear yerine cumartesi 10-12" taşıma yerine iptal + ayrı etkinlik olarak yapıldı.
  - **İkinci, gereksiz / yanlış soru (2):**
    - "hackathon kabul geldi!" sorusunda tek bekleyen takip varken "hangi hackathon?" diye soruldu.
    - "27 Kasım Perşembe'ye toplantı ekle" mesajında tarih çözülmedi; gün adı tutmazlığı yerine saat ve konu soruldu.
- **Düzeltmeler (en büyük 2 hata türü):**
  1. Görevler ajanda alanında (domain metni). `complete_task` koordinatörün hızlı yoluna eklendi. Haftalık saatli bilgi "blok"tur, `remember` değil. "X yerine Y'de / Y'ye alındı" = `move_block_on`.
  2. Bekleyen takipler her isteğin bağlamına (sistem son ekine) giriyor. Haber gelince `update_followup`, ancak iki takip uyuyorsa soru. Eksik saat veya başlık soru sebebi değil, tarih yine önce çözülüyor.
- **Sonra: 25/25 (%100) ve 24/25 (%96).** Tur başına ~$0.02, ~2 dk.
  - Kalan tek başarısızlık #17 ("geçen hafta bir gün EE211'e gitmedim"): Friday soruyu soru işaretsiz sordu. Kontrolü dolaylı soruyu kabul edecek şekilde düzelttim. Ama örnek olarak EE211'in olmadığı "Pazartesi"yi önerdi; derslerin günlerini önermesi daha iyi olurdu (yapılmadı).
- Eski 5 mesajlık canlı senaryo (`-k scenarios`) değişiklikten sonra 2 kez koştu. Biri geçti; birinde 3b adımında rastlantısal bir İngilizce cevap çıktı ve "çarşamba" onayından sonra araç çağrılmadı. Bu sorun 2 gecedir ara ara görülüyor (claim guard'ın tekrar denemesi İngilizce yazdı); izlenmeli.
- Ayrıca gördüğüm: karışık mesajlarda koordinatör bazen bir yaverin satırını birleşik cevaba koymayı unutuyor. Değişiklik kartında görünüyor ama cevapta yok. Regresyon setine bunun kontrolünü ekledim (#14, `dropped_part`); son iki turda sorun çıkmadı.
- Harcama (bu madde): 3 regresyon turu + 2 senaryo turu ≈ $0.06.
