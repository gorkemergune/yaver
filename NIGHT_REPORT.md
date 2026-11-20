# Gece raporu — 19/20 Kasım 2026

Kuyruğun tamamı bitti, hiçbir madde atlanmadı. 15 commit var, push yapılmadı. Her maddeden sonra container içinde `ruff`, `mypy` ve `pytest`, web container'ında da `tsc`, `eslint` ve `vitest` yeşil. Son durum: backend 730 test, frontend 24 test.

**LLM harcaması: yaklaşık $0.13** (sınır $0.50).
- Devamsızlık canlı testi, 15 tur: ~$0.08
- Ana senaryolar, 6 tur: ~$0.025
- Haftalık plan (Sonnet), 1 tur: ~$0.03. Bu tahmin; testte maliyet basılmadı.
- Ses (Whisper), 1 tur: $0.0003

Canlı testlerin hepsi `yaver_test` veritabanında çalıştı.

**Gerçek verine dokunduğum yerler.** Uygulama yeni kodla çalışabilsin diye 3 şema migration'ını gerçek veritabanına uyguladım. İlk ikisinden önce yedek aldım; üçüncüsü (`dc85dc3660d4`) yalnızca bir CHECK kısıtı ve ondan hemen önceki yedeğe dayanıyor. Bunun dışında hiçbir kayıt eklemedim, silmedim. Silmeye en yakın işlem, kendi açtığım deneme veritabanlarını (`yaver_restore_test*`, `yaver_premigration_check`) kaldırmaktı.

## Durum

| # | Madde | Durum | Commit'ler |
|---|---|---|---|
| 1 | Yedekleme | ✅ | `fafcb2a` |
| 2 | time_resolver: gün adlı tarihler | ✅ | `2233fb2` |
| 3 | Hafta/Bugün metin taşması | ✅ (önceki turda yapılmıştı, doğrulandı) | `279b4b4` |
| EK | Devamsızlık düzeltmesi | ✅ | `f4a67a7` `ccf1b27` `1392caa` `2f12853` `09b007f` `e0f97c9` |
| 4 | Tasarım: Aurora + B'nin balonsuz cevapları | ✅ | `173fd05` |
| 5 | ROADMAP Faz 1'e akşam check-in | ✅ (önceki turda yapılmıştı) | `564f1f7` |
| 6 | Faz 1: scheduler, brifing, check-in, takip | ✅ | `2843ea9` `5695c94` |
| EK-5 | Pazar haftalık planlama | ✅ | `0bb5431` |
| EK-6 | Sesli mesaj (Groq Whisper, bas-konuş) | ✅ (gerçek mikrofonla denenmedi) | `9545d10` `53409d2` |
| EK-7 | Smoke test, hızlı testler, README | ✅ | `fe33199` |

## 1. Yedekleme ✅

- **Otomatik yedek:** API her açılışta son yedeğe bakar; 24 saatten eskiyse `backups/yaver-YYYYMMDD-HHMMSS.sql.gz` alır ve en yeni 14 tanesini tutar.
- **Scriptler:** `scripts/backup.ps1` ve `scripts/backup.sh` üç komut sunar: `backup`, `list`, `restore`.
- **Restore koruması:** Restore varsayılan olarak ayrı bir veritabanına (`yaver_restore`) yazar. Canlı veritabanına ancak `-Yes` / `--yes` ile yazar.
- **Belgeler:** README ve `docs/tr/yedekleme.md` "`down -v` verini siler" uyarısını içeriyor.
- **Doğrulama:** Gerçek yedeği bir deneme veritabanına açtım. 9 tablonun satır sayıları ve Alembic sürümü canlıyla birebir aynıydı. Yedeği dolu veritabanının üzerine tekrar yükleyince de çift kayıt oluşmadı. Hem bash hem ps1 ile denendi.
- **karar:** Döküm ve sıkıştırma db container'ının içinde yapılıyor, dosya `docker compose cp` ile dışarı alınıyor. PowerShell pipe'ları ikili veriyi bozabiliyor.
- **karar:** Dosya adlarındaki saat UTC; API ve scriptler bu sayede tutarlı.
- **karar:** api imajına `postgresql-client-16` resmi PostgreSQL deposundan kuruldu. Debian trixie 17 sürümünü getiriyor; istemci sunucuyla (16) aynı sürümde olmalı.

