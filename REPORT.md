# REPORT — 21 Kasım 2026 (akşam)

Kapsam: `test/e2e-qa` merge'ü, QA bulguları (Y1–Y3, O1–O4, düşükler) ve en yüksek öncelikli
iki gerçek kullanım hatası (A, B). Canlı/geliştirme ayrımı ve KULLANIM.md isimleri bilerek
yapılmadı: o işler `feat/live-deploy`'da ikinci ajanda. `docker-compose*`, nginx yapılandırması,
`scripts/` ve `docs/tr/`'ye dokunmadım. Push yok.

## En yüksek öncelik: gerçek kullanımdaki iki hata (A, B)

### Sebepler (loglardan / veritabanından)

**A**: "yarın sabah Medipoldeki kahvaltıya gidicem" Scholar'a gitti ve hiçbir şey eklenmedi.
Sebep "Medipol" kelimesi değil. Scholar'ın bir önceki mesajdan **açık sorusu** vardı ("bu telafi
dersine mi gitmedin?"). Kod, 8 kelimeden kısa ve değişiklik fiili içermeyen her mesajı o sorunun
cevabı sayıyordu. Fiil listesi "gidicem"i tanımıyordu, bu yüzden mesaj soruyla birlikte doğrudan
Scholar'a gitti; Scholar "ders değil" deyip durdu (gerçek DB: mesaj 103 → 104, koordinatör
satırı yok).

**B**: "Pazartesi DSA sınavında ..." mesajına "Cevap gelmedi (zaman aşımı)" geldi.
Gerçek DB'de bu mesaj **hiç kaydedilmemiş** ve tek bir LLM çağrısı bile yapılmamış (son
`llm_usage` satırı A'ya ait, 17:45:25). Mesaj uygulamaya hiç ulaşmadı:
1. Gündelik Yaver'in çalışma klasöründen sıcak yeniden yüklemeyle çalışıyor. O sırada bir
   dosya kaydettim (`config_problems.py`), uvicorn yeniden yüklemeye başladı.
2. Açık bir ofis sekmesinin SSE akışı hiç kapanmadığı için `Waiting for connections to close`
   adımında **sonsuza kadar** bekledi. API 'unhealthy' oldu; o arada gönderilen mesaj cevapsız
   kaldı.
3. Y3 düzeltmesiyle gelen 45 sn'lik istemci zamanlayıcısı bunu "zaman aşımı" olarak gösterdi.
   Düzeltmeden önce sonsuz "yazıyor…" olurdu.

Düzeltme: `uvicorn --timeout-graceful-shutdown 5`. Açık bir akışla yeniden yükleme testinde
akış 5 sn'de kesildi, yeniden yükleme tamamlandı. Asıl çözüm canlı/geliştirme ayrımı (ikinci
ajan). LLM yavaşlığı ya da takılan bir döngü değildi.

### Yapılanlar

