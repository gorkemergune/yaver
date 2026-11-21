# Yaver günlük kullanım rehberi

Yaver'le konuşarak çalışırsın. Ders programı, devamsızlık, sınav, toplantı, spor, kariyer,
startup, reklam, içerik ve arkadaş planları; hepsini sohbete yazman yeter. Ekran yalnızca okumak
içindir; tek buton **Geri al**'dır.

Ana ekran **Ofis**: her çalışanın bir masası, bir **defteri** (kısa tarihli notlar) ve bir
**gelen kutusu** (ona verilen işler) var. Bir çalışan çalışırken masasında, toplantıdayken
toplantı odasında görünür. Bunlar uydurma değildir, gerçekten yaptığı işe karşılık gelir.

---

## 1. Kadro: kim ne yapar?

| Çalışan | Alanı | Kendiliğinden ne yapar (mesai) |
|---|---|---|
| **Yaver** · Chief of Staff | Mesajını parçalara böler, her parçayı doğru çalışana verir, cevapları tek mesajda toplar. Plan sorularını ("yarın ne var?") kendisi cevaplar. | Sabah brifingi (önce standup), akşam gün sonu raporu, Pazar haftalık plan taslağı |
| **Scholar** · Akademik | Dersler, lab'lar, devamsızlık, sınavlar, ödevler, ders notları, syllabus, çalışma kağıtları | Sınava ~7 gün kala tekrar planı önerir |
| **Chrono** · Ajanda | Toplantılar, iş/staj saatleri, etkinlikler, hackathonlar, takip edilen dönüşler, görevler | Bekleyen takipleri her gün sorar, yaklaşan teslimlere bakar |
| **Coach** · Disiplin | Spor, alışkanlıklar, ekran süresi ve uygulama limitleri | Spor günlerini ve ekran süresini izler, 21:00 check-in'i yapar |
| **Mentor** · Kariyer | Staj/iş başvuruları, mülakatlar, iş yerindeki projeler, başvuru dönüşleri | Her sabah bekleyen başvuru dönüşlerine bakar |
| **Venture** · Startup | Girişimin haftalık hedefleri, rakipler, sektör haberleri, yatırım | Her sabah startup deposuna (GitHub) bakar, rakip/haber taraması yapar |
| **Metrics** · Reklam analisti | Meta (Instagram/Facebook) reklamları: harcama, tıklama, dönüşüm | Attığın Ads Manager CSV'sini kaydeder, önceki dönemle karşılaştırır |
| **Creator** · İçerik | Post fikirleri, içerik takvimi, paylaşım taslakları, trendler | Pazartesi haftanın içerik takvimi taslağını defterine yazar |
| **Buddy** · Sosyal çevre | Arkadaşlar, doğum günleri, buluşmalar, ortak planlar | Her sabah önümüzdeki haftanın doğum günlerini ve buluşmalarını toplar |

İsimler `config/agents.yaml`'dan gelir. Kendi isimlerini verdiysen tablodaki isim yerine
onları kullan; görevler (id'ler: `yaver`, `academic`, `agenda`, `discipline`, `career`,
`startup`, `ads`, `content`, `social`) aynıdır.

### Bir çalışanla nasıl konuşurum?