## 2. time_resolver ✅

- **Desteklenen biçimler:** "27 Kasım Cuma", "Cuma 27 Kasım", "cuma, 27 kasım", "27.11 Cuma" ve "cuma 27/11" çözülüyor. "27.11" ve "27/11" zaten çalışıyordu.
- **Gün adı uymazsa:** `ambiguous` (`WEEKDAY_MISMATCH`) döner, adaylar yazılan tarih ve o gün adına en yakın gündür. Örnek: "28 Kasım Cuma" → 27 Kasım Cuma mı, 28 Kasım Cumartesi mi?
- **karar:** Gün adı yalnızca doğrulama yapar ya da açık kalan yılı seçer ("19 Mayıs Salı"). Tarihi asla başka bir yıla çekmez; 28 Kasım 2025 bir Cumaydı, ama "28 Kasım Cuma" bunu seçmez.

## EK: Devamsızlık düzeltmesi ✅

1. **Veri modeli:**
   - Kayıtlar artık blok bazında: (ders, tarih, blok) tekil ve `hours` alanı ders saatini tutuyor.
   - Limitler saat cinsinden.
   - Yaver öncesi devamsızlıklar ayrı bir tabloda (`attendance_baselines`); özetlerde ayrı satır olarak görünüyor.
2. **Kayıt:** "X tarihinde gitmedim" o günün tüm bloklarını yazıyor. Cevapta tarih tarih saat dökümü ve toplam var. Aynı mesaj tekrar gelirse sayı değişmiyor.
3. **Friday'in yeni araçları:** `list_attendance`, `delete_attendance`, `set_attendance_baseline`.
4. **Tarih doğrulama:** Gelecek tarih ya da o dersin olmadığı bir gün gelirse en yakın geçmiş ders günü öneriliyor ("22 Kasım Pazar → 19 Kasım Perşembe"). Tatiller ve iptaller hesaba katılıyor.
5. **Koordinatör:** Açık onaydan sonra tekrar sormuyor. Bir iş için araç yoksa "şu araç eksik" diyor, soruyu sana geri atmıyor. Hitap her zaman "sen".
6. **Migration (`c6f6a0cbe462`):** Mevcut gün bazlı kayıtları blok bazına dönüştürüyor; ileri ve geri yön testli. Gerçek verinde 11 kayıt vardı, 11 blok kaydına dönüştü. Migration öncesi yedekle satır satır karşılaştırdım; hepsi doğru.
7. **Canlı senaryo:** Konuşmanın birebir aynısı kullanıldı. Sonuç MATH 221 = 8, CSE 221 = 7, TKL 201 = 2, EE 211 = 2 saat ve tekrar gönderilince değişmiyor. Son 4 tur art arda yeşil.

Gece bulunup düzeltilen hatalar:
- **Araçsız "kaydetti":** Koordinatör, geçmişteki "kaydettim" cevaplarını taklit edip hiç araç çağırmadan "Friday kaydetti" diyordu; EE 211 0 saatte kaldı. Artık kod bunu yakalıyor: değişiklik iddiası ya da değişiklik isteği varken hiç araç çalışmadıysa mesaj bir kez daha çalıştırılıyor. Not sistem ekine konuyor ve kendi başına anlamlı istekler geçmiş olmadan tekrar deneniyor.
- **Gereksiz "hangisini kastettin?" sorusu:** Model "12 19 kasım" listesini belirsizlik sanıyordu. `resolve_date` artık listenin ayrı günler olduğunu ve hepsine uygulanması gerektiğini açıkça yazıyor.
- **Çift spor bloğu:** Friday bağlamdaki sporu da ekledi, Karen de ekledi ("Spor" / "spor"). Aynı saat ve türdeki blok artık bir kez yazılıyor.
- **Gereksiz bitiş saati sorusu:** Jarvis toplantının bitiş saatini sordu. Araçların boş bırakılmasına izin verdiği ayrıntılar artık soru sebebi değil.

