# Windows'ta kurulum ve iPhone'dan erişim

Yaver bilgisayarında Docker'da çalışır. Telefonundan **Tailscale** üzerinden, HTTPS ile açarsın. Uygulama internete açılmaz, yalnızca senin cihazların görür.

İlk kurulum (Docker Desktop, `.env`, ilk sohbet) için README'deki *Quick start* bölümüne bak. Bu belge ondan sonrasını anlatır:

1. Günlük kullanım: canlı kurulum
2. Parola
3. Tailscale ile HTTPS adresi
4. iPhone'da uygulama (PWA) ve bildirimler
5. Takvim aboneliği (ICS)

## 1. Günlük kullanım: canlı kurulum

İki ayrı kurulum var (ayrıntı ve geçiş: [canli-ve-gelistirme.md](canli-ve-gelistirme.md)):

| | **Canlı** (`yaver-live`) | **Geliştirme** (`yaver-dev`, `docker compose up -d`) |
|---|---|---|
| Adres | http://localhost:8080 (Tailscale de buraya) | http://localhost:8180 |
| Veritabanı | Gerçek veri (`yaver_pgdata`) | Ayrı test veritabanı |
| Web | nginx, derlenmiş dosyalar, telefonda hızlı | Vite dev sunucusu, kod değişince yenilenir |
| Bilgisayar yeniden başlayınca | Kendiliğinden açılır | Açılmaz |
| Güncelleme | `.\scripts\deploy-live.ps1` (test + yedek + geçiş) | Kaydettiğin an |