- **Genel sohbet (Sohbet sekmesi ya da Ofis'te "Yaver'e yaz"):** ne istediğini yaz, Yaver
  dağıtır. Karışık mesaj olur: *"yarın linear iptal, akşam spora gidemeyeceğim, Iceberg'den
  dönüş geldi mi?"* → Scholar, Coach ve Mentor aynı anda çalışır, cevap tek mesajda gelir.
- **Adıyla çağır:** *"Scholar, yarın hangi derslerim var?"*, *"Buddy, Ece'nin doğum günü ne
  zaman?"* → mesaj doğrudan o çalışana gider.
- **Ofiste tıkla:** bir çalışana (ya da listedeki adına) tıklayınca paneli açılır: şu an ne
  yaptığı, **Defter**, **Gelen kutusu**, mesai planı ve altta **doğrudan sohbet** kutusu. Orada
  yazdığın yalnızca o çalışana gider, o kendi araçlarıyla cevaplar. Geri al burada da çalışır.
- **Defterine baktır:** *"Venture'ın defterinde ne var?"*, *"Metrics bu hafta ne not aldı?"*
- **Görev panosu (Pano):** bütün çalışanların işleri dört sütunda: *Bekliyor* (bugün saati
  gelmemiş mesai işleri), *Çalışıyor*, *Onay bekliyor* (senden cevap bekleyen soru), *Bitti*.
  Bir karta tıklamak o çalışanın panelini açar.

Bir çalışanın üstünde kırmızı nokta varsa: ya sana bir soru sordu ve cevabını bekliyor (sohbete
bak), ya da günlük harcama sınırını doldurdu (`agents.yaml` → `daily_budget_usd`). İkincisinde
mesai işleri durur ama sohbet çalışmaya devam eder.

## 2. Çalışan çalışan örnek cümleler

### Yaver (koordinatör)
- "yarın ne var?", "bu hafta neler var?", "cuma öğleden sonra boş muyum?"
- "Cuma günleri Medipol'deyim, bunu hatırla" / "bunu unut"
- "son değişikliği geri al"
- "bugün linear iptal ve akşam spor yok" → iki çalışana böler

### Scholar (dersler)
**Program**
- "Pazartesi 9-11 Linear Algebra B204, çarşamba 13-15 EE211 lab"
- "salı perşembe 19-20 spor" (bunu Coach alır)

**İptal ve taşıma** (yalnızca o gün değişir, diğer haftalar aynı kalır)
- "bugün linear iptal"
- "yarınki EE211 dersi iptal, hoca gelmiyor"
- "çarşamba lab cuma 14-16'ya alındı"

**Devamsızlık** (ders saati olarak sayılır: 2 saatlik ders = 2 saat)
- "bugün linear'a gitmedim"
- "5 12 17 19 kasımda CSE221'e gitmedim"
- "MATH221 devamsızlık sınırım 8 saat", "kaç saat devamsızlığım var?"
- "Yaver'den önce EE211'den 4 saat devamsızlığım vardı"

**Sınav, not, çalışma kağıdı**
- "27 Kasım Cuma 10:00'da MATH221 vizesi var", "haftaya salı CSE221 quiz"
- Syllabus PDF'ini at → haftalık konular tablo olarak gelir, "evet" dersen kaydedilir.
- "EE211'de Thevenin direnci nasıl bulunuyordu?" → yüklediğin notlarda arar, kaynağı yazar
  "(ee211_hafta7_notlar.pdf, s. 2)". Notlarda yoksa bunu söyler, ezberden uydurmaz.
- "bu hafta EE211'de ne işlendi?", "EE211 7. hafta için çalışma kağıdı hazırla"
- "bu haftanın adı Vize Haftası olsun"

### Chrono (ajanda)
- "yarın 14'te Iceberg toplantısı var", "her cuma 9-17 Medipol'de çalışıyorum"
- "28-29 kasım hackathon", "perşembeki toplantıyı 16'ya al", "cumartesi buluşmasını sil"
- "yarın için 'sunum hazırla' görevi ekle", "rapor yaz görevini bitirdim"
- "hocadan proje onayı bekliyorum, her gün sor" → takip; "onay geldi!" → kapanır

### Coach (disiplin)
- "salı perşembe 19-20 spor", "bu akşam spora gidemeyeceğim"
- "yarın için '30 dk yürüyüş' görevi ekle", "yürüyüşü yaptım"
- "bugün ne kadar ekrandaydım?", "bugün ne kadar VALORANT oynadım?" (masaüstü uygulaması gerekir;
  uygulama limitleri masaüstü uygulamasının ayarlarından verilir, sohbetten değil)
- 21:00 check-in'inde: **✓ Hepsi tamam**'a dokun ya da "spor hariç hepsi tamam" yaz.

### Mentor (kariyer)
- "Trendyol'a staj başvurusu yaptım, 3 günde bir dönüş geldi mi diye sor"
- "Iceberg'den mülakat daveti geldi, 2 Aralık 11:00"
- "Iceberg'den olumsuz döndüler" → takip kapanır
- Staj ve iş başvurusu takipleri Mentor'un: her sabah 10:00'da kendi listesine bakar, öğlen
  takip mesajında kendi adıyla sorar (Chrono yalnız diğer takipleri sorar).
- "işteki dashboard projesi için cumaya kadar demo hazırla görevi ekle"
- "junior backend ilanlarında en çok istenen ne?" (web arama anahtarı varsa)

### Venture (startup)
- "Venture, bu hafta depoda neler oldu?", "kim hafta-07 teslimini atmadı?" (sabah notlarından cevaplar)
- "demo videosu ne zaman teslim?", "yatırımcı sunumu görevini bitirdim"
- "rakiplerden bu hafta haber var mı?" (web arama anahtarı varsa)
- **Repo takibi** (GitHub, salt okunur): her sabah 08:15'te startup deposuna bakar.
  - İlk sefer deponun haritasını defterine yazar: README özeti, hafta klasörleri, toplantı
    notları, açık issue'lar, milestone'lar, son commit'ler.
  - Sonra her sabah: son hafta klasörüne kim commit atmış / atmamış; toplantı notlarındaki ve
    issue'lardaki tarihli işler ("25 Kasım: demo videosu teslim") **takvime teslim + takip**
    olarak bir kez eklenir; 3 gün içindeki bir iş için dosya ya da PR yoksa **hatırlatma**,
    gelince takip **kapanır**.
  - Hiçbir şey yazmaz, PR açmaz, issue değiştirmez. Yanlış eklenen için: "GitHub'dan
    eklenenleri geri al".
  - Kurulum (token + depo adı): [venture-github.md](venture-github.md). Token yoksa Venture
    günde bir "GitHub entegrasyonu bekliyor" notu düşer.

### Metrics (reklam)
- **CSV atmak:** Ads Manager → Kampanyalar → tarih aralığını seç → *Dışa aktar* → *Tablo
  verilerini dışa aktar* → **CSV**. Dosyayı sohbete sürükle, ataçla seç ya da yapıştır; mesaj
  yazmana gerek yok (istersen "geçen haftanın raporu" yaz). Tablonun ekran görüntüsü de olur.
- Ne olur: dosya **doğrudan Metrics'e** gider. Kampanya / reklam seti / reklam başına harcama,
  gösterim, erişim, tıklama, CTR, CPC, sonuç ve sonuç başı maliyet **kodda** okunur, kaydedilir
  ve önceki dönemle karşılaştırılır. Özet + **3 öneri**yi haftalık derin model (Opus) yazar;
  rapor Metrics'in defterine de düşer.
- Aynı dosyayı ikinci kez atarsan yeniden kaydedilmez. **Geri al** raporu, satırlarını ve defter
  notunu birlikte siler.
- Sonra: "geçen haftaki reklamlar nasıldı?", "hangi kampanyanın sonuç başı maliyeti arttı?",
  "Metrics, en iyi reklam setini söyle".
- Örnek dosyalar: `examples/meta-ads/`. Opus'un aylık sınırı `DEEP_MONTHLY_BUDGET_USD`; dolunca
  analizi Sonnet yazar. Meta hesabını doğrudan bağlama henüz yok: Metrics'in sabah işi bunu
  "entegrasyon bekliyor" diye not eder.

### Creator (içerik)
- "Creator, bu haftanın içerik takvimini çıkar"
- "Creator, Örnek Girişim için gelecek haftaya 3 Instagram postu planla"
- "salı postunu daha kısa yaz", "perşembe için reels fikri ver"
- **Taslaklar:** her Pazartesi 10:30'da haftanın post taslaklarını **defterine** yazar: gün,
  platform, biçim, konu, taslak metin ve neye dayandığı. Bağlamı: `agents.yaml`'da
  `content_calendar` işinin `topics`'i (marka), bu markadan bahseden kalıcı bilgiler ("bunu
  hatırla"), Venture'ın son notları, yaklaşan etkinlikler; web arama anahtarı varsa trendler.
- **Hiçbir şey paylaşılmaz.** Taslağı defterden (Ofis → Creator) kopyalayıp sen paylaşırsın.
  Bir postu takvime koymak istersen: "Creator, salı 19:00'a 'kampanya postu' etkinliği ekle".

### Buddy (sosyal)
- "Ece'nin doğum günü 14 Aralık, hatırlat"
- "cumartesi 20:00 Kadıköy'de Mert'le buluşma"
- "Can'a kitabını geri vereceğime söz verdim, haftaya sor"
- "bu hafta kimlerin doğum günü var?"

## 3. Tarihler

"Yarın", "geçen salı", "haftaya cuma 14'te", "ayın 28'i", "27 Kasım Cuma" gibi ifadeleri **kod
çözer**, model tahmin etmez. Bir şey belirsizse Yaver sorar:
- Gün adı tarihle uyuşmuyorsa ("27 Kasım Perşembe"): "26 Kasım Perşembe mi, 27 Kasım Cuma mı?"
- Sabah mı akşam mı belli değilse ("yarın 9'da"): sorar.

Saat yazmadığında: 8-11 arası sabah, 1-7 arası öğleden sonra sayılır ("3'te" = 15:00). Bunu
`.env`'deki `CLOCK_MORNING_HOURS` / `CLOCK_AFTERNOON_HOURS` ile değiştirebilirsin.

## 4. Geri al

Her cevabın altındaki değişiklik kartında **Geri al** var. O mesajda yapılan her şeyi (birden
fazla çalışan çalıştıysa hepsini) tek seferde geri alır. Sohbetten de olur: "geri al", "son
değişikliği geri al". Bir cevap hata verdiyse altında **Tekrar dene** çıkar.

## 5. Görsel, PDF ve CSV göndermek

Ataç düğmesi, sürükle-bırak ya da yapıştır (Ctrl+V). iPhone'da kamera da açılır.

- **Ders programının fotoğrafı veya ekran görüntüsü:** Claude okur, tablo olarak gösterir; "evet" dersen yazılır.
- **Sınav duyurusu, afiş, davetiye:** tarihleri okunur ve kodda çözülür. Okunamayan kısımlar "Belirsiz" diye listelenir, tahmin edilmez.
- **Syllabus (PDF):** Scholar haftalık konuları tablo olarak getirir; "evet" dersen kaydedilir.
- **Ders notu (PDF veya sayfa fotoğrafı):** Scholar hangi ders ve hafta olduğunu sorar ya da syllabus'tan önerir. Taranmış PDF'te metin yoksa sayfaların fotoğrafını gönder.
- **Reklam raporu (CSV ya da tablo ekran görüntüsü):** Metrics'e gider (yukarıda).

Görseller sadece Claude'a gider; Groq'a görsel gönderilmez. Fotoğraflardaki konum (EXIF) bilgisi silinir.

## 6. Ses

Mikrofon düğmesine **basılı tut, konuş, bırak**. Kısa bir dokunuşla da kayda başlar; tekrar
dokununca gönderir. Ses Groq Whisper ile yazıya çevrilir. Telefonda mikrofon için HTTPS gerekir
(Tailscale).

## 7. Yaver kendiliğinden ne zaman yazar?

| Ne zaman | Ne | Ayar (`.env`) |
|---|---|---|
| Her sabah 09:00 | Standup (her çalışan 1-2 cümle) + brifing | `BRIEFING_TIME` |
| Her gün 12:00 | Takip soruları ("Iceberg'den dönüş var mı?") | `FOLLOWUP_TIME` |
| Her gün 18:00 | Sınav tekrar planı taslağı (Scholar) | `EXAM_PREP_TIME` |
| Her akşam 21:00 | Check-in (Coach) | `CHECKIN_TIME` |
| Her akşam 21:15 | Gün sonu raporu (defterlerden) | `DAY_REPORT_TIME` |
| Pazar 20:00 | Haftalık toplantı ve plan taslağı | `WEEKLY_PLAN_TIME` |
| Çalışanın mesai saatleri | Venture repo/haber taraması, Metrics reklam notu, Creator içerik takvimi, Buddy hatırlatmaları... → defterlerine | `config/agents.yaml` → `shift_jobs` |

Bilgisayar o saatte kapalıysa iş, açılınca bir kez çalışır. Mesai işleri LLM kullanmaz (tek
istisna Creator'ın haftalık taslağı); sonuçları defterlere ve görev panosuna düşer.

**Bildirimler:** Durum → Bildirimler → *Bildirimleri aç*. iPhone'da önce Safari → Paylaş →
**Ana Ekrana Ekle**, sonra Yaver'i ana ekrandan açıp bildirimleri oradan aç (iOS 16.4+).

## 8. Ekranlar

- **Ofis:** sahne, çalışan listesi, son cevap ve ofis akışı; bir çalışana tıkla → paneli.
  - **Masaya tıkla** (ya da paneldeki *Ekranına bak*): o çalışanın ekranı yakınlaşır; şu an ne
    yaptığı, hangi aracı kullandığı, elindeki iş ve defterinden son iki satır. Esc ile kapanır.
  - **Mesai dışı** (`agents.yaml` → `office.open_at` / `close_at`, varsayılan 08:00-23:00):
    boştaki çalışanlar kapıdan çıkıp eve gider, masaları boş ve ekranları sönüktür. Gece bir
    şey yazarsan ilgili çalışan "gece mesaisi"ne gelir, işi bitince yine gider.
  - **Ses** (başlıktaki hoparlör): iş başlarken, toplantıda, seni beklerken ve iş bitince hafif
    sesler. Varsayılan kapalı; seçim bu tarayıcıda hatırlanır.
- **Sohbet:** Yaver'le genel sohbet.
- **Takvim:** Bugün / Yarın / Hafta. "Şu an" çizgisi, iptaller üstü çizili; haftalar ‹ › ile
  ya da kaydırarak değişir.
- **Pano:** görev panosu (yukarıda).
- **Durum:** dönemin haftaları, çalışma kağıtları, devamsızlık, bildirimler, takvim aboneliği,
  cihaz anahtarları, aylık LLM harcaması.
- **Takvim aboneliği:** Durum → Takvim aboneliği → *Takvime ekle*. Bağlantı gizli bir anahtar
  içerir; paylaştıysan *Yeni bağlantı* de, eskisi çalışmayı bırakır.

## 9. Masaüstü uygulaması (Windows)

Ekranda duran yuvarlak logoya tıklayınca mini sohbet açılır. Ekran süresini tutar ve uygulama
limitlerinde %80'de ve %100'de uyarır; Coach'a "bugün ne kadar oynadım?" diye sorabilirsin.
Kurulum: `desktop/README.md`, bağlantı: [cihaz-anahtari.md](cihaz-anahtari.md).

## 10. Giriş ve güvenlik

- `.env`'de `APP_PASSWORD` boşsa giriş yoktur; bu yalnızca Yaver'e sadece kendi bilgisayarından
  erişiliyorsa uygundur. **Telefonu bağlamadan (Tailscale) önce bir parola koy.**
- Tarayıcı bir kez giriş yapar, oturum 30 gün kullanılmazsa biter. Masaüstü uygulaması ve Siri
  kısayolu **cihaz anahtarı** ile bağlanır (Durum → Cihaz anahtarları).
- 10 dakikada 5 yanlış parola denemesinden sonra bir süre beklemek gerekir.

## 11. Canlı ve geliştirme, yedek

Gerçek verin **canlı** kurulumdadır (`yaver-live`, http://localhost:8080); kod denemeleri
ayrı veritabanlı **geliştirme** kurulumunda (`yaver-dev`, http://localhost:8180). Güncelleme
yalnızca `.\scripts\deploy-live.ps1` ile yapılır: önce test eder, yedek alır, sonra geçer;
sorun çıkarsa eski sürümde kalır. Ayrıntı: [canli-ve-gelistirme.md](canli-ve-gelistirme.md).

```powershell
.\scripts\live.ps1 status                  # canlıda hangi sürüm var
.\scripts\backup.ps1                       # canlı veritabanının yedeği
.\scripts\backup.ps1 list
.\scripts\smoke.ps1 -NoChat                # canlı çalışıyor mu
```

API her açılışta, son yedek 24 saatten eskiyse otomatik yedek alır (`backups/`, son 14 tane).
Ayrıntılar: [yedekleme.md](yedekleme.md).

> ⚠️ Gerçek veritabanı silinmesin diye canlı kurulumun volume'ü "external"dır ve
> `live.ps1` `down -v`'yi reddeder. Yine de `docker volume rm yaver_pgdata` yazma.

## 12. Sık sorunlar

| Sorun | Çözüm |
|---|---|
| "Sunucuya ulaşılamadı" | `.\scripts\live.ps1 ps`: db, api, web *running* olmalı. Kontrol: `.\scripts\smoke.ps1 -NoChat` |
| Cevap gecikti / hata | 45 sn hiçbir şey gelmezse hata gösterilir; **Tekrar dene**'ye bas. Groq'un dakikalık sınırı dolduysa Yaver Claude Haiku'ya geçer. |
| Bir şeyi yanlış kaydetti | Kartta **Geri al**, sonra doğrusunu yaz. |
| Tarihi yanlış anladı | Tarihi açık yaz: "27 Kasım Cuma". Gün adı tutmazsa Yaver sorar. |
| Bir çalışanda kırmızı nokta | Sohbette cevap bekleyen sorusu var ya da günlük bütçesi doldu (panelde yazar). |
| Venture / Creator / Mentor "entegrasyon bekliyor" | `GITHUB_TOKEN` + `GITHUB_STARTUP_REPO` (Venture) ya da `TAVILY_API_KEY` / `BRAVE_API_KEY` (web arama) `.env`'de yok. Ekledikten sonra `.\scripts\live.ps1 up -d` (`restart` `.env`'i yeniden okumaz). |
| Metrics CSV'yi okumadı | Ads Manager'dan **CSV** olarak dışa aktar (Excel değil). Ekran görüntüsü için Claude anahtarı gerekir. |
| Görsel okunmadı | `ANTHROPIC_API_KEY` gerekir; Claude bütçesi dolduysa (%100) görseller okunmaz. |
| Bildirim gelmiyor | Durum → Bildirimler → *Deneme bildirimi gönder*. iPhone'da uygulama ana ekrandan açılmış olmalı. |
| Telefonda mikrofon çalışmıyor | HTTPS gerekir: Tailscale (`tailscale serve`), bkz. [KURULUM_WINDOWS.md](KURULUM_WINDOWS.md). |
| Claude harcaması | Durum → aylık harcama. %80'de Sonnet yerine Haiku, %100'de Claude kapanır (`CLAUDE_MONTHLY_BUDGET_USD`). |

Daha fazlası: [Canlı ve geliştirme](canli-ve-gelistirme.md) · [LLM sağlayıcıları](llm-saglayicilari.md) · [Yedekleme](yedekleme.md) · [Venture GitHub](venture-github.md) · `README.md`
