# Venture: startup deposu (GitHub, salt okunur)

Venture, startup'ın GitHub deposuna her sabah 08:15'te bakar (`agents.yaml` → `github_watch`).
**Hiçbir şey yazmaz:** istemci yalnızca GET isteği gönderir, başkasını kodda reddeder.

## Kurulum

1. github.com → Settings → Developer settings → **Fine-grained tokens** → Generate new token.
   - Repository access: **Only select repositories** → startup deposu.
   - Permissions (Repository): **Contents**, **Issues**, **Pull requests**, **Metadata** → *Read-only*.
2. `.env`:
   ```
   GITHUB_TOKEN=github_pat_...
   GITHUB_STARTUP_REPO=sahip/depo-adi
   ```
   `GITHUB_STARTUP_REPO` tam olarak `sahip/depo` olmalı (github.com adresini yapıştırmak da olur).
   Geçersiz ya da yer tutucu bir değer uygulamayı durdurmaz; entegrasyon "bekliyor" kalır ve
   api logunda uyarı görünür.
3. `docker compose up -d api` (ayarlar açılışta okunur).
4. Sabahı beklemeden denemek için (giriş açıksa bir cihaz anahtarıyla):
   ```
   curl -X POST -H "Authorization: Bearer yvk_..." http://localhost:8000/api/jobs/shift:startup:github_watch/run
   ```
   Sonuç Venture'ın defterine düşer (Ofis → Venture).

## Ne yapar?

- **İlk sefer:** depo haritasını deftere yazar: README özeti, hafta klasörleri (`hafta-03`,
  `week_3`...), toplantı notları (yolunda `toplanti`, `meeting`, `notes`, `notlar` geçen
  `.md`/`.txt`), açık issue'lar, milestone'lar, son 7 günün commit'leri, ekip (katkı verenler).
- **Her sabah:**
  - Son hafta klasörüne kim commit atmış ("teslim eden"), kim henüz atmamış.
  - Toplantı notlarındaki ve issue'lardaki tarihli satırlar ("25 Kasım: demo videosu teslim",
    "Son tarih: 24.11.2026") ve tarihli milestone'lar → takvime tüm gün **teslim** + o güne
    **takip**. Bir kez eklenir (tekrar eklemez). Yılı yazmayan tarih bugüne en yakın yıl sayılır.
  - 3 gün içindeki bir iş için ilgili dosya ya da PR yoksa **hatırlatma**; varsa (PR başlığı /
    dosya adı işin kelimelerini içeriyor, ya da PR "#4"e atıf yapıyor) takip **kapanır**.
- Sabah notunun sonunda değişikliğin kimliği yazar; sohbette "GitHub'dan eklenenleri geri al"
  ya da o kimlikle geri alabilirsin.

Token yoksa Venture günde bir kez "GitHub entegrasyonu bekliyor" notu düşer.
