# Cihaz anahtarı: masaüstü uygulaması ve iPhone Siri kısayolu

`.env`'de `APP_PASSWORD` varsa Yaver her isteğe giriş ister. Tarayıcı bunu çerezle halleder; masaüstü uygulaması ve Siri kısayolu ise **cihaz anahtarı** kullanır:

- `yvk_` ile başlayan uzun bir anahtar. Sunucu yalnızca SHA-256'sını saklar, anahtarın kendisi bir kez görünür.
- Süresi dolmaz (tarayıcı oturumu 30 gün kullanılmayınca düşer, anahtar düşmez).
- Her cihaza ayrı anahtar ver; bir cihazı kaybedersen yalnızca onunkini iptal et.

## Anahtar oluşturma

1. Web'de giriş yap → **Durum** → **Cihaz anahtarları**.
2. Cihaz adı yaz (ör. `Masaüstü`, `iPhone Siri`) → **Cihaz anahtarı oluştur**.
3. Çıkan `yvk_…` anahtarını **Kopyala**. Bu ekrandan çıkınca bir daha görünmez; kaybedersen yenisini oluştur.
4. İptal: aynı kartta cihazın yanındaki **İptal et**. O cihaz hemen bağlanamaz olur.

## Masaüstü uygulaması

- İlk açılışta (ya da anahtar iptal edildiyse) sohbet paneli kendiliğinden **⚙ Ayarlar**'da açılır: "Yaver'e bağlanmak için bu bilgisayara bir cihaz anahtarı gerekiyor."
- **Cihaz anahtarı** kutusuna yapıştır → **Kaydet**. Uygulama anahtarı önce sunucuya sorar; kabul edilirse saklar (`%APPDATA%\com.yaver.desktop\session.json`).
- **Anahtarı unut** bu bilgisayardan siler; sunucudaki kaydı iptal etmek için web'deki **İptal et**'i kullan.

## iPhone Siri kısayolu

Telefonun Yaver'e ulaşabilmesi gerekir (Tailscale, `KURULUM_WINDOWS.md` → Tailscale serve). Adres örnekte `https://bilgisayar.tailnet.ts.net`.

**Kestirmeler** uygulaması → **+** → adı **Yaver'e söyle**. Sırayla şu eylemleri ekle:

1. **Metni Dikte Et** (Dictate Text): dil Türkçe, "Dinlemeyi Durdur: Duraklamadan Sonra".
2. **URL'nin İçeriğini Al** (Get Contents of URL):
   - URL: `https://bilgisayar.tailnet.ts.net/api/chat`
   - Yöntem: **POST**
   - Başlıklar:
     - `Authorization` = `Bearer yvk_…` (iPhone için oluşturduğun anahtar)
     - `Content-Type` = `application/json`
   - İstek Gövdesi: **JSON**, alan `message` (Metin) = *Dikte Edilen Metin*
3. **Sözlük Değerini Al** (Get Dictionary Value): anahtar `reply`, sözlük = *URL'nin İçeriği*.
4. **Metni Seslendir** (Speak Text) ya da **Sonucu Göster**: *Sözlük Değeri*.

Kullanım: "Hey Siri, Yaver'e söyle" → "yarın quiz var". Cevap sesli gelir; değişiklik web'de değişiklik kartıyla görünür ve oradan **Geri al** yapılabilir.

Notlar:
- Siri'den gelen mesaj ana sohbete düşer; ofiste ilgili çalışan çalışırken görünür.
- 401 dönerse anahtar yanlış ya da iptal edilmiş: web'de yenisini oluşturup 2. adımdaki başlığı güncelle.
- Anahtar kısayolun içinde düz metin durur; kısayolu paylaşma.
