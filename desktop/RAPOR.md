# Masaüstü arkadaşı — gece raporu (20 Kasım 2026)

Branch: `feat/desktop-companion` (worktree). Push yok. Sadece `desktop/` değişti; backend, web, docker ve veritabanına dokunulmadı.

## Durum

| Commit | Ne |
|---|---|
| `59fe762` | Tauri v2 iskeleti: şeffaf, hep üstte, sürüklenebilir yuvarlak logo; konum hatırlanıyor |
| `496c25f` | Mini sohbet paneli (`POST /api/chat`), yaver etiketi + renk, **Geri al**, sunucu adresi ayarı |
| `4fafed0` | Windows oturum açılışında otomatik başlatma (varsayılan kapalı) + tepsi menüsü + tek instance |
| `8c2eb21` | Ekran süresi (yerel SQLite), paneldeki günlük özet, uygulama limiti uyarıları (%80 / %100, kapatma yok) |
| (son) | `README.md` + bu rapor |

Testler: Rust'ta 37 test, frontend'de 15 test (vitest). `clippy -D warnings`, `rustfmt`, `tsc`, `eslint` temiz.

Kurulum dosyası: `desktop/src-tauri/target/release/bundle/nsis/Yaver_0.1.0_x64-setup.exe` (gitignore'da; komutla yeniden üretilir: `npm run tauri build`).

## Kararlar (gerekçeleriyle)

1. **HTTP isteklerini Rust yapıyor, webview değil.** Backend CORS başlığı göndermiyor, webview'in origin'i de `http://tauri.localhost`. Webview'den `fetch` yapılsa engellenirdi. Backend'e dokunmamak için istekler `reqwest` ile Rust'tan gidiyor. Hata kodları (`unreachable`, `timeout`, `http`…) panelde Türkçe mesaja çevriliyor.
2. **Akışsız `/api/chat` kullanılıyor.** Görevde bu istenmişti. Cevap tek seferde geliyor, beklerken "Düşünüyor…" yazıyor; zaman aşımı 300 sn. SSE (`/api/chat/stream`) sonraki adım olabilir.
3. **Frontend framework'süz, vanilla TS.** Üç küçük pencere (logo, panel, uyarı balonu) için React gereksiz ağırlık olurdu. Mantık saf modüllerde (`chat/model.ts`, `screen/model.ts`) ve testli. Metinlerin hepsi `src/i18n/tr.ts`'de, Rust tarafındakiler (tepsi menüsü, uyarı metinleri) kendi `tr` modüllerinde.
4. **Cevaplar düz metin olarak gösteriliyor** (markdown işlenmiyor, `**kalın**` olduğu gibi görünür). Güvenli (`textContent`) ve basit. Gerekirse küçük bir markdown işleyici eklenebilir.
5. **Config, `%APPDATA%\com.yaver.desktop\config.json`.** Uygulama bu dosyayı **oku-değiştir-yaz** ile güncelliyor: logoyu sürükleyince sadece `bubble_position` değişiyor. Elle eklediğin limitler hiçbir zaman ezilmiyor. Bozuk JSON'a hiç yazılmıyor; uygulama son geçerli ayarlarla devam ediyor ve hatayı panelde gösteriyor. Dosya dakikada bir yeniden okunuyor, yeniden başlatma gerekmiyor.
6. **Ekran süresi oturum (session) olarak saklanıyor, örnek olarak değil.** 5 sn'lik örnekler aynı uygulama sürdükçe tek satırı uzatıyor (günde 17 bin satır yerine birkaç yüz). Örnekler arasında 15 sn'den uzun boşluk (uyku, kapanma) sayılmıyor. Tablo adı ROADMAP'teki gibi `screen_sessions`; ileride backend'e aynı şekliyle gönderilebilir.
7. **Boşta kalma kuralı:** 5 dk klavye/fare girdisi yoksa süre sayılmıyor (`idle_minutes`). **Limiti olan uygulamalar boşta sayılmıyor**, çünkü Windows gamepad girdisini görmüyor ve bir oyun ekrandaysa oynanıyordur. Yan etki: girdi olmadan izlenen video (YouTube) 5 dk sonra sayılmayı bırakıyor.
8. **Pencere başlıkları kaydedilmiyor**, sadece exe adı ve uygulamanın açıklaması ("Google Chrome") tutuluyor. Başlıklarda sohbet adları ve sekme başlıkları gibi kişisel bilgiler olur. Veri yerelde de olsa gerek yok.
9. **Sahipleri farklı süreçler:** UWP uygulamaları (Ayarlar, Hesap Makinesi…) `ApplicationFrameHost.exe` içinde çalışıyor; gerçek uygulama alt pencereden bulunuyor. Açılamayan korumalı süreçlerin (anti-cheat olabilir) adı süreç anlık görüntüsünden (Toolhelp) alınıyor.
10. **Uyarılar günde bir kez:** her seviye (80/100) gösterildiğinde SQLite'taki `limit_alerts`'e yazılıyor; uygulama yeniden başlasa da tekrar etmiyor. Uygulama limit zaten aşılmışken açılırsa sadece %100 uyarısı çıkıyor.
11. **Uyarı iki yoldan gidiyor:** logonun üstünde bir balon (odak çalmaz, 20 sn sonra kaybolur, tıklayınca panel ekran süresi sekmesinde açılır) ve bir Windows bildirimi. Bildirimin sebebi şu: tam ekran oyun balonu örtebilir, bildirim ise Bildirim Merkezi'nde kalır.
12. **Gün sınırı bilgisayarın yerel saatine göre** (Türkiye'de backend'in `APP_TIMEZONE`'u ile aynı). Zamanlar SQLite'ta UTC unix saniyesi olarak tutuluyor.
13. **Otomatik başlatma varsayılan olarak kapalı**, tepsiden veya ⚙'den açılıyor (`HKCU\...\Run`). **Tek instance:** ikinci kez açılırsa çalışan uygulamanın sohbeti öne geliyor, ikinci bir logo çıkmıyor.
14. **Pencerelerin görev çubuğunda yeri yok**, kapatmak tepsiden yapılıyor. Alt+F4 sadece gizliyor.

## Gece denenenler

- Logo sağ altta şeffaf görünüyor; tıklayınca panel logonun soluna, alt kenarları hizalı açılıyor (koyu tema).
- Uçtan uca limit testi: geçici 1 dakikalık bir "TEST" limitiyle %80 ve %100 uyarıları doğru sırayla birer kez çıktı. Balon ve Windows bildirimi göründü; balona tıklayınca panel ekran süresi sekmesinde açıldı ("Google Chrome 1 dk", TEST limiti kırmızı). Balondaki uzun metin kesiliyordu, yüksekliği artırıldı.
- Testten sonra test verisi silindi (`screen_time.sqlite3`, log). Ekran görüntüleri ekrandaki diğer pencereleri de içerdiği için silindi.
- Backend'den sadece `GET /api/team` okundu, o da salt okuma. **Sohbet mesajı gönderilmedi**: veritabanına yazar ve LLM harcar. Gerçek sohbeti sen deneyeceksin.

## Sabah denemen gerekenler

1. **Kurulum:** `desktop/src-tauri/target/release/bundle/nsis/Yaver_0.1.0_x64-setup.exe`'yi çalıştır. Ya da geliştirme modunda: `cd desktop && npm install && npm run tauri dev`.
2. **Logo:** Sürükle; bırakınca yerinde kalmalı. Uygulamayı kapatıp açınca aynı yerde başlamalı. Tek tıklama paneli açıp kapatmalı.
3. **Sohbet:** Docker ayaktayken bir mesaj yaz ("yarın ne var?"). Cevapta yaver adı/rengi doğru mu? Değişiklik yapan bir mesajda "1 değişiklik · Geri al" çıkıyor mu, Geri al çalışıyor mu? (Bunlar gerçek veriye yazar.)
4. **Sunucu adresi:** ⚙ → *Bağlantıyı dene* "Bağlandı: Yaver, Friday, …" demeli. Docker kapalıyken "Sunucuya ulaşılamadı" mesajı çıkmalı.
5. **Otomatik başlatma:** Kurulu uygulamadan aç (dev modundan açarsan debug exe kaydedilir), oturumu kapat-aç. Tepsideki onay işareti ile ⚙'deki kutu aynı durumu göstermeli.
6. **Ekran süresi:** Biraz kullandıktan sonra saat sekmesi. Uygulama adları mantıklı mı? Yerel `config.json`'a **VALORANT 90 dk** limitini ekledim (`VALORANT-Win64-Shipping.exe`, `VALORANT.exe`). Oyunda exe adını Görev Yöneticisi → Ayrıntılar'dan kontrol et.
7. **VALORANT'ta asıl soru:** tam ekranda balon üstte görünüyor mu, Windows bildirimi geliyor mu? Windows'un "Oyun oynarken" odak yardımı (Focus Assist / Rahatsız Etmeyin) bildirimleri bastırıyor olabilir. Hızlı deneme için `daily_minutes`'ı 2 yap; dosya 1 dk içinde yeniden okunur. Aynı gün aynı limit adıyla uyarı tekrar çıkmaz, denemede farklı bir `name` kullan.
8. **Çoklu monitör / %125–150 ölçek:** logoyu ikinci ekrana taşı, panel ve balon ekran dışına taşmamalı. Bunu deneyemedim; testteki ekran tekti ve ölçek %100'dü.

## Bilinen eksikler / sonraki adımlar

- **Process kapatma ve "pazarlık"** (ROADMAP Faz 4) bilerek yapılmadı. %100'de 2 dk geri sayım ve kapatma, `limits.rs`/`screentime::due_warnings`'in yanına eklenecek.
- **Backend entegrasyonu:** `screen_sessions`'ı backend'e senkronlamak, `set_app_limit` aracının (`backend/app/agent/tools/__init__.py`'de "Faz 4" olarak işaretli) limitleri yazması, günlük raporun brifinge girmesi.
- **Sohbet:** SSE akışı, markdown, görsel ekleme, konuşma geçmişini sunucudan yükleme. Şu an sadece son konuşmanın id'si hatırlanıyor, mesajlar uygulama yeniden açılınca boş başlıyor.
- **Proaktif balon mesajları** (brifing, hatırlatma): balon penceresi (`notice.rs`) hazır, içerik kaynağı yok.
- **macOS:** ön plan örneklemesi şimdilik sadece Windows (`foreground.rs` macOS'ta `None` döner).
- **Saklama:** `screen_sessions` sınırsız büyüyor (ama küçük: günde birkaç yüz satır). İleride eski günler özetlenebilir.
- **ROADMAP.md** bu worktree'de güncellenmedi (görev `desktop/` dışına dokunmamaktı). Faz 4'te "Logo masaüstünde duruyor, sohbet açılıyor" maddesi senin denemenden sonra işaretlenebilir.
