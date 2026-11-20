# Gece raporu — 20/21 Kasım 2026 (O2 + O3 + O4)

Üç faz da kodda tamam. 13 commit var, **push yok**. `down -v`, volume silme yok; `.env`'e dokunulmadı.

Gerçek DB'de migration gerekmedi, bu yüzden yedek de alınmadı. Yeni tablo yok; yalnızca dev API yeniden yüklenince çalışan listesi `agents.yaml`'dan senkronlandı.

Her maddeden sonra kontroller (container'da `ruff`, `ruff format`, `mypy`, `pytest`; web'de `npm run check`) yeşildi. Son durum:
- **Backend:** 835 test.
- **Web:** 55 test.

LLM harcaması **≈ $0.03** (sınır $1). Hepsi test DB'sindeki canlı denemelerde:
- O2 canlı akış: 2 mesaj ve panel sohbeti, ~$0.006
- 10 kişilik yönlendirme seti: 2 tur, ~$0.014
- Standup: 2 tur, gün sonu raporu: 1 kez. Bu kayıtların bir kısmını test DB sıfırlaması sildi; token sayısından tahminim ~$0.01.

## Özet

| Faz | Madde | Durum | Commit'ler |
|---|---|---|---|
| O2 | Sahne betiği → katman başına SVG + `layout.json`, gökyüzü CSS değişkeni | ✅ | `abec393` |
| O2 | Geometri (engeller, ızgara, A*, koltuklar, z-sırası) + SSE → figür modeli | ✅ | `9c9a44b` |
| O2 | Canlı bağlantı (snapshot + SSE, yeniden bağlanma, 40 sn sessizlik bekçisi) | ✅ | `4dbd299`, `6298e43` |
| O2 | Ofis ana sekme, Takvim altında Bugün/Yarın/Hafta, liste, panel, Yaver'e yaz + mikrofon | ✅ | `4dbd299` |
| O2 | A* testi (tüm nokta çiftleri) + SSE → figür birim testleri | ✅ | `9c9a44b`, `b24dcf8` |
| O2 | Headless ekran görüntüleri (masaüstü + 390 px), düzeltmeler | ✅ | `4dbd299` |
| O2 | Ek: çalışanla doğrudan sohbet ana sohbetin yerine geçiyordu (O1 hatası) | ✅ | `efdd894` |
| O3 | 6 yeni çalışan (örnek + senin yerel `agents.yaml`'ın) | ✅ | `ee7bc95` |
| O3 | `web_search` (Tavily/Brave) + Lyra için Meta iskeleti, anahtar yoksa "bekliyor" notu | ✅ | `ee7bc95` |
| O3 | Her yeni çalışana mesai işi, $0.20 günlük bütçe | ✅ | `ee7bc95`, `64c60fa` |
| O3 | 10 kişilik yönlendirme testi (canlı set) | ⚠️ 8/9 | `a6f5095` |
| O4 | 09:00 standup → brifing | ✅ (saat için aşağıya bak) | `d027254` |
| O4 | Gün sonu raporu | ✅ (21:15, karar) | `d027254` |
| O4 | Pazar haftalık toplantısı | ✅ (canlı denenmedi) | `d027254` |
| O4 | Görev panosu sekmesi | ✅ | `d027254`, `839454e` |
| O4 | Dev modda ritüel düğmeleri | ✅ | `839454e` |

## O2 — Ofis sahnesi

- **Sahne:** `scripts/office_scene.py` artık `web/src/office/scene/*.svg` ve `layout.json` yazıyor.
  - 7 katmanın hepsi prototipteki SVG'lerle **birebir aynı**; yalnızca `xmlns` eklendi ve gökyüzü `var(--office-sky)` oldu.
  - SVG'ler satır içi yerleştiriliyor; `<img>` içinde sayfanın CSS değişkeni çalışmazdı.
- **Geometri:** `web/src/office/geometry.ts` prototipin sayılarının aynısı.
  - Tek fark: koltuklar çalışan id'si yerine masa konumuna (`seat:back:0`) bağlı. Kimin nerede oturduğu `agents.yaml`'dan geliyor; kadroda olmayan masa boş kalıyor.
- **A* testi:** 38 nokta, **1406 rota, 0 ihlal**.
  - Prototipte 34 nokta / 1122 rota vardı. Bu gece eklenenler: yönetici odası + 10 masa ve standup için 3 ayakta yer.
  - Kontrol: rotanın her 0.02 karoluk örneği hiçbir engelin içine girmiyor. Tek istisna, koltuğa giriş/çıkış bacağı (koltuk zaten bir engel karesinin içinde).
- **SSE → figür:**
  - `working` → kendi masası.
  - `meeting` → toplantı odası; `meeting_with` ile aynı masada, Yaver bize dönük, karşısındaki arkadan görünüyor.
  - `break` → kahve, koltuk ya da dinlenme (rastgele). Toplantı odasına ve başkasının masasına hiç gitmez.
  - `needs_user` → kırmızı nokta.
  - Bunların hepsi `model.test.ts`'te test edildi.
- **karar (önemli):** backend durumları yürüyüşten çok kısa.
  - Bir devir ~1 sn sürüyor; ofisi prototip hızında (0.55 karo / 0.9 sn) geçmek 10-20 sn.
  - İlk canlı denemede kimse toplantı odasına varamadı (ekran görüntüsü: `o2-canli-ilk-deneme-sorun.png`).
  - Çözüm: backend'in gönderdiği toplantıya ya da masaya figür mutlaka varıyor ve orada kalıyor (toplantı 4 sn, masa 2.5 sn), sonra en güncel duruma geçiyor.
  - Toplantıda, grubun yürüyen bir üyesi varken gelenler kalkmıyor; son gelen oturunca herkesin süresi baştan başlıyor.
  - Bedeli: ofis gerçeğin **10-30 sn gerisinden** geliyor. Olan her şey gösteriliyor, olmayan hiçbir şey gösterilmiyor. Yürüyüş hızını değiştirmedim; istersen hızlandırırım.
- **Ek düzeltme (`6298e43`):** API öldüğünde Vite proxy'si SSE bağlantısını açık tutuyordu ve `: ping` yorumları EventSource'a hiç ulaşmıyordu, yani sayfa kopukluğu fark edemiyordu.
  - Artık ping bir veri olayı; tarayıcı 40 sn hiçbir olay görmezse yeniden bağlanıyor.
  - Canlı denendi: API'yi öldürüp başlattım, sayfa yeni API'ye kendisi bağlandı.
- **Ek düzeltme (`efdd894`):** `/conversations/latest` ve zamanlayıcının mesaj yazdığı "en son sohbet", bir çalışanla açılan doğrudan sohbeti ana sohbet sanıyordu. Atlas'la konuşunca sabah brifingi oraya düşerdi.
- **Görsel kontrol:** headless Chrome, CDP ile.
  - Önce senaryolu bir sahte sunucuyla (yalnızca scratchpad'de, ürün kodunda yok) masaüstü + 390 px, açık/koyu.
  - Sonra test DB'sine bağlı geçici API + gerçek LLM ile kare kare.
  - Bulup düzelttiklerim:
    - "Yaver'e yaz" kutusu dar ve ortalıydı.
    - Telefonda liste sahneyle birlikte kayıyordu; artık sahnenin altında.
    - Telefonda ipucu "sol alttaki liste" diyordu.
    - Yürüyen figür her tick'te yeniden rota hesaplıyordu.
  - Z-sırası prototipteki kurallarla uyumlu: ön sıra sandalye sırtlıkları ve toplantı odası camı figürlerin üstünde, Yaver masasının arkasında.

## O3 — Yeni çalışanlar

- **Kadro (örnek dosya):** Nova (kariyer, arka 1), Orion (startup, arka 2), Lyra (reklam, arka 3), Arda (araştırma, arka 4), Mira (içerik, ön 0), Ece (sosyal, ön 1). Masalar ve renkler prototiptekiyle aynı.
- **Senin `config/agents.yaml`'ın:** 6 kişi sona eklendi, mevcut 4'e dokunulmadı.
  - Alanlar OFFICE.md'deki bağlamla (Medipol, Iceberg, Nexa Lab, TÜBİTAK) dolduruldu.
  - Yedeği: `C:\Users\PC\AppData\Local\Temp\claude\57ae162538478f55\7574789c-9cac-401d-9351-6997b6dbce21\scratchpad\agents.local.backup.yaml` (geçici klasör).
  - Gerçek DB'de ofis şu an 10 kişi.
- **Web arama:** `web_search` aracı (`.env`: `WEB_SEARCH_PROVIDER=auto`, `TAVILY_API_KEY` ya da `BRAVE_API_KEY`).
  - Anahtar yoksa araç `integration_pending` döner ve çalışanın defterine **günde bir kez** "Web arama anahtarı bekleniyor (…)" yazar. Kırmızı nokta çıkmaz.
- **Lyra:** `get_ad_report` iskelet. Anahtar yokken "Meta reklam hesabı bağlı değil", anahtar varken "entegrasyon henüz yazılmadı" der; bekliyor durumunda kalıyor.
- **Mesai işleri:** `agents.yaml` → `shift_jobs`.
  - Nova 10:00 dönüş takibi, Orion 08:30 rakip taraması, Lyra 09:30 reklam metrikleri, Arda 09:15 teslim takibi, Mira 11:00 trend taraması, Ece 10:30 hatırlatmalar.
  - Hepsi zamanlayıcıda (`shift:<çalışan>:<iş>`), bütçe kontrollü, sonuç deftere ve gelen kutusuna yazılıyor.
  - **Canlıda 6/6 çalışan defterine yazdı.**
  - karar: mesai notları LLM'siz, kodla yazılıyor: ücretsiz ve uydurmasız. Web taraması sonuçların başlıklarını ve sitelerini listeliyor (özet yok).
- **Bütçe:** örnek dosyada `office.daily_budget_usd: 0.20`; senin dosyanda yeni 6 kişiye ayrı ayrı $0.20.
  - karar: senin mevcut 4 çalışanına dokunmadım, onlar kod varsayılanında ($0.50) kaldı.
- **Yönlendirme:** `pytest -m live -k routing`, 9 mesaj, alan başına bir.
  - 1. tur 8/9: tek ıskalama, koordinatörün tek alanlı toplantıyı `fast_path` ile kendisinin eklemesiydi. Tasarım gereği; test artık bunu doğru sayıyor.
  - 2. tur 8/9: "Bugün spora gidemeyeceğim" bu sefer Karen'e değil koordinatöre kaldı. 1. turda aynı prompt'la doğruydu; LLM'in değişken davranışı.
- **karar:** koordinatör prompt'undaki örnek isimler artık id ile seçiliyor. `agents[-1]` 10 kişide Ece olunca spor örneği yanlış kişiye düşüyordu.
- **Bulunan hata:** çalışan satırı yokken "bekliyor" notu FK hatasıyla tüm sohbeti düşürüyordu. Artık not yazılmıyor, sohbet devam ediyor (`a6f5095`).
- **Prompt boyutu:** koordinatör 3443 → 3698 token (+%7: 6 yeni alan satırı ve delegasyon listesi). Yeni çalışanlar çağrı başına 1.8-2.8k token.

## O4 — Ritüeller

- **Standup:** brifing işinin içinde.
  - Yaver ve 9 çalışan `meeting` durumuna geçiyor ve toplantı odasında toplanıyor. Oda 9 koltuklu; perde önüne ve kapının yanına 3 ayakta yer eklendi.
  - Her çalışan defteri, gelen kutusu ve bugünkü mesai işlerinden 1-2 cümle söylüyor (fast tier, kendi bütçesinden).
  - Söyleyecek bir şeyi olmayanın ya da bütçesi dolanın cümlesini kod yazıyor, LLM çağrılmıyor.
  - Yaver bunları brifingin sonuna "**Standup**" bölümü olarak ekliyor; sonra herkes dağılıyor.
  - Canlıda 10 kişi odada birlikte görüldü (`o4-standup-toplanti-odasi.png`).
  - ⚠️ **Saat:** standup `BRIEFING_TIME`'da çalışıyor. Kod ve `.env.example`'da varsayılanı 09:00 yaptım, ama senin `.env`'inde `BRIEFING_TIME=08:00` varsa 08:00'de çalışır (dosyaya dokunmadım). 09:00 istiyorsan `.env`'de değiştir.
- **Gün sonu raporu:** her çalışanın bugünkü defter notları ve gelen kutusundan Yaver tek bir fast-tier çağrıyla rapor yazıyor; LLM olmazsa kod listesi var. O gün bir şey olmadıysa mesaj yok.
  - karar: saat **21:15** (`DAY_REPORT_TIME`). 21:00'deki check-in'le aynı dakikada iki mesaj gelmesin diye.
  - Canlı çıktı: "Nova: Iceberg… 2 gündür dönüş bekleniyor; Arda: TÜBİTAK ara rapor teslimi 25 Kasım…".
- **Pazar haftalık toplantısı:** mevcut haftalık plan akışı `weekly_plan.order`'daki çalışanlarla toplantı odasında çalışıyor. Toplantı kısmı testli; plan taslağı Sonnet kullandığı için canlıda denemedim.
- **Görev panosu:** `#/board` (`GET /api/office/board`).
  - **Bekliyor:** bugün henüz çalışmamış planlı işler.
  - **Çalışıyor:** süren işler.
  - **Onay bekliyor:** açık sorusu olan çalışanın son işi.
  - **Bitti:** son 3 gün.
  - Kartlar çalışan rengiyle; karta tıklayınca `#/office?employee=<id>` ile o çalışanın paneli açılıyor.
  - Pano her ofis olayında yenileniyor. Telefonda sütunlar yana kayıyor.
  - Ek: mesai işleri ve ritüeller artık gelen kutusuna "Mesai" kaynağıyla düşüyor (`64c60fa`).
- **Dev düğmeleri:** yalnızca `npm run dev` / dev container'da, ofiste "Ritüeller (yalnızca geliştirme)": Standup, Gün sonu raporu, Haftalık toplantı.
  - Gerçek işi `force` ile çalıştırırlar: gerçek LLM çağrısı yaparlar ve sohbete gerçek mesaj yazarlar.
  - Prod derlemede görünmezler.

## Ekran görüntüleri

`C:\Users\PC\Desktop\yaver-gece-ekranlar\` klasöründe (repoda değil):
- **O2:**
  - `o2-ofis-10-kisi-senaryolu-sunucu.png`: prototiple karşılaştırma için 10 kişilik sabit senaryo.
  - `o2-ofis-panel-secili.png`, `o2-ofis-390px.png`, `o2-ofis-390px-panel.png`
  - `o2-canli-dogrudan-sohbet.png`: gerçek LLM, panelden not.
  - `o2-canli-ilk-deneme-sorun.png`: bekleme kuralından önceki sorun.
- **O4:**
  - `o4-standup-toplanti-odasi.png`, `o4-standup-tam-ekran.png`
  - `o4-gorev-panosu-masaustu.png`, `o4-gorev-panosu-390px.png`
  - `o4-karttan-acilan-panel.png`

Not: prototip dosyası (`Main.dc.html`) kendi başına çalışmadığı için yan yana ekran görüntüsü alınamadı. Statik katmanlar birebir aynı olduğundan karşılaştırmayı figür yerleşimi ve z-sırası üzerinden yaptım.

## Sabah denemen gerekenler

1. **Ofis:** `http://localhost:8080` artık ofisle açılıyor.
   - 10 kişiyi görmelisin. Bir çalışana tıkla: Şu an, Defter, Gelen kutusu, Mesai planı, Sohbet.
   - Telefonda sahneyi yana kaydır; liste ve panel altta olmalı.
2. **Canlı devir:** "Yaver'e yaz"a iki alanlı bir şey yaz (ör. "Cuma 10:00 toplantı ekle, bir de bugün spora gidemeyeceğim").
   - İlgili çalışanlar toplantı odasına yürüyüp Yaver'le oturmalı, sonra masalarına ya da molaya dönmeli.
   - Ofis 10-30 sn geriden gelir (karar yukarıda).
3. **Standup:** ofisin altındaki dev düğmesi "Standup", ya da `POST /api/jobs/briefing/run?force=true`.
   - Herkes toplantı odasına gitmeli; sohbete "Standup" bölümlü bir brifing düşmeli.
   - Saati 09:00 istiyorsan `.env`'de `BRIEFING_TIME=09:00` yap.
4. **Gün sonu raporu:** dev düğmesi ya da akşam 21:15'te.
5. **Görev panosu:** "Görev panosu" sekmesi. Bir karta tıkla, ofiste o çalışanın paneli açılmalı.
6. **Web arama (istersen):** `.env`'e `TAVILY_API_KEY` (ücretsiz katman) ekle ve `docker compose up -d` yap.
   - Orion ve Mira'nın sabah taraması gerçek sonuç yazar.
   - Elle: `POST /api/jobs/shift:startup:web_scan/run?force=true`
7. **Yönlendirme ölçümü (istersen):** `docker compose exec api pytest -m live -k routing -s` (~$0.005).

**Dikkat (risk):** senin yerel `agents.yaml`'ında Jarvis'in alanı hâlâ "iş/staj (Medipol, Iceberg vb.), başvurular" diyor; Nova'nınki de "Medipol ve Iceberg işleri, staj…".
- Bu sınırda yönlendirme ikisi arasında kayabilir; canlı testte "Iceberg staj başvurusu" Nova'ya gitti.
- Mevcut 4'ü değiştirmemem istendiği için dokunmadım. İstersen Jarvis'in alanından "iş/staj, başvurular"ı çıkar; örnek dosyada bunu yaptım.
