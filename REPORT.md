# REPORT — 21 Kasım 2026 (gece)

Branch: `feat/mentor-o5` (`main` `5b40ac3`'ten) · Push yok · Canlıya deploy yok.
Yalnız `yaver-dev` (8180/8100/5532) ve kendi izole e2e kopyam (`yaver-e2e-o5`) kullanıldı.
`yaver-live`'a, gerçek veritabanına ve çalışan eski `yaver-*` stack'ine dokunulmadı.
Önceki rapor (akşam: A/B, QA Y1–Y3, O1–O4) git geçmişinde: `git show e205293:REPORT.md`.

## Özet

| # | İş | Commit | Doğrulama |
|---|---|---|---|
| 1 | Kariyer takipleri Mentor'un | `7b50887` | Yönlendirme seti **18/18** (önce 17/18); gerçek konuşma #33 takibin sahibini de kontrol ediyor |
| 2a | QA O5: tek konuşma, tek konuşan | `31e093e` | pytest (422 + koordinatör reddi + bilinmeyen id) |
| 2b | QA D6: DST'de yerel saat | `694f7ff` | Europe/Berlin testleri (2027 ilkbahar ve sonbahar geçişi) |
| 3 | O5 ofis cilası | `71aa913` | Backend testleri sabit saatle + yeni e2e `office-hours.spec.ts` + ekran görüntüleri |
| 4 | Telefon rehberi ve kontrol listesi | `093fef8` | Belge (Tailscale kurulmadı) |

Her maddeden sonra: smoke testi, LLM'siz e2e, geliştirme API'si `(healthy)` + `/api/health/ready` 200.
Son durum: backend **1092** test, ruff/mypy temiz; web `npm run check` temiz (**67** vitest);
e2e **22/22** (20 eski + 2 yeni).

## 1. Mentor'un kariyer takipleri

- `followups.owner_id`: takibi ekleyen çalışan. NULL = Chrono'nun.
- Migration (`5c2d8e1f0a37`) eski satırları da dolduruyor:
  - başlığında staj / başvuru / mülakat / intern / iş teklif geçenler → `career`
  - `[github:` notlu olanlar → `startup`
- Sınıflandırıcı: staj / iş başvurusunun takibi ve haberi artık `career` niyeti. Örnekler:
  "dönüş bekliyorum, her gün sor", "kabul geldi". Hackathon gibi diğer takipler Chrono'da kaldı.
- Mentor'un 10:00 `followup_watch`'ı yalnız kendi takiplerine bakıyor. Önce herkesinkini yazıyordu.
- Öğlen takip mesajı sahibine göre gruplu: "**Mentor** · Başvurular: haber var mı?" ve
  "**Chrono** · Takip: ...".
- Canlı ölçüm (test DB'si):
  - yönlendirme **18/18** ($0.016)
  - gerçek konuşma seti tur başına 40/41; iki hata da bu değişiklikle ilgisiz (aşağıda),
    tekrar koşuda 3/3 × 2
  - toplam ~$0.08

## 2. QA O5 ve D6

İkisi de bir saatin içinde çözülebilecek boyuttaydı, yaptım.

**O5:**
- Doğrudan sohbet uçları zaten 422 veriyordu.
- Açık kalan taraf ana sohbetti: `/api/chat` bir çalışanın konuşma id'siyle o konuşmaya
  yazabiliyordu. Artık `422 not_the_main_chat` dönüyor.
- `Coordinator` da başkasının konuşmasını reddediyor; API'yi atlayan bir yol kalmadı.
- Bilinmeyen id için QA 404 önermişti. Bunu bilerek yapmadım: yeni konuşma açılıyor
  ve bu artık loglanıyor. Sebebi, istemcinin cevaptaki yeni id'yi zaten saklaması.
  DB sıfırlanınca 404 + yeniden deneme yerine sohbet kesintisiz sürüyor.

**D6:**
- `core/localtime.local_datetime`, kodda geçen bütün `combine(..., tzinfo=tz)` kullanımlarının
  yerini aldı:
  - saat ileri alınırken atlanan saat → saatin atladığı yer (02:30 → 03:30)
  - iki kez yaşanan saat → ilki
- Süreler gerçek geçen zamanla hesaplanıyor: ders saati sayısı, sınav tekrar planındaki boş
  saatler.
- Europe/Istanbul'da hiçbir şey değişmedi (testte 24 saatin hepsi karşılaştırıldı).

## 3. O5 – Ofis cilası

- **Mesai saatleri:** `agents.yaml` → `office.open_at` / `close_at` (varsayılan 08:00–23:00;
  ikisi aynıysa ofis hep açık).
  - Saat dışında boştaki çalışan `off` olur: kapıdan çıkıp gider, masası sönük.
  - Gece bir istek gelirse ilgili çalışan kapıdan gelir. Durumu "Gece mesaisine geliyor",
    sonra "Gece mesaisi: <iş>". Masası çalışanın renginde yanar, iş bitince yine gider.
  - Başlıkta "Mesai dışı · açılış 08:00" yazar.
- **Backend (ilke 8: sahte değil):**
  - Tek yazma noktası `Office.set_state`, boşta durumunu saate göre `break` ya da `off` seçer.
  - Geçişleri `Office.refresh_hours` yapar; her snapshot'ta ve akışın 15 sn'lik ping'inde
    çalışır, zamanlayıcı gerekmez (geliştirmede zamanlayıcı kapalı).
  - Değişiklik `hours` SSE olayıyla yayınlanır; snapshot da `hours` taşır.
- **Masaya tıklayınca** (ya da paneldeki *Ekranına bak*) ekran masadan büyüyerek açılır.
  - İçerik: durum, araç, başlangıç saati, elindeki iş (yoksa son bitirdiği), defterden iki satır.
  - Mesai dışında "Ekran kapalı".
  - Esc / ✕ / dışına tıklama ile kapanır.
- **Ses:** Web Audio ile üretilen dört hafif ses (iş başladı, toplantı, seni bekliyor, bitti).
  Dosya yok. En fazla 300 ms'de bir çalar, gizli sekmede çalmaz. Varsayılan kapalı,
  başlıktaki hoparlörle açılır, tarayıcıda hatırlanır.
- **Yapılmayan:** "performans" ayrıca ele alınmadı. Ölçülen bir sorun yok; ROADMAP O5'te not edildi.

## 4. Telefon (`docs/tr/telefon.md`)

- **Canlı / geliştirme:**
  - Telefon her gün canlıyı kullanır (443 → 8080).
  - Geliştirme yalnız deploy öncesi denemek için, kendi portunda açılır (8443 → 8180) ve sonra
    tek başına kapatılır. `tailscale serve reset` canlıyı da kapatır, belgede uyarısı var.
- **İki adres = iPhone'da iki ayrı uygulama:** giriş, bildirim izni ve abonelik ayrı. Geliştirme
  ikonunun adı "Yaver Dev" olmalı.
- **Önkoşullar:** parola, VAPID anahtarları (sonradan değiştirilmemeli), bilgisayarın uyumaması.
- Zamanlı bildirimlerin tablosu ve kontrol listesi var:
  - Kontrol listesinin bölümleri: bağlantı, ana ekran uygulaması, sohbet + Geri al, mikrofon,
    bildirimler, ofis, isteğe bağlılar.
  - Hangi satırların ROADMAP Faz 1'deki açık maddeleri kapattığı yazılı.
- `KURULUM_WINDOWS.md`'deki iki çelişki düzeltildi: "geliştirme de telefonda çalışır" notu ve
  "Blocked request" satırı.
- `tailscale serve` sözdizimi resmi belgeden alındı (ikinci HTTPS portu, tekini `off`). Tailscale
  bu makinede kurulu değil, komutları çalıştırmadım. Belgenin açıkça yazmadığı tek şey `off`'un
  bayrak tekrarı istemesi; rehberde "reddedilirse aynı bayraklarla `off`" diye yazdım.

## Bilmen gerekenler

1. **Geliştirme stack'i şu an bu worktree'den çalışıyor:** `C:\Users\PC\Desktop\yaver-qa`, branch
   `feat/mentor-o5`.
   - Kodun yeni migration'ı görmesi için gerekliydi. Geliştirme DB'si `5c2d8e1f0a37`'de.
   - `main`'de bu revizyon yok: merge'den önce ana klasörden `alembic` çalıştırırsan
     "revision bulunamadı" der.
   - Merge'den sonra ana klasörde `docker compose up -d` geliştirmeyi oraya geri alır.
2. **Canlıda migration deploy ile gelir:** önce yedek alınır ve prova yapılır.
   - Eski takipler başlıklarına göre sahiplenir. Gerçek DB'deki "Iceberg staj başvurusu dönüşü"
     Mentor'a geçmeli.
   - Deploy'dan sonra öğlen takip mesajında bunu görebilirsin.
3. **Yerel config:**
   - Worktree'ye `config/agents.yaml` ve `providers.yaml` kopyaladım (gitignored, commit'lenmedi).
   - Kendi `agents.yaml`'ında `office.open_at` / `close_at` yok; varsayılan 08:00–23:00 geçerli.
     Farklı istersen ekle (örnek dosyada var).
   - Chrono'nun `domain` metnine "staj / iş başvuruları hariç" eklemek istersen örnek dosyada var.
     Yönlendirmeyi niyet sınıflandırıcısı yaptığı için şart değil.
4. **Bir kaza ve dersi:** canlı konuşma seti çalışırken aynı test DB'sinde (`yaver_test`) birim
   testlerini başlattım.
   - Bir mesaj "deadlock detected" aldı (r2 #3).
   - Takılan koşuyu öldürünce PostgreSQL'de yetim bir sıfırlama sorgusu kaldı ve canlı seti
     dondurdu. `pg_terminate_backend` ile yalnız onu kapattım, set tamamlandı.
   - Sonraki birim testlerini ayrı bir DB'de (`_unit_test`) koştum, sonra o DB'leri sildim.
   - r1 #17 ("27 kasım cuma 10da math221 vizesi var") bir kez tarihi tanımadı. Bu prompt
     değişikliğiyle ilgisiz bir model dalgalanmasıydı; tekrar koşuda #3, #17, #33 2 turda 6/6.
5. **iPhone'da ses:** Web Audio, iPhone'un sessiz anahtarına uyar. Sessiz modda ofis sesleri
   çıkmaz.
6. **Temizlik:**
   - Kendi e2e kopyamı (`yaver-e2e-o5`: 8091/8002/5434) volume ve imajlarıyla kaldırdım.
   - `yaver-e2e`'ye dokunmadım (çalışmıyordu).
   - Ekran görüntüleri yalnız `e2e/test-results/` altında (gitignored). Oradaki "Bağlantı koptu"
     yazısı mock'lu akışın kapanmasından.

## Commit'ler (push yok)

```
093fef8 docs(tr): telefon.md - Tailscale, iPhone uygulaması, Web Push (canlı / geliştirme), kontrol listesi
71aa913 feat(office): O5 - mesai saatleri, gece mesaisi, masa ekranı yakınlaştırma, ses
694f7ff fix(time): QA D6 - DST'de yerel saatler, gerçek süreler
31e093e fix(chat): QA O5 - ana sohbet bir çalışanın konuşmasına yazamaz
7b50887 feat(career): staj / iş başvurusu takipleri Mentor'un (owner_id, yönlendirme 18/18)
```
