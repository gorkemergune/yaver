# Telefondan Yaver: Tailscale, iPhone uygulaması, bildirimler

Faz 1'in kalan üç maddesi (Tailscale + HTTPS, iPhone'da ana ekran uygulaması, iPhone'a push)
kodda hazır; eksik olan kurulum ve telefonda deneme. Bu belge ikisini canlı / geliştirme
ayrımına göre anlatır ve sonunda bir **kontrol listesi** verir. Kurulum adımlarının uzun hâli:
[KURULUM_WINDOWS.md](KURULUM_WINDOWS.md) §2-4.

## 0. Telefona hangi kurulum açılır?

| | **Canlı** (`yaver-live`) | **Geliştirme** (`yaver-dev`) |
|---|---|---|
| Telefondaki adres | `https://<makine>.<tailnet>.ts.net` (443) | `https://<makine>.<tailnet>.ts.net:8443` (isteğe bağlı) |
| Bilgisayarda nereye gider | `http://127.0.0.1:8080` | `http://127.0.0.1:8180` (Vite dev) |
| Ne için | Her gün | Yalnız bir değişikliği **deploy etmeden önce** telefonda denemek; iş bitince kapat |
| Veri | Gerçek | Uydurma (ayrı veritabanı) |
| Zamanlı bildirimler (brifing, check-in, takip) | Gelir | Gelmez (zamanlayıcı kapalı); yalnız *Deneme bildirimi* |

Bilmen gerekenler:

- **Telefon her gün yalnız canlıyı kullanır.** Ana ekrandaki Yaver simgesi canlının adresidir.
- iPhone iki adresi **iki ayrı uygulama** sayar (port farklı = başka site): ayrı giriş, ayrı
  bildirim izni, ayrı bildirim aboneliği. Geliştirmeyi ana ekrana eklersen adını
  **Yaver Dev** yap ki karışmasın.
- İkisi de aynı `.env`'i okur: aynı parola, aynı VAPID anahtarları.
- Geliştirme veritabanı sıfırlanırsa oradaki bildirim aboneliği de gider; telefonda
  *Bildirimleri aç*'a yeniden basmak yeter.

## 1. Önkoşullar (bir kez)

1. Canlı çalışıyor: `.\scripts\live.ps1 status` ve `.\scripts\smoke.ps1 -NoChat` hepsi OK.
2. `.env`'de **`APP_PASSWORD`** gerçek bir parola (`change-me` "parola yok" sayılır). Değiştirdiysen
   `.\scripts\live.ps1 up -d`.
3. `.env`'de **`VAPID_PUBLIC_KEY` / `VAPID_PRIVATE_KEY` / `VAPID_SUBJECT`** dolu. Eksikse Durum →
   Bildirimler kartı "Sunucuda VAPID anahtarları yok" der. **Anahtarları sonradan değiştirme:**
   değişirse kayıtlı bütün cihazların bildirimi durur, her cihazda yeniden açmak gerekir.
4. Bilgisayar uyumasın: Ayarlar → Sistem → Güç → *Prizdeyken uyku*: **Hiçbir zaman**. Uyuyan
   bilgisayara telefon ulaşamaz; zamanlı bildirimler de bilgisayar uyanınca gelir (geç).

## 2. Canlı: Tailscale ile HTTPS