| # | İş | Commit |
|---|---|---|
| 1 | Uzun işler cevabı bekletmiyor. Sınav sohbette eklenince cevap hemen geliyor; tekrar planı mesaj kaydedildikten sonra arka planda üretilip **ayrı mesaj** olarak düşüyor (`after_message` → `run_job("exam_prep", record=False)`, günlük 18:00 işi yine çalışıyor). Sınav konuları kaydediliyor (`add_event topics` → "Konular: linked list, stack, queue"); syllabus yoksa plan bu konulardan çıkıyor. | `9938c5f` |
| 1 | Yeniden yükleme takılması (B'nin sebebi) | `a7fb731` |
| 2 | **Niyet bazlı yönlendirme.** Her mesaj önce tek bir hızlı çağrıyla parçalara ve niyetlere ayrılıyor: etkinlik, sınav, ders, devamsızlık, ders notu, görev, takip, spor, içerik, reklam, startup, kariyer, sosyal, hatıra, soru, geri al, cevap. Niyet → sahip eşlemesi kodda sabit (`agent/intent_map.py`). Kod delege ediyor, koordinatör yalnız cevabı yazıyor. Yer adı tek başına hiçbir şeyi belirlemiyor. Açık soru varken gelen mesaj da sınıflandırılıyor: soruya cevapsa ya da soranın alanındaysa ona, yeni bir istekse normal akışa gidiyor (A'nın asıl düzeltmesi). | `3e3ad7d`, `da7ddf2` |
| 3 | Hiçbir çalışan isteği yapmadan dönmüyor. Alanı dışındaysa `handoff(reason, area)` çağırıyor, koordinatör aynı mesajda doğru çalışana veriyor; bu, doğrudan sohbette ya da adıyla çağrılan çalışanda da geçerli. Kendi alanına handoff reddediliyor. Düz takvim etkinliği (`add_event`) herkesin ortak aracı. Saat yoksa "sabah" 09:00, "öğlen" 12:00, "akşam" 19:00 oluyor. | `6633b0d`, `237c0da` |
| 4 | Ders takma adları: `courses.aliases`. Bilinmeyen kısaltmada (DSA) çalışan bir kez soruyor ("CSE 211 mi, CSE 221 mi?"); cevap alias olarak kaydediliyor ve geri alınabiliyor. **Gerçek DB'ye migration uygulandı**, önce `scripts/backup.ps1` ile yedek alındı: `backups/yaver-20261121-151256.sql.gz`. | `92f4a5f` |
| 5 | Gerçek konuşma seti (`tests/db/test_live_real_talk.py`): senin yazım tarzınla 41 mesaj, ilk maddeler A ve B. İçerik: küçük harf, eksik ek, "gidicem / çıkcakmış / uğrıycam", saatsiz etkinlik, Medipol / Iceberg geçen ama ders olmayan şeyler, tek mesajda iki iş. Her biri **veritabanında** kontrol ediliyor: hangi kayıt, hangi gün, hangi saat, hangi ders, konular. | `bf913e7` |

### Canlı set sonuçları (test DB'si, 2 tur)

| Koşu | Tur 1 | Tur 2 | Ne düzeltildi |
|---|---|---|---|
| ilk | 36/41 (%88) | 36/41 (%88) | (başlangıç) |
| 2 | 40/41 | 41/41 | Kendi alanına handoff reddi, koordinatöre niyet notu, plan maddelerinde ders kodu, "onay isteme, yap" kuralları |
| 3 | 41/41 | 41/41 | "cuma akşam" bütün ifadeyle `resolve_date`'e |
| 4 | 40/41 | 41/41 | Hatıra: haftalık saatli bilgi blok olur ("her cuma 9-17 Medipol'de çalışıyorum" eski regresyon setinde bozulmuştu). Kalan hata: soranın alanındaki cevap ("cse 211" → `course_note`) |
| 5 | 40/41 | 41/41 | Kalan hata: el verilen parça, hedefin aynı mesajdaki kendi parçasını "zaten yapıldı" diye atlatıyordu |
| 6 | 40/41 | 41/41 | Kalan hata: "13.30da" saat olarak çözülmüyordu (resolver) |
| **son** | **41/41 (%100)** | **41/41 (%100)** | — |

Düzeltilen hatalar:
- Chrono "market alışverişi yapmam lazım"ı kendi işi değil sanıp geri verdi, kimse yapmadı.
- Hatıra parçası blok diye delege edildi.
- "ee211" ile "Devre Teorisi" bloğu eşleşmedi.
- "13.30da" saat olarak tanınmadı.
- "bu perşembe spora gidemicem" için onay istendi.

Eski setler son kodla:
- regresyon **25/25**
- yönlendirme **17/18**: kalan "Iceberg staj başvuruma dönüş bekliyorum, her gün sor". Takip niyetiyle Chrono'ya gidiyor ve takip oluşuyor; set Mentor'u bekliyor (ROADMAP backlog'unda).

## QA bulguları (kod bazında)

| Kod | Durum | Ne yapıldı | Commit |
|---|---|---|---|
| **Y1** | ✅ | Kimlik kontrolü DB bağlantısını hemen bırakıyor (`Depends(get_session, scope="function")`). Yeni e2e testi 18 açık ofis akışını açıyor: pano ve `/health/ready` ~100 ms'de 200. Düzeltmeden önce aynı test 500 verdi. | `185c148` |
| **Y2** | ✅ (backend) | `X-Forwarded-For` yalnız güvenilen proxy'den geliyorsa sayılıyor (`TRUSTED_PROXIES`, varsayılan: bu makine + Docker ağları), o zaman da yalnız proxy'nin gördüğü son adres. Limiter en fazla 1000 adres tutuyor. pytest + e2e: her denemede farklı başlıkla nginx üzerinden 429. nginx'teki `$remote_addr` satırı ikinci ajanın işi. | `0a2555b` |
| **Y3** | ✅ | Sunucu 15 sn'de bir ping atıyor, 240 sn üst sınır var (`error timeout`, rollback). İstemcide 45 sn hareketsizlik sınırı var; `done`/`error` gelmeden kapanan akışta görünür hata çıkıyor; hatalı cevapta "Tekrar dene" düğmesi var. **E2E'deki 2 kırmızı test yeşil.** | `3569472` |
| **O1** | ✅ | Geçersiz `.env` değeri varsayılana düşüyor (`9:00`, `21.00` artık geçerli). Bozuk `agents.yaml` / `providers.yaml` yerine example dosyası okunuyor. Açılışta ERROR logu ve arayüzde uyarı bandı çıkıyor. QA'nın kendi denemesi (`BRIEFING_TIME=9h`, `APP_TIMEZONE=Istanbul`, kapanmamış tırnaklı agents.yaml) artık açılıyor. `e16b843` kuralıyla birleştirildi (CLAUDE.md). | `9190f80` |
| **O2** | ✅ | `ShiftContext.search` zaten düzelmişti (`websearch` takma adı). Tarama `backend/scripts/shadow_scan.py`'ye taşındı, bulgu olursa çıkış 1. Pytest'te (smoke) ve pre-commit'te (`.pre-commit-config.yaml`) çalışıyor. Bulduğu son 3 isim düzeltildi; biri benim yeni eklediğim `ChatReply.intents`'ti. Ayrıca `app.agent.intents` önce import edilince ortaya çıkan döngüsel import da düzeltildi. | `2506e18`, `da7ddf2` |
| **O3** | ✅ (api) | Takvim token'ı (ve her `token=/key=/password=` değeri) api erişim logunda `***` oluyor; e2e stack'inde doğrulandı. nginx logu ikinci ajanın işi. | `060ea32` |
| **O4** | ✅ | `httpx2` artık çalışma zamanı bağımlılığı (önce yalnız dev grubundaydı); prod imajında doğrulandı. | `ab0f1b5` |
| O5 | ⏭ backlog | Listede yoktu; ROADMAP backlog'unda. | — |
| D1 | ✅ | Rollback de patlarsa çalışan "working"de kalmıyor, ilk hata korunuyor. | `0cf04f7` |
| D2 | ✅ | Otomatik yedek sıkıştırmayı thread'de yapıyor; stderr aynı anda okunuyor. | `0cf04f7` |
| D3 | ✅ | Ekler event loop dışında okunuyor. | `0cf04f7` |
| D4 | ✅ | Toplu yüklemede reddedilen dosya, öncekileri diskten siliyor. | `0cf04f7` |
| D5 | ✅ | `X-Forwarded-Proto` da yalnız güvenilen proxy'den (Y2 ile). | `0a2555b` |
| D6 | ⏭ backlog | DST (Europe/Istanbul'da etkisiz). | — |

## e2e sonucu

**20/20 yeşil**:
- QA'nın 17 testi, bunların içinde Y3'ün 2 kırmızısı
- 3 yeni test: Y1 açık akışlar, Y2 başlıkla limit aşma, O1 uyarı bandı

Her maddeden sonra smoke testi ve LLM'siz e2e suite çalıştı. O2'de e2e'yi commit'ten hemen
sonra koştum (yeşil); diğerlerinde commit'ten önce. Backend: 1081 test, ruff, mypy temiz; web:
`npm run check` temiz. Kural CLAUDE.md'de ("kırmızıysa commit yok").

## Sana düşenler / bilmen gerekenler

- **Geliştirme API'si (gündelik Yaver) bugün üç kez etkilendi:**
  - A mesajından hemen sonra (17:46 civarı) yeniden yükleme takıldı (B'nin sebebi); `docker compose restart api` ile
    açtım.
  - Dockerfile bayrağı için `up -d --build api` ile yeniden kuruldu.
  - D3'te benim bozuk kaydettiğim bir satır yüzünden ~1 dk açılamadı; hemen geri aldım.
  - Şu an `(healthy)`, `/api/health/ready` 200. Bu kırılganlığın kalıcı çözümü canlı stack.
- **Gerçek DB'ye migration uygulandı** (`courses.aliases`), yedek
  `backups/yaver-20261121-151256.sql.gz`. Gerçek DB'nde CSE 211'in adı yok, bu yüzden ilk
  "DSA" mesajında Scholar bir kez soracak; sonra hep bilecek.
- **Yerel config'e** iki satır ekledim (gitignored, commit'lenmedi):
  - `config/providers.yaml`: `intent_classify: fast`
  - `config/agents.yaml`: Scholar'a `add_course_alias`
- **Yeni `.env` alanları** (opsiyonel, `.env.example`'da): `TRUSTED_PROXIES`, `CHAT_TIMEOUT_SECONDS`.
- Her mesajda bir hızlı sınıflandırma çağrısı daha var: ~$0.0003–0.0005 ve ~1 sn.
- **Harcama:** bugünkü bu iş için ~$0.45 (hepsi test DB'sinde canlı testler: gerçek konuşma seti
  7 koşu, eski regresyon ve yönlendirme setleri).
- Pre-commit kancası istersen bir kez: `pip install pre-commit && pre-commit install`.
- **deploy-live:** bu işi ikinci ajan `feat/live-deploy`'da yapıyor; ben dokunmadım. Kullanım
  rehberi o branch'in `docs/tr/` dosyasında olacak.
- Kalanlar `ROADMAP.md` → Backlog: O5, D6, Y2/O3'ün nginx yarısı, sınav planının SSE ile anında
  görünmesi.

## Commit'ler (push yok)

```
40c1c10 docs: CLAUDE.md + ROADMAP backlog
0cf04f7 fix: QA D1-D4
ab0f1b5 fix(deps): O4
060ea32 fix(logs): O3
2506e18 fix(ci): O2
bf913e7 test(live): real talk (41 mesaj, 82/82)
237c0da fix(agents): yap, sorma; ders kodu; 13.30da
da7ddf2 fix(routing): canlı setin bulduğu yönlendirme hataları
9938c5f feat(exams): konular + arka planda tekrar planı
92f4a5f feat(courses): ders takma adları (gerçek DB migration'ı yedekten sonra)
6633b0d feat(agents): handoff + ortak add_event + varsayılan saat
3e3ad7d feat(routing): niyet bazlı yönlendirme + açık soru koruması
a7fb731 fix(api): graceful shutdown 5 sn (B'nin sebebi)
9190f80 fix(config): O1
0a2555b fix(auth): Y2 + D5
3569472 fix(chat): Y3
185c148 fix(api): Y1
dcef6c1 Merge test/e2e-qa
```
