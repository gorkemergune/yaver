# Yaver günlük kullanım rehberi

Yaver'le konuşarak çalışırsın. Ders programı, devamsızlık, sınav, toplantı, spor ve görev gibi her şeyi sohbete yazman yeter. Ekran yalnızca okumak içindir; tek buton **Geri al**'dır.

Örneklerdeki isimler varsayılan ekibe göre: **Friday** dersler, **Jarvis** ajanda, **Karen** disiplin. Kendi isimlerin `config/agents.yaml`'da.

---

## 1. Ekip: kim ne yapar?

| Yaver | Alanı | Örnek |
|---|---|---|
| **Yaver** (koordinatör) | Mesajı böler, doğru yavere verir, cevapları tek mesajda toplar. Basit tek işleri kendisi yapar. | "bugün linear iptal" |
| **Friday** | Dersler, lab'lar, devamsızlık, sınavlar, ders notları, syllabus, çalışma kağıtları | "EE211'e gitmedim" |
| **Jarvis** | Toplantılar, iş/staj, etkinlikler, takip edilen dönüşler, görevler | "yarın 14'te Iceberg toplantısı var" |
| **Karen** | Spor, alışkanlıklar, ekran süresi | "bu akşam spora gidemeyeceğim" |

Bir yaveri adıyla çağırabilirsin: "Friday, yarın ne var?". Cevapta her yaverin yaptığı kendi satırında yazar: "Friday: bugünkü Linear Algebra dersini iptal etti."

## 2. Örnek cümleler

**Program**
- "Pazartesi 9-11 Linear Algebra B204, çarşamba 13-15 EE211 lab"
- "her cuma 9-17 Medipol'de çalışıyorum"
- "salı perşembe 19-20 spor"

**İptal ve taşıma** (yalnızca o gün değişir, diğer haftalar aynı kalır)
- "bugün linear iptal"
- "yarınki EE211 dersi iptal, hoca gelmiyor"
- "çarşamba lab cuma 14-16'ya alındı"
- "bu hafta perşembe linear yerine cumartesi 10-12'de"

**Devamsızlık** (ders saati olarak sayılır: 2 saatlik ders = 2 saat)
- "bugün linear'a gitmedim"
- "5 12 17 19 kasımda CSE221'e gitmedim"
- "MATH221 devamsızlık sınırım 8 saat"
- "kaç saat devamsızlığım var?"
- "Yaver'den önce EE211'den 4 saat devamsızlığım vardı"

**Sınav ve etkinlik**
- "27 Kasım Cuma 10:00'da MATH221 vizesi var"
- "haftaya salı CSE221 quiz"
- "28-29 kasım hackathon"

**Takip** (her gün ya da belirli bir günde sorulur)
- "Iceberg'e staj başvurusu yaptım, her gün dönüş geldi mi diye sor"
- "hackathon kabul geldi!" → takip kapanır.

**Görev**
- "yarın için 'sunum hazırla' görevi ekle"
- "rapor yaz görevini bitirdim"

**Soru**
- "yarın ne var?", "bu hafta neler var?", "cuma boş muyum?"

**Hafta**
- "bu haftanın adı Hackathon Haftası olsun"

### Tarihler

"Yarın", "geçen salı", "haftaya cuma 14'te", "ayın 28'i", "27 Kasım Cuma" gibi ifadeleri **kod çözer**, model tahmin etmez. Bir şey belirsizse Yaver sorar:
- Gün adı tarihle uyuşmuyorsa ("27 Kasım Perşembe"): "26 Kasım Perşembe mi, 27 Kasım Cuma mı?"
- Sabah mı akşam mı belli değilse ("yarın 9'da"): sorar.

Saat yazmadığında: 8-11 arası sabah, 1-7 arası öğleden sonra sayılır ("3'te" = 15:00). Bunu `.env`'deki `CLOCK_MORNING_HOURS` / `CLOCK_AFTERNOON_HOURS` ile değiştirebilirsin.

## 3. Geri al

Her cevabın altındaki değişiklik kartında **Geri al** var. O mesajda yapılan her şeyi (birden fazla yaver çalıştıysa hepsini) tek seferde geri alır. Sohbetten de olur: "geri al", "son değişikliği geri al".

## 4. Görsel ve PDF göndermek

Ataç düğmesi, sürükle-bırak ya da yapıştır (Ctrl+V). iPhone'da kamera da açılır.