Bilgisayara ve iPhone'a Tailscale kurulumu, MagicDNS ve HTTPS Certificates:
[KURULUM_WINDOWS.md §3](KURULUM_WINDOWS.md#3-tailscale-ile-https-adresi). Sonra bilgisayarda:

```powershell
tailscale serve --bg 8080          # canlı: https://<makine>.<tailnet>.ts.net -> 127.0.0.1:8080
tailscale serve status             # adresi ve "tailnet only" olduğunu gösterir
```

- `--bg` kalıcıdır: bilgisayar yeniden başlayınca da devam eder.
- **`tailscale funnel` kullanma**: Funnel internete açar; `serve` yalnız senin cihazlarına.
- `tailscale serve reset` **her şeyi** kapatır (canlı dahil); yalnız birini kapatmak için
  aşağıdaki `off` biçimini kullan.

## 3. Geliştirme: telefonda denemek (isteğe bağlı)

Yalnız deploy öncesi bir değişikliği telefonda görmek için. Geliştirme stack'i açık olmalı
(`docker compose ps` → `yaver-dev` çalışıyor).

```powershell
tailscale serve --bg --https=8443 http://127.0.0.1:8180   # geliştirme: ...ts.net:8443
tailscale serve status                                     # 443 (canlı) ve 8443 (geliştirme)
# iş bitince yalnız geliştirmeyi kapat (canlı açık kalır):
tailscale serve --https=8443 off
```

`off` reddedilirse açarken kullandığın bayrakların aynısını yaz ve sonuna `off` ekle. Sonra
`tailscale serve status` yalnız 443'ü göstermeli.

- Adres her zaman tam ad olmalı: `https://<makine>.<tailnet>.ts.net:8443`. Vite yalnız
  `.ts.net` adlarını kabul eder; kısa ad (`http://makine:8443`) "Blocked request" verir.
- İlk açılış yavaştır (Vite derlenmemiş dosyaları tek tek gönderir). Kod kaydedince sayfa
  kendini yeniler; yenilemezse aşağı çekip yenile.
- Geliştirmede zamanlayıcı kapalı: brifing / check-in bildirimi gelmez. Denemek için
  *Deneme bildirimi gönder* ya da ofisteki *Ritüeller (yalnızca geliştirme)* düğmeleri
  (gerçek LLM çağrısı yapar, küçük bir maliyeti vardır).

## 4. iPhone'da ana ekran uygulaması ve bildirimler

1. iPhone'da Tailscale açık ve bağlı.
2. Safari'de canlı adresi aç → giriş ekranı gelmeli.
3. Paylaş → **Ana Ekrana Ekle** → Ekle (geliştirme için adı **Yaver Dev** yap).
4. Yaver'i **ana ekrandaki simgeden** aç, parolanla gir (Safari'deki oturum geçmez).
5. Durum → Bildirimler → **Bildirimleri aç** → izin ver → **Deneme bildirimi gönder**.
   "1 cihaza gönderildi." yazar ve bildirim birkaç saniyede gelir.

Bildirim izni yalnız ana ekran uygulamasında istenebilir (iOS 16.4+); Safari sekmesinde kart
"önce Ana Ekrana Ekle" der. Bildirimler Apple'ın sunucusundan gelir, **gelmesi için Tailscale'in
açık olması gerekmez**; dokunup açmak için gerekir (Tailscale → *VPN On Demand* açık kalsın).

Canlıda kendiliğinden gelen bildirimler (`.env` saatleri, varsayılanlar):

| Saat | Başlık | Ne |
|---|---|---|
| 09:00 | Günaydın ☀️ | Standup + brifing |
| 12:00 | Takip: haber var mı? | Bekleyen takipler (Mentor başvuruları, Chrono diğerleri) |
| 18:00 | Sınav hazırlığı 📚 | Bir hafta kalan sınav için tekrar planı (varsa) |
| 21:00 | Akşam check-in 🌙 | Günün dersleri, sporu, görevleri |
| 21:15 | Gün sonu raporu 🌆 | Yaver'in defterlerden özeti |
| Pazar 20:00 | Haftalık plan taslağı | Gelecek hafta |

## 5. Telefondan test kontrol listesi

Canlı adreste, ana ekran uygulamasından. Bir madde olmazsa ekran görüntüsü + saat ile not al;
bilgisayarda `.\scripts\live.ps1 logs --tail 100 api` çıktısı da işe yarar.

**A. Bağlantı ve giriş**
- [ ] Tailscale bağlıyken canlı adres açılıyor, giriş ekranı geliyor
- [ ] Yanlış parola → "Parola yanlış."; doğru parola → Ofis açılıyor, üstte "Bağlı"
- [ ] Ofis başlığında "N / M çalışan masasında" (akış canlı; "yeniden bağlanıyor" kalmıyor)
- [ ] Tailscale **kapalıyken** adres açılmıyor (internete açık değil)
- [ ] `tailscale serve status` yalnız tailnet içi gösteriyor (funnel yok)

