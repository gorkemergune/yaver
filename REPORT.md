# Rapor — 22 Kasım 2026 (Venture/GitHub + ek kuyruk)

Her şey `main`'de (son commit `0bb28a9`). Push yok, deploy yok. Yalnız `yaver-dev` ve geçici `yaver-e2e` kullanıldı; `yaver-live`'a ve gerçek DB'ye dokunulmadı. `.env`'e de dokunmadım (okuyamıyorum da). Önceki rapor: `git show bd40f80:REPORT.md`.

Her maddeden sonra yapılan kontroller (hepsi yeşil):
- pytest: smoke dahil, son durumda **1204** test
- her modül tek başına import: **152/152**
- LLM'siz e2e: **22/22**
- web `npm run check`: 68 test; masaüstü `npm run check` + `cargo check`
- dev `/api/health/ready`: 200

Her madde ayrı dal; bitince `main`'e merge.

## Özet

| # | İş | Commit | Doğrulama |
|---|---|---|---|
| A1 | Yerel config overlay (`agents.yaml` / `providers.yaml` example'ın üstüne biner) | `e00621a` | overlay testleri; senin gerçek yerel dosyalarınla denendi |
| A2 | Venture'ın salt okunur GitHub araçları (6 araç) | `e090fa7` | sahte GitHub ile testler |
| A4 | Eksik ayar adıyla söyleniyor | `b735493` | testler; dev'de gerçek `.env` ile |
| A3 | Startup istekleri Venture'a, handoff'ta pes yok | `48401af`, `1e43fdc` | yönlendirme testleri |
| A5 | Canlı regresyon (canlıdaki cümle + 5 benzeri) | `8409341` | son durumda **12/12** |
| 1 | Gerçek repo kontrolü | `b75ca9c` | dev, gerçek token, salt okunur |
| 2 | 👎 Hatalı → bug_reports, `export-bugs.ps1` | `8f85a34` | API testleri, dev'de dışa aktarma, salt okunur kanıtı |
| 3 | Raporlar sekmesi | `5bcc91d` | API testi, masaüstü ve telefon ekran görüntüsü |
| 4 | Pes etmeme denetimi + 60 cümle | `37871b9` | 2 tur **59/60 + 60/60 (%99)** |
| 5 | Bu akşamki NEXA toplantısı | `0bb28a9` | testler + dev'de gerçek model |

**LLM harcaması:**
- Ek kuyruk: ≈ **$0.22** (bütçe $1.5). Kalemler: 60 cümle × 2 tur, iki kez ($0.086 + $0.089); 19 yeni cümlenin ilk turu ($0.018); dev denemeleri (<$0.01); startup seti ($0.013).
- Venture/GitHub düzeltmesi: ≈ $0.06.

## Venture: neden bozuktu, ne oldu

Canlıdaki cümle ("bu akşamki NEXA toplantısında üyeler week3'te …") üç ayrı nedenle düştü:
1. Yerel `config/agents.yaml` eskiydi ve araç listeleri ondan okunuyordu. Venture'da GitHub aracı, Scholar'da `get_exam_scope` yoktu.
   - Artık araçlar, mesai işleri ve model hep example'dan geliyor.
   - Yerel dosya yalnız isim, renk, kişilik, alan, masa, mesai saati gibi görünen alanları değiştirir.
   - Farklar açılışta WARNING olarak loglanıyor. Senin dosyanda: academic/startup `tools ignored`; `material_map`/`source_notes` example'dan.
2. "taslak" kelimesi isteği Creator'a gönderdi. Creator "alanım değil" dedi ama `handoff` aracını çağırmadı; Yaver de pes etti.
   - Artık repo/weekN geçen bir parça Venture'ın.
   - Sözle "alanım değil" de handoff sayılıyor.
   - Venture bir repo isteğini geri verirse bir kez daha ona gidiyor.
3. `.env`'de `GITHUB_STARTUP_REPO` hâlâ yer tutucu (`gorkemergune/<startup>`). Artık bu, arayüzde uyarı bandı olarak ve Venture'ın cevabında adıyla söyleniyor.

## 1. Gerçek repo kontrolü ve Venture'ın taslağı

- **Senin cümlen** (dev, gerçek model, `.env` olduğu gibi):
  > Venture: week3 özetini çekemedi, çünkü GitHub deposu ayarı hatalı. `GITHUB_STARTUP_REPO` değeri "gorkemergune/<startup>" olarak girilmiş, oysa "owner/name" biçiminde (ör. acme/startup) olmalı. Bu ayarı düzeltince toplantı taslağını hemen hazırlayabileceğini söyledi.
- **`github/gorkemergune/startup` ile:**
  > Venture: Week3 taslağını hazırlayamadı. "gorkemergune/startup" deposuna GitHub erişemiyor; depo adı yanlış olabilir ya da GITHUB_TOKEN bu depoya yetkili değil.
- **Token'ın gördüğü 55 depoda üye bazlı weekN yok.** Bu yüzden gerçek NEXA deposuyla taslak çıkaramadım.
  - Nexa ile ilgili olanlar: `nexa-lab-ai/nexa-bench` ve `nexa-tr/website`; ikisinde de week klasörü yok.
  - weekN yalnız ders depolarında var (`cpp-foundations/doc/week01-12`).
  - Sonuç: depo ya başka bir adda, ya da fine-grained token'ın kapsamı dışında.
- **Gerçek bir depoda yapıyı anlama düzeltmeleri** (`cpp-foundations` week03 üzerinde denendi):
  - Hepsi tek kişinin dosyasıysa "bunlar üye değil, parça" deniyor; üye uydurulmuyor.
  - README'si olmayan klasörde PDF'in ilk sayfası okunuyor.
  - Üye klasörü adı commit yazarıyla eşleşiyor (ali → ali-dev, deniz → "Deniz Kaya").
  - Yalnız `.gitkeep` olan klasör "boş" sayılıyor.
  - Geçen hafta teslim edip bu hafta klasörü olmayan ayrıca yazılıyor.
- **Karşılaştırma için sahte repoda çıkan taslak** (week1-3, 4 üye, canlı setteki ilk cümle):
  > Venture week3 taslağını hazırladı. İşte bu akşamki NEXA toplantısı için taslak:
  > **Week 3 – MVP Prototipleri Sunum Taslağı**
  > - **Ali Demir (ali-dev):** `ali/` klasöründe FastAPI ile `/recommend` endpoint'i yazmış. Öğrencinin ilgi alanlarına göre 5 etkinlik öneriyor, veri olarak 120 kulüp etkinliği kullanılmış. (Son commit: 21 Kasım, "recommend endpoint")
  > - **Deniz Kaya (dnz42):** `deniz/` klasöründe anket verisiyle kullanıcı segmentasyonu denemiş; 4 segment çıkmış: sosyal, akademik, spor, sanat.
  > - **Zeynep Yıldız (zeynepy):** HTML + Tailwind ile landing page ve bekleme listesi formu; formda 37 kişi kayıt olmuş.
  > - **Mert Can (mertc):** rakip analizi; Eventbrite, kulüp Instagram sayfaları ve okul portalı. Farkı kişiye özel öneri.
- karar: Gerçek depo okunamadığı için canlıda bu akşam alacağın cevap yukarıdaki "ayar hatalı" cevabı olur. Düzeltmesi aşağıda, "Deploy sonrası" bölümünde.

## 2. Hata bildirimi (👎 Hatalı)

- Web sohbetinde, ofis panelinin doğrudan sohbetinde ve masaüstü mini sohbette her cevabın altında: 👎 Hatalı → kısa not → Kaydet → "Kaydedildi (hata #N)".
- `bug_reports` tablosu şunları tutuyor:
  - mesaj, cevap, cevaplayan çalışan
  - araçlar (hataları, handoff alanı/nedeni) ve yönlendirme
  - o cevabın log satırları, not, kaynak (web/desktop), durum
- `scripts\export-bugs.ps1`: canlıdaki açık raporları tek dosyaya yazar: `docs\bugs\bugs-<zaman>.md`. Seçenekler: `-All`, `-Since 2026-11-20`, `-Project`.
  - Salt okunur oturumda çalışıyor. Dev'de denedim; bir silme denemesi "read-only transaction" hatasıyla reddedildi.
- karar: CLAUDE.md'deki "UI'de tek buton Geri al" kuralına ikinci istisna (👎). Kullanıcı verisi değil, change_log'a girmez.
- karar: araç izi her cevabın `messages.meta` alanında: yönlendirme, araçlar, hatalar, handoff'lar, maliyet. Model bunu görmez.
- karar: log özeti bellekteki son 400 satırdan; API yeniden başlayınca boşalır.
- karar: `docs/bugs/` gitignore'da (sohbet içeriği).
- karar: kaydedilmemiş (akışı kopmuş) bir cevap da raporlanabiliyor; istemci ekrandakini gönderiyor.

## 3. Raporlar sekmesi

- Yeni sekme **Raporlar**: Gün / Hafta seçimi, ‹ › ile dönem değiştirme. Gösterdikleri:
  - Çalışan başına: senden gelen istek, Yaver'den gelen, mesai işi, başarısız, geri verdi, araç hatası, maliyet.
  - Başarısız ve geri verilen istekler, nedenleriyle: alan, "sözle mi araçla mı".
  - Yönlendirme kararları: mesaj → niyet → çalışan.
  - Açık hata raporları.
- API: `GET /api/reports?period=day|week&date=`.
- karar: "boş Raporlar sekmesi" kodda yoktu; üst menüye yeni sekme olarak ekledim. Telefonda alt menü 6 sütun oldu.
- karar: yönlendirme ve handoff verisi bu sürümden önceki mesajlarda yok. İstek sayısı ve maliyet eski veriden de geliyor.

## 4. Pes etmeme + 60 cümlelik gerçek konuşma

- **Kural (agent prompt):** önce aracını dene; eksik ayarı adıyla söyle; okuyabileceğin şeyi kullanıcıdan yapıştırmasını isteme; alan dışıysa handoff.
- **Kodda emniyet:** cevapta "erişimim yok / yapamam / yapıştır / sorgulayamıyor…" geçiyorsa, hiç gerçek araç çalışmamışsa ve bir ayar adı yoksa, o çalışan bir kez daha çalışıyor.
  - Raporlarda `gave_up` adımı olarak görünür.
  - Eki olan mesaj hariç.
- **Set:** 41 → **60** cümle, dokuz çalışanın hepsi. Yeniler:
  - Venture, sahte GitHub ile: week3, issue, readme, rakipler, toplantı + özet
  - Metrics, Creator, Buddy, Mentor
  - "yapıştırır mısın" denemesi
  - tek mesajda iki iş
- **Sonuçlar:**
  - İlk ölçüm 59/60 + 59/60. Metrics bir kez araç çalıştırmadan "sorgulayamıyor" dedi; desen genişletildi.
  - Son durum, 2 tur: **59/60 + 60/60 (%99)**, hedef ≥%95.
  - Tek kaçan #2: eski DSA açık-soru akışı, arada bir "cse 211" cevabını yeni soru sanıyor.
- karar: 58 ve 60'ta ekibin soru sorması doğruydu; testleri düzelttim.
  - 58: "pazartesi" bugün de olabilir, gelecek hafta da.
  - 60: o saatte zaten spor var.

## 5. Bu akşamki NEXA toplantısı

- **"bugün akşam NEXA toplantısı var"** → Chrono 19:00'a ekliyor, kod Venture'a bağlıyor. Chrono: "Toplantıdan bir saat önce haftanın sunum taslağını ve klasörü boş olanları sana yazacak."
- **Hatırlatma:** 5 dakikada bir kontrol. Toplantıya ≤1 saat kala Venture sohbete yazıyor ve push gönderiyor, bir kez, LLM'siz. İçerik:
  - son week klasöründe üye başına: klasör, commit yazarı, README başlığı, son commit
  - "Klasörü boş: …"
  - "Geçen hafta teslim edip bu hafta klasörü olmayan: …"
- **Testler:**
  - 3 saat önce gitmiyor, 55 dk kala gidiyor, ikinci kez gitmiyor.
  - Iceberg toplantısı ve "EE211 lab" bağlanmıyor; tüm gün etkinlik atlanıyor.
  - GitHub ayarı yoksa ayarın adı söyleniyor.
  - Geri al, bağı da kaldırıyor.
- **Dev'de 18:05'te:** "NEXA toplantısı 19:00'de (1 saatten az kaldı). Sunum taslağını hazırlayamadım: GITHUB_STARTUP_REPO geçersiz: 'gorkemergune/<startup>' …"
- karar: bir toplantıyı NEXA'nın sayan şunlar: `keywords` + Venture'ın alan metnindeki özel adlar (senin yerelinde "Nexa Lab"; "NEXA" da eşleşir) + repo/weekN. Hafta = depodaki en büyük weekN.

## Deploy sonrası denemen gerekenler

Bu akşamdan önce, sırayla:

1. **`.env`'i düzelt:** `GITHUB_STARTUP_REPO=<NEXA deposunun owner/name'i>`.
   - Fine-grained token'a o depoyu ekle: Contents, Issues, Pull requests, Metadata, salt okuma.
   - Depo bir organizasyondaysa token'ın o organizasyon için oluşturulmuş olması gerekir.
2. `.\scripts\deploy-live.ps1`. Önce her modülü prod imajında tek başına import ediyor, sonra testler, ardından iki migration: bug raporları ve etkinlik sahibi.
3. **İstersen** yerel `config/agents.yaml`'da Venture'a `keywords: [Nexa, Nexa Lab]` ekle. Alan metninden zaten çıkıyor; bu sadece daha kesin hale getirir.
4. Canlıda sırayla dene:
   - "bugün akşam NEXA toplantısı var" → Chrono ekler, Venture'ın 1 saat önce yazacağını söyler.
   - "bu akşamki NEXA toplantısında üyeler week3'te yaptığı projeleri sunacak, kim ne yapmış taslak hazırla" → üye bazlı taslak. Yukarıdaki sahte repo taslağıyla karşılaştır.
   - Bir cevabın altında 👎 Hatalı → not yaz; sonra `.\scripts\export-bugs.ps1` → `docs\bugs\` altındaki dosyayı bana ver.
   - Raporlar sekmesinde Gün / Hafta.
   - Toplantıya 1 saat kala Venture'ın mesajı ve push.
5. Masaüstü uygulaması: 👎 butonu yeni sürümde var. İstersen `desktop` için yeniden derle (`npm run tauri build`).