Kararlar:
- **karar:** `courses.absence_limit` sütununun adı değişmedi; artık saat olarak okunuyor. Mevcut 8/10/5 değerlerin saat gibi duruyor.
- **karar:** Ders saati = süre/60, yuvarlanıyor, en az 1. Telafi etkinlikleri sayılmıyor, yalnızca bloklar sayılıyor.
- **karar:** Birden fazla tarihte geçerli günler yazılıyor, sorunlu gün öneriyle soruluyor.
- **karar:** "12 19 kasım" geçmiş kayıtta iki ayrı gün sayılıyor; planlamada aralık için "28-29" yazımı geçerli.
- **karar:** `log_attendance` koordinatörün hızlı yolundan çıktı. Devamsızlık her zaman Friday'e gidiyor, çünkü saat kuralları onun prompt'unda.

**Senin verinde dikkat:** CSE 221'in 19 Kasım kaydı eski sistemde hiç yazılmamış. Bu yüzden CSE 221 şu an 5 saat görünüyor, beklenen 7 değil. Ben eklemedim.

## 4. Tasarım ✅

- **Görünüm:** Aurora uygulandı. Koyu tema öncelikli: hiç seçim yapılmamışsa koyu; açık ve sistem seçenekleri duruyor. Arka planda süzülen renk alanları, cam başlık, kartlar ve giriş alanı; telefonda yüzen cam sekme çubuğu.
- **Yaverler:** Her yaverin kendi rengi ve ikonlu bir küresi var (pusula, kep, takvim, alev). Cevaplar B'deki gibi balonsuz.
- **Hareket:** Konuşanın renginde "yazıyor" noktaları, kart girişleri. Bugün görünümünde nabız atan "şu an" çizgisi.
- **Karşılama:** Kişisel karşılama başlığı ("İyi akşamlar, Görkem").
- **`/design-preview`:** "Yeni" (uygulanan) ilk sırada; A ve B karşılaştırma için duruyor.
- **karar:** Küre avatarlar A'dan, balonsuz cevap stili B'den alındı. İkonlar yaver id'sine göre seçiliyor.

## 6. Faz 1 başlangıcı ✅

- **Zamanlayıcı:** APScheduler 3, işleri PostgreSQL'de tutuyor (`apscheduler_jobs`; Alembic bu tabloyu yok sayıyor).
  - Saatler: 08:00 brifing, 21:00 check-in, 12:00 takip, Pazar 20:00 haftalık plan.
  - Bilgisayar kapalıyken kaçan iş, açılınca penceresi içindeyse çalışıyor.
  - `job_runs` her işi günde bir mesajla sınırlıyor.