**B. Ana ekran uygulaması**
- [ ] Ana ekrana eklendi, simgeden tam ekran açılıyor (Safari çubukları yok)
- [ ] Uygulamayı kapatıp açınca yeniden parola sormuyor
- [ ] Yatay / dikey çevirince düzen bozulmuyor; ofis sahnesi yana kayıyor, çalışan listesi altta

**C. Sohbet ve Geri al**
- [ ] "yarın ne var?" → birkaç saniyede cevap
- [ ] "cuma 15'te deneme toplantısı ekle" → değişiklik kartı; Takvim'de görünüyor
- [ ] Kartta **Geri al** → Takvim'den kalkıyor
- [ ] Mikrofon: basılı tut, konuş → metin geliyor (HTTPS olmadan çalışmaz)

**D. Bildirimler**
- [ ] Durum → Bildirimler → *Bildirimleri aç* → izin → *Deneme bildirimi gönder* → geliyor
- [ ] Telefon kilitliyken de geliyor
- [ ] Tailscale **kapalıyken** de geliyor; dokununca (Tailscale açıkken) Yaver açılıyor
- [ ] Ertesi gün 09:00 brifing, 12:00 takip (bekleyen varsa), 21:00 check-in bildirimi geliyor
- [ ] Check-in mesajında **✓ Hepsi tamam** çalışıyor

**E. Ofis (O5)**
- [ ] Bir çalışana dokun → panel; *Ekranına bak* → yakınlaştırılmış ekran, ✕ ile kapanıyor
- [ ] Bir masaya dokun → aynı ekran açılıyor
- [ ] 23:00'ten sonra masalar boş ve sönük, başlıkta "Mesai dışı · açılış 08:00"
- [ ] Gece bir mesaj yaz → ilgili çalışan kapıdan gelip "Gece mesaisi: ..." diye çalışıyor, sonra gidiyor
- [ ] Hoparlör düğmesi: varsayılan kapalı; açınca bir iş başlarken hafif ses

**F. İsteğe bağlı**
- [ ] Takvim aboneliği: Durum → Takvim aboneliği → *Takvime ekle* → iPhone Takvim'de dersler
- [ ] Siri kısayolu: [cihaz-anahtari.md](cihaz-anahtari.md) (Faz 2)
- [ ] Geliştirme (:8443): açılıyor, uydurma veri, ayrı giriş, *Deneme bildirimi* geliyor;
      sonra `tailscale serve --https=8443 off` ve `tailscale serve status`'ta yalnız 443

ROADMAP Faz 1'in "iPhone'a push bildirimi düşüyor" maddesi D'nin ilk iki satırı geçince,
"Windows açılınca o günün brifingi geliyor" ve check-in maddeleri D'nin son iki satırı geçince
işaretlenebilir.

## Sorun giderme

| Belirti | Çözüm |
|---|---|
| Adres açılmıyor | iPhone'da Tailscale bağlı mı? Bilgisayar açık ve uyanık mı? `tailscale serve status` adres gösteriyor mu? Canlı çalışıyor mu (`.\scripts\live.ps1 status`)? |
| `Blocked request. This host ... is not allowed` | Geliştirmeyi kısa adla açıyorsun; tam `https://...ts.net:8443` adresini kullan. |
| Geliştirme açılıyor ama boş / eski | `docker compose ps`: `yaver-dev` açık mı? Kod değiştiyse sayfayı yenile. |
| Bildirim kartı "VAPID anahtarları yok" | `.env`'e üç VAPID satırı, sonra `.\scripts\live.ps1 up -d`. |
| *Deneme bildirimi* "Gönderilecek cihaz yok." | Bu uygulamada (bu adreste) *Bildirimleri aç* yapılmamış; canlı ve geliştirme ayrı abonedir. |
| Bildirim hiç gelmiyor | Ayarlar → Bildirimler → Yaver açık mı? Odak modu engelliyor mu? Uygulamayı ana ekrandan açıp *Kapat* → *Bildirimleri aç* ile yeniden abone ol. |
| Zamanlı bildirim geç geliyor | Bilgisayar uyumuş olabilir; uyanınca gelir (catch-up). Uyku ayarına bak (§1). |