Her gün canlıyı kullan. Kodu güncelledikten sonra (`git pull` ya da yeni commit'ler):

```powershell
cd C:\Users\PC\Desktop\yaver
.\scripts\deploy-live.ps1          # main'in son commit'i: test eder, yedekler, geçer; olmazsa eskide kalır
.\scripts\live.ps1 status
.\scripts\smoke.ps1 -NoChat        # hepsi OK olmalı
```

**Yepyeni bir kurulumda** (henüz `yaver_pgdata` volume'ü yoksa) ilk deploy'u
`.\scripts\deploy-live.ps1 -NewDatabase` ile çalıştır; boş veritabanını o oluşturur.

Docker Desktop → Settings → General → **Start Docker Desktop when you sign in** açık olsun. Böylece bilgisayar açılınca Yaver de gelir.

## 2. Parola (telefona açmadan önce)

Tailscale'e bağlı her cihaz adresi açabilir. Bu yüzden önce parola koy.

1. `.env` dosyasında `APP_PASSWORD=` satırına gerçek bir parola yaz. `change-me` "parola yok" sayılır.
2. Canlıyı yeniden başlat: `.\scripts\live.ps1 up -d` (`.env` değişikliği için `restart` yetmez).
3. `http://localhost:8080`'i aç; giriş ekranı çıkmalı.

Oturum açık kalır ve 30 gün kullanılmazsa kapanır (`SESSION_DAYS`). Masaüstü uygulaması ve iPhone Siri kısayolu süresi dolmayan bir **cihaz anahtarıyla** bağlanır: web'de Durum → Cihaz anahtarları → "Cihaz anahtarı oluştur", masaüstünde ⚙ → Cihaz anahtarı (adımlar: `cihaz-anahtari.md`).

## 3. Tailscale ile HTTPS adresi

1. **Bilgisayara** Tailscale'i kur (<https://tailscale.com/download/windows>) ve giriş yap.
2. **iPhone'a** App Store'dan Tailscale'i kur ve **aynı hesapla** giriş yap. VPN izni istenince izin ver.
3. Tailscale yönetim panelinde (<https://login.tailscale.com/admin/dns>) iki ayarı aç:
   - **MagicDNS**
   - **HTTPS Certificates**
4. Bilgisayarda PowerShell'de:

   ```powershell
   tailscale serve --bg 8080
   ```

   Çıktıda adresin yazar, örneğin `https://masaustu.tail1234.ts.net/`. `--bg` ayarı kalıcı yapar; bilgisayar yeniden başlayınca da geçerlidir.
5. Kontrol: `tailscale serve status`. Kapatmak için `tailscale serve reset`.

Notlar:

- İlk açılışta sertifika alınırken birkaç saniye beklenebilir.
- **`tailscale funnel` kullanma.** Funnel adresi herkese, internete açar; `serve` yalnızca senin cihazlarına açar.
- `tailscale serve` HTTPS'i kendisi sağlar ve isteği `http://localhost:8080`'e iletir. Windows güvenlik duvarında ek kural gerekmez.
- Geliştirme modunda da çalışır (Vite `*.ts.net` adreslerini kabul eder, sıcak yenileme de bağlanır). Yine de telefonda açılış yavaştır.

## 4. iPhone'da uygulama ve bildirimler

1. iPhone'da Tailscale açık ve bağlı olsun.
2. **Safari**'de `https://masaustu.tail1234.ts.net` adresini aç (kendi adresin).
3. Paylaş → **Ana Ekrana Ekle** → Ekle.
4. Yaver'i **ana ekrandaki simgeden** aç ve parolanla giriş yap. Ana ekran uygulamasının oturumu Safari'den ayrıdır; Safari'de giriş yapmış olsan da burada bir kez daha girersin.
5. Bildirimler (iOS 16.4+): Durum sekmesi → Bildirimler → **Bildirimleri aç** → izin ver → **Deneme bildirimi gönder**. Bildirim birkaç saniye içinde gelmeli.

Bilmen gerekenler:

- **Bildirim gelmesi için Tailscale'in açık olması gerekmez.** Bildirimler Apple'ın sunucusundan gelir. Bildirime dokunup uygulamayı açmak içinse Tailscale bağlı olmalıdır.
- Tailscale uygulamasında **VPN On Demand** açarsan bağlantı hep açık kalır.
- Bildirim izni yalnızca ana ekran uygulamasında istenebilir; Safari sekmesinde düğme çalışmaz.
- Uygulama güncellenince bir sonraki açılışta yeni sürüm gelir. Gelmezse uygulamayı uygulama değiştiriciden kapatıp yeniden aç.

## 5. Takvim aboneliği (ICS)

Dersler (iptaller ve taşımalar işlenmiş hâliyle), sınavlar, toplantılar ve etkinlikler iPhone Takvim'inde görünür. Takvim yalnızca okur; değişiklikleri yine sohbetten yaparsın.

1. iPhone'daki Yaver'de: Durum → **Takvim aboneliği** → **Takvime ekle**.
2. iOS "Abone ol" diye sorar → Abone ol → Ekle.

Bağlantı açılmazsa elle ekle: **Kopyala** ile adresi al. Sonra Ayarlar → Takvim → Hesaplar → Hesap Ekle → Diğer → **Takvim Aboneliği Ekle** yolunu izle ve adresi yapıştır.

Bilmen gerekenler:

- Bağlantıda gizli bir anahtar var. Parola sormaz; bağlantıyı bilen takvimi görür. Yanlışlıkla paylaşırsan **Yeni bağlantı** de, eskisi hemen çalışmaz olur.
- iPhone takvimi **kendisi** indirir, bu yüzden yalnızca Tailscale bağlıyken yenilenir. Bağlı değilken son indirdiği hâli gösterir.
- Yaver takvime "saatte bir yenile" der; iOS bunu kendi aralığına göre uygular. Bir değişikliğin takvimde görünmesi bir saate kadar sürebilir.
- **Mac'te** (Takvim → Dosya → Yeni Takvim Aboneliği) konum olarak **"Bu Mac'te"** seç, iCloud seçme. iCloud'u seçersen takvimi Apple'ın sunucusu indirmeye çalışır ve Tailscale adresine ulaşamaz.

## Sorun giderme

| Belirti | Çözüm |
|---|---|
| Telefonda adres açılmıyor | iPhone'da Tailscale bağlı mı? Bilgisayar açık ve uyanık mı (uyku modu bağlantıyı keser)? `tailscale serve status` adres gösteriyor mu? |
| `Blocked request. This host ... is not allowed` | Geliştirme sunucusunu (8180) telefondan açıyorsun; telefonda canlıyı (8080) kullan. |
| Birkaç saniye `502 Bad Gateway` | API yeniden başlıyor (deploy sırasında 20-40 sn); bekle. Sürerse `.\scripts\live.ps1 logs --tail 50 api`. |
| Her açılışta parola soruyor | Ana ekran uygulamasından mı açıyorsun? Safari ile ana ekran uygulamasının oturumları ayrıdır. |
| Bildirim düğmesi yok ya da hata veriyor | Uygulamayı ana ekrandan aç (iOS 16.4+). Ayarlar → Bildirimler → Yaver açık mı? |
| Takvim güncellenmiyor | Tailscale bağlıyken bekle (bir saate kadar). Ayarlar → Takvim → Hesaplar → abonelik → adres doğru mu? |
| Değişikliklerim canlıda görünmüyor | Commit'lendi ve `main`'de mi? Sonra `.\scripts\deploy-live.ps1`. `.\scripts\live.ps1 status` hangi commit'in çalıştığını gösterir. |