- **Brifing:** Dersler, 14 gün içindeki sınav geri sayımı, limite yaklaşan devamsızlık, ajanda, spor, görevler, iptaller ve tatiller. Dünkü check-in cevapsız kaldıysa bir kez hatırlatıyor.
- **Check-in:** Dersler "katıldı" sayılıyor; spor ve görevler soruluyor. Sohbette "✓ Hepsi tamam" ve "Düzenle" butonları var. Boş günde check-in gönderilmiyor.
- **Takip:** Vadesi gelen takipler soruluyor ve bir sonraki soru zamanı ileri alınıyor.
- **Arayüz:** Zamanlayıcı mesajları etiketli ve ayrı birer öğe. Sohbet, pencereye dönüldüğünde ve dakikada bir yenileniyor.
- **karar:** Brifing, check-in ve takip mesajları LLM'siz, şablonla üretiliyor. Ücretsiz, çevrimdışı çalışıyor ve rate limit'e takılmıyor.
- **karar:** Mesajlar en son sohbete yazılıyor; hiç sohbet yoksa yeni biri açılıyor.
- **karar:** `on_date` kuralındaki takip, o tarihten itibaren her gün soruluyor.
- **karar:** "✓ Hepsi tamam" sohbete normal bir mesaj olarak gidiyor, yani yazma işini yine ekip yapıyor. Spor kaydı için henüz araç yok (`log_workout` Faz 1'de); koordinatör bunu tek cümleyle söylüyor.
- Tailscale, iPhone push ve auth yapılmadı; bunlar sende.

## EK-5. Haftalık planlama ✅

- **Taslak:** Pazar 20:00'de smart tier (Sonnet; bütçe koruması geçerli) yalnızca verilere bakarak görev taslağı yazıyor. Verilen veriler: haftanın planı, sınavlar, devamsızlık, takipler, mevcut görevler. Hafta dışına düşen tarihler atılıyor.
- **Onay:** Taslak bir öneri; sohbette tablo olarak görünüyor, "evet" ile tek change_set olarak görevlere yazılıyor.
- **Canlı deneme:** Sonnet, Cuma sınavı etrafında makul bir hafta çıkardı: hazırlığı önceki günlere yaydı, MATH 221 devamsızlığı için uyardı, hackathon takibini ekledi.
- **Geçmiş:** Pazartesi brifingi artık Pazar'ın taslağını geçmişten silmiyor.
- **karar:** Öneri numarası mesajın gizli `context` alanında; modele gidiyor, sana gösterilmiyor.
- **Elle tetikleme:** `POST /api/jobs/{job}/run?force=true` (briefing, checkin, followups, weekly_plan).

## EK-6. Ses ✅

- **Akış:** `POST /api/voice`, Groq `whisper-large-v3` (Türkçe) ile metne çeviriyor; metin normal sohbet akışıyla gidiyor. Kullanım `llm_usage`'a yazılıyor (tier `stt`).
- **Canlı deneme:** Windows'un Türkçe sesiyle ürettiğim örnek → "Yarın saat 14'te Iceberg toplantısı var." (3,4 sn, $0.0003).
- **Arayüz:** Basılı tut ve konuş, bırakınca gönderilir; kısa dokunuş aç/kapa modu; canlı dalga göstergesi, süre, iptal.
- **karar:** STT router dışında (sohbet tamamlaması değil). Ayarları `providers.yaml` içindeki `stt` bölümünde.
- ⚠️ **Gerçek mikrofonla denenmedi:** Headless tarayıcıda mikrofon yok. Telefonda mikrofon için HTTPS gerekiyor (`tailscale serve`).

## EK-7. Sağlamlaştırma ✅

- **Smoke testi:** `scripts/smoke.ps1` stack'i, health uç noktalarını ve API'yi kontrol ediyor; ayrıca gerçek bir sohbet mesajı gönderip geri alıyor.
  - Bu gece yalnızca `-NoChat` ile çalıştırdım, çünkü sohbet adımı gerçek veritabanına bir test sohbeti yazar.
  - Yazarken bir hata buldum: dev ortamında `/health` adresine Vite `index.html` dönüyordu ve kontrol yanlışlıkla geçiyordu. Artık `/api/health` kullanılıyor.
- **Testler:** Backend paketi 25 sn'den 14 sn'ye indi. Sebep, test başına `TRUNCATE` yerine tek bir `DELETE` ve sequence sıfırlama bloğu.
  - En yavaş 5 testin üçü hızlandı.
  - İki migration testi gerçek Alembic yukarı/aşağı adımlarını çalıştırdığı için aynı kaldı.
- **README:** Güncel özellikler, mimari ve hızlı başlangıç.

## Sabah denemen gerekenler

1. **Tasarım:** http://localhost:8080'u aç. Karşılaştırma için http://localhost:8080/design-preview.
2. **Brifing:** 08:00 brifingi sohbette olmalı (bilgisayar açıksa). Değilse: `curl -X POST "localhost:8000/api/jobs/briefing/run?force=true"`.
3. **CSE 221:** "19 kasımda cse221'e gitmedim" yaz; CSE 221 7 saate çıkmalı. Durum sayfasında saatler görünüyor.
4. **Mikrofon:** localhost'ta basılı tutup konuş; Chrome izin isteyecek. Kayıt, dalga göstergesi ve gönderim gerçek tarayıcıda hiç denenmedi.
5. **Check-in:** 21:00 check-in'ine "✓ Hepsi tamam" butonuyla cevap ver. LLM'in bu cevabı nasıl işlediği canlı denenmedi.
6. **Haftalık plan:** Pazar 20:00 taslağı gelecek; istersen `…/api/jobs/weekly_plan/run?force=true` ile hemen dene, sonra "evet" de.
7. **Smoke testi:** `.\scripts\smoke.ps1` (tam hâli bir smoke sohbeti yazar ve geri alır) ya da `-NoChat`.
8. **Yedekler:** `backups/` klasöründe gece alınan yedekler var. İstersen `BACKUP_DIR`'i OneDrive gibi senkronize bir klasöre yönlendir.
9. **Push:** Push etmeden önce `git log --oneline 564f1f7..HEAD`.