- **Ders programının fotoğrafı veya ekran görüntüsü:** Claude okur, tablo olarak gösterir; "evet" dersen yazılır.
- **Sınav duyurusu, afiş:** tarihleri okunur ve kodda çözülür. Okunamayan kısımlar "Belirsiz" diye listelenir, tahmin edilmez.
- **Syllabus (PDF):** haftalık konular tablo olarak gelir; "evet" dersen kaydedilir, ders yoksa oluşturulur.
- **Ders notu (PDF veya sayfa fotoğrafı):** Friday hangi ders ve hafta olduğunu sorar ya da syllabus'tan önerir ("EE211 7. hafta notu olarak kaydedeyim mi?"). Kaydedildikten sonra aranabilir. Taranmış PDF'te metin yoksa sayfaların fotoğrafını gönder.

Görseller sadece Claude'a gider; Groq'a görsel gönderilmez. Fotoğraflardaki konum (EXIF) bilgisi silinir.

## 5. Ders notları ve çalışma kağıdı

- "EE211'de Thevenin direnci nasıl bulunuyordu?" → Friday yüklediğin notlarda arar ve kaynağı gösterir: "(ee211_hafta7_notlar.pdf, s. 2)". Notlarda yoksa bunu söyler, ezberden cevap uydurmaz.
- "bu hafta EE211'de ne işlendi?" → syllabus'taki haftanın konuları.
- "EE211 7. hafta için çalışma kağıdı hazırla" → yalnızca notlarından yazılmış bir kağıt: özet, kavramlar, formüller, kendini dene soruları. Her bilginin yanında kaynak numarası, sonda "Kaynaklar" listesi (dosya + sayfa) var. Kağıtlar **Durum → Çalışma kağıtları**'nda; Markdown indirebilir ya da "PDF olarak kaydet" diyebilirsin.
- Sınava ~1 hafta kala Friday kendiliğinden bir **tekrar planı** önerir: konular, notlar ve boş saatlerine göre günlük tekrar seansları. "Evet" dersen görevlere yazılır.

## 6. Ses

Mikrofon düğmesine **basılı tut, konuş, bırak**. Kısa bir dokunuşla da kayda başlar; tekrar dokununca gönderir. Ses Groq Whisper ile yazıya çevrilir ve mesaj olarak gider. Telefonda mikrofon için HTTPS gerekir (Tailscale).

## 7. Yaver kendiliğinden ne zaman yazar?

| Ne zaman | Ne | Ayar (`.env`) |
|---|---|---|
| Her sabah 08:00 | Brifing: dersler, sınav geri sayımı, limitine yaklaşan devamsızlık, ajanda, spor, görevler | `BRIEFING_TIME` |
| Her gün 12:00 | Takip soruları ("Iceberg'den dönüş var mı?") | `FOLLOWUP_TIME` |
| Her gün 18:00 | Sınav hazırlığı taslağı (2-7 gün kalan sınavlar için) | `EXAM_PREP_TIME` |
| Her akşam 21:00 | Check-in | `CHECKIN_TIME` |
| Pazar 20:00 | Haftalık plan taslağı (Sonnet) | `WEEKLY_PLAN_TIME` |

Bilgisayar o saatte kapalıysa iş, açılınca bir kez çalışır.

**Akşam check-in:** günün dersleri "katıldı" sayılır, spor ve görevler sorulur.
- Her şey yolundaysa **✓ Hepsi tamam**'a dokun ya da "spor hariç hepsi tamam" yaz.
- Bir derse gitmediysen "EE211'e gitmedim" yaz.
- Masaüstü uygulaması açıksa check-in'de ekran süresi satırı da olur ("bugün 5 saat 12 dk ekran, 1 saat 10 dk VALORANT").
- Cevap vermezsen ertesi sabah brifinginde bir kez hatırlatılır.

**Bildirimler:** Durum → Bildirimler → *Bildirimleri aç*. Brifing, check-in, takip ve taslaklar telefona da gelir. iPhone'da önce Safari → Paylaş → **Ana Ekrana Ekle**, sonra Yaver'i ana ekrandan açıp bildirimleri oradan aç (iOS 16.4+).

## 8. Ekranlar

- **Bugün / Yarın:** günün planı. "şu an" çizgisi, iptaller üstü çizili.
- **Hafta:** ‹ › ile, ←/→ tuşlarıyla ya da telefonda kaydırarak hafta değiştir.
  - Başlıkta "2026-27 Güz · 9. Hafta" ve haftanın etiketi var (Vize Haftası, Tatil Haftası… ya da senin verdiğin ad).
  - Geçmiş haftalarda devamsızlıklar kırmızı, taşınan dersler "eski → yeni" görünür.
- **Durum:**
  - Dönemin bütün haftaları; tıklayınca o haftaya gider.
  - Çalışma kağıtları, ekip ve son yaptıkları.
  - Devamsızlık (saat ve kalan hak).
  - Bildirimler ve takvim aboneliği.
  - Aylık LLM harcaması.
