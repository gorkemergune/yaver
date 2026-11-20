# Windows'ta kurulum ve iPhone'dan erişim

Yaver bilgisayarında Docker'da çalışır. Telefonundan **Tailscale** üzerinden, HTTPS ile açarsın. Uygulama internete açılmaz, yalnızca senin cihazların görür.

İlk kurulum (Docker Desktop, `.env`, ilk sohbet) için README'deki *Quick start* bölümüne bak. Bu belge ondan sonrasını anlatır:

1. Günlük kullanım için prod modu
2. Parola
3. Tailscale ile HTTPS adresi
4. iPhone'da uygulama (PWA) ve bildirimler
5. Takvim aboneliği (ICS)

## 1. Günlük kullanım: prod modu (önerilen)

İki çalışma şekli var. İkisi de **aynı veritabanını** kullanır; aralarında geçince kayıtların kaybolmaz.

| | Geliştirme (`docker compose up -d`) | Prod (`docker compose -f docker-compose.yml up -d`) |
|---|---|---|
| Web | Vite dev sunucusu, kod değişince anında yenilenir | nginx, derlenmiş ve küçültülmüş dosyalar |
| Telefonda açılış | Yavaş (yüzlerce küçük dosya, Tailscale üzerinden) | Hızlı (birkaç dosya, önbellekli) |
| Bilgisayar yeniden başlayınca | Container'lar **kendiliğinden açılmaz** | Açılır (`restart: unless-stopped`) |
| API / DB portları (8000, 5432) | Bilgisayara açık | Kapalı, yalnızca 8080 (web) açık |
| `pytest`, `ruff`, `mypy` | Çalışır | Çalışmaz (prod imajında geliştirme araçları yok) |

**Öneri:** Her gün kullanırken prod modunda çalış. Kod üzerinde çalışırken geliştirme moduna geç, bitince prod'a dön.

Prod'a geçmek için:

```powershell
cd C:\Users\PC\Desktop\yaver
docker compose -f docker-compose.yml up -d --build
docker compose -f docker-compose.yml exec api alembic upgrade head   # yeni şema değişikliği varsa
.\scripts\smoke.ps1 -NoChat                                          # hepsi OK olmalı
```

- `--build` ilk seferde birkaç dakika sürer. Sonraki seferlerde yalnızca değişen kısım derlenir.
- Açıldıktan sonraki birkaç saniye `/api` 502 dönebilir; API ayağa kalkınca düzelir.
- Geliştirme moduna dönmek için `docker compose up -d` yeter (override dosyası otomatik yüklenir).
- Kodu güncelledikten sonra (`git pull` ya da yeni commit'ler) prod komutunu `--build` ile tekrar çalıştır. Yoksa eski sürüm çalışmaya devam eder.

Docker Desktop → Settings → General → **Start Docker Desktop when you sign in** açık olsun. Böylece bilgisayar açılınca Yaver de gelir.

## 2. Parola (telefona açmadan önce)

Tailscale'e bağlı her cihaz adresi açabilir. Bu yüzden önce parola koy.

1. `.env` dosyasında `APP_PASSWORD=` satırına gerçek bir parola yaz. `change-me` "parola yok" sayılır.
2. API'yi yeniden başlat: `docker compose -f docker-compose.yml up -d` (geliştirme modundaysan `docker compose up -d`).
3. `http://localhost:8080`'i aç; giriş ekranı çıkmalı.

Oturum açık kalır ve 30 gün kullanılmazsa kapanır (`SESSION_DAYS`). Masaüstü uygulamasında: ⚙ → Parola → Giriş yap.

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
| `Blocked request. This host ... is not allowed` | Eski bir Vite ayarı kalmış. `git pull`'dan sonra `docker compose up -d web` çalıştır. |
| Birkaç saniye `502 Bad Gateway` | API yeniden başlıyor; bekle. Sürerse `docker compose logs api --tail 50`. |
| Her açılışta parola soruyor | Ana ekran uygulamasından mı açıyorsun? Safari ile ana ekran uygulamasının oturumları ayrıdır. |
| Bildirim düğmesi yok ya da hata veriyor | Uygulamayı ana ekrandan aç (iOS 16.4+). Ayarlar → Bildirimler → Yaver açık mı? |
| Takvim güncellenmiyor | Tailscale bağlıyken bekle (bir saate kadar). Ayarlar → Takvim → Hesaplar → abonelik → adres doğru mu? |
| Değişikliklerim prod'da görünmüyor | `docker compose -f docker-compose.yml up -d --build` (`--build` şart). |