- **Takvim aboneliği:** Durum → Takvim aboneliği → *Takvime ekle*.
  - Dersler (iptal ve taşımalar işlenmiş hâliyle), sınavlar ve etkinlikler iPhone Takvim'de görünür, saatte bir güncellenir.
  - Bağlantı gizli bir anahtar içerir. Paylaştıysan *Yeni bağlantı* de, eskisi çalışmayı bırakır.

## 9. Masaüstü uygulaması (Windows)

Ekranda duran yuvarlak logoya tıklayınca mini sohbet açılır. Ekran süresini tutar ve uygulama limitlerinde (ör. VALORANT 90 dk) %80'de ve %100'de uyarır. Günlük özet 10 dakikada bir backend'e gider; Karen'e "bugün ne kadar oynadım?" diye sorabilirsin. Kurulum ve ayarlar: `desktop/README.md`.

## 10. Giriş ve güvenlik

- `.env`'de `APP_PASSWORD` boşsa giriş yoktur. Bu yalnızca Yaver'e sadece kendi bilgisayarından erişiliyorsa uygundur.
- **Telefonu bağlamadan (Tailscale) önce bir parola koy**, sonra `docker compose up -d` çalıştır. Tarayıcı bir kez giriş yapar, oturum 30 gün kullanılmazsa biter. Masaüstü uygulaması ve Siri kısayolu **cihaz anahtarı** ile bağlanır: Durum → Cihaz anahtarları (ayrıntı: `cihaz-anahtari.md`).
- Durum → Oturum → *Oturumu kapat* o tarayıcının oturumunu bitirir.

## 11. Yedek ve geri yükleme

API her açılışta, son yedek 24 saatten eskiyse otomatik yedek alır (`backups/`, son 14 tane). Ayrıntılar: [yedekleme.md](yedekleme.md).

```powershell
.\scripts\backup.ps1                       # şimdi yedek al
.\scripts\backup.ps1 list                  # yedekleri listele
.\scripts\backup.ps1 restore backups\yaver-....sql.gz   # önce ayrı bir veritabanına (yaver_restore)
```

> ⚠️ `docker compose down -v` veritabanını **siler**. Durdurmak için `docker compose down` ya da `stop` yeterli.

## 12. Sık sorunlar

| Sorun | Çözüm |
|---|---|
| "Sunucuya ulaşılamadı" | `docker compose ps`: üç servis (db, api, web) de *running* olmalı. Kontrol: `.\scripts\smoke.ps1 -NoChat` |
| Cevap çok geç geliyor / "sıra bekleniyor" | Groq'un dakikalık sınırı doldu, Yaver Claude Haiku'ya geçer. Durum sayfasında harcamayı görürsün. |
| Bir şeyi yanlış kaydetti | Kartta **Geri al**, sonra doğrusunu yaz. Ya da "EE211 19 kasım devamsızlığını sil". |
| Tarihi yanlış anladı | Tarihi açık yaz: "27 Kasım Cuma". Gün adı tutmazsa Yaver sorar. |
| Görsel okunmadı | Claude anahtarı (`ANTHROPIC_API_KEY`) gerekir; bütçe dolduysa (%100) görseller okunmaz. |
| PDF "metin yok" diyor | Taranmış PDF: sayfaların fotoğrafını gönder. |
| Notlarda arama hiçbir şey bulmuyor | Notun ders ve haftasıyla kaydedildiğinden emin ol. İlk aramada embedding modeli (~220 MB) bir kez iner, birkaç saniye sürer. |
| Bildirim gelmiyor | Durum → Bildirimler → *Deneme bildirimi gönder*. iPhone'da uygulama ana ekrandan açılmış olmalı; `.env`'de VAPID anahtarları dolu olmalı. |
| Telefonda mikrofon çalışmıyor | Tarayıcı mikrofonu yalnızca HTTPS'te verir: Tailscale (`tailscale serve`) ile aç, bkz. [KURULUM_WINDOWS.md](KURULUM_WINDOWS.md). |
| Giriş ekranında parola kabul edilmiyor | Parola `.env`'deki `APP_PASSWORD`. 10 dk'da 5 yanlış denemeden sonra bir süre beklemek gerekir. |
| Claude harcaması | Durum → aylık harcama. %80'de Sonnet yerine Haiku kullanılır, %100'de Claude kapanır (`CLAUDE_MONTHLY_BUDGET_USD`). |

Daha fazlası: [LLM sağlayıcıları](llm-saglayicilari.md) · [Yedekleme](yedekleme.md) · `README.md`
