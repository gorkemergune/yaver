# Yaver HQ — Ofis (tasarım ve mimari)

Yaver'in yeni yüzü: izometrik (2.5D) bir ofis. Her ajan bir **çalışan**; masası, defteri, gelen kutusu ve mesai planı var. Kullanıcı ofisi açınca kimin ne yaptığını görür, bir çalışana tıklayıp notlarını okur ve doğrudan ona sorar. Genel sohbette Yaver'e yazılanlar tool call ile doğru masaya gider.

Onaylanmış görsel prototip: `design/office-prototype/Main.dc.html` (tasarım kanvası dosyası; çalışan mantık ve sahne geometrisi içinde). Statik sahne `scripts/office_scene.py` ile üretildi.

## Temel ilke: ofiste hiçbir şey sahte değil

Animasyon gerçek duruma bağlıdır. Backend her çalışanın durumunu yayınlar, frontend onu çizer.

| Ofiste görünen | Backend durumu |
|---|---|
| Masasında, üstünde "…" | `working` — o an LLM/araç çağrısı yürütüyor ya da sırada iş var |
| Toplantı odasına yürüyor / oturuyor | `meeting` — başka bir çalışana iş devrediyor (delegation) ya da standup |
| Mutfakta / pencere koltuğunda, elinde kahve | `break` — boşta; kuyruğu boş |
| Dinlenme kanepesi, koridor | `idle_walk` — boşta (rastgele, sadece görsel çeşitlilik) |
| Kırmızı nokta | `needs_user` — senden onay/cevap bekliyor |
| Mesai dışı (gece) | `off` — masası boş, ekran sönük (opsiyonel, O5) |

Boşta olma (break/idle_walk) görsel çeşitlemedir ve frontend'de seçilebilir; working / meeting / needs_user ise **yalnızca** backend'den gelir.

## Kadro (varsayılan; isim, renk, kişilik `config/agents.yaml`)

| Çalışan | Alan | Otonom mesai (PC hep açık) | Gerekli entegrasyon |
|---|---|---|---|
| Yaver — Genel Müdür (kendi odası) | Seninle konuşur, yönlendirir, birleştirir, geri al | 09:00 standup, 21:00 gün sonu raporu | — |
| Atlas — Akademik | Dersler, devamsızlık, sınav, materyal, çalışma kağıdı | Sınav hazırlığı, haftalık ders özeti | (mevcut) |
| Nova — Kariyer | Medipol, Iceberg, staj başvuruları | Bekleyen dönüş takibi | Gmail (ileride) |
| Orion — Startup | Nexa Lab hedefleri, rakipler | Sabah haber/rakip taraması, Pazartesi notu | Web arama API |
| Lyra — Reklam Analisti | Reklam performansı | Günlük metrik çekme, anomali uyarısı | Meta Marketing API |
| Mira — İçerik | Post fikirleri, içerik takvimi | Trend tarama, haftalık takvim | Web arama API |
| Ece — Sosyal Çevre | Arkadaşlar, doğum günleri, planlar | Hatırlatmalar | — |
| Deniz — Ajanda | Toplantılar, takvim, followup | Çakışma kontrolü, takip soruları | (mevcut) |
| Kaan — Koç | Spor, disiplin, ekran süresi | 21:00 check-in, Valorant limiti | Desktop (mevcut) |
| Arda — Araştırma · AI | TÜBİTAK, Medipol model çalışmaları | Haftalık deney özeti, teslim hatırlatma | — |

Mevcut 3 yaver eşlemesi: academic → Atlas, agenda → Deniz, discipline → Kaan. Yeni çalışan = `agents.yaml` kaydı + araçlar + ofiste boş masa (düzen 5 masa çifti; arka/ön sıra).

## Backend (mevcut çekirdeğin üstüne)

- `employees` tablosu `agents.yaml`'dan senkronlanır: id, ad, rol, renk, masa (sıra + sütun), kişilik, araçlar, `daily_budget_usd`.
- `employee_state`: activity (yukarıdaki enum), current_task, since, updated_at. Tek yazma noktası: `office/state.py` (`set_state(...)`), her değişiklikte olay yayınlar.
- `employee_notes` (defter): kısa, tarihli notlar; ajan `add_note` aracıyla yazar, mesai işleri de yazar. Sohbette "Atlas'ın defterinde ne var?" okunabilir.
- `employee_tasks` (gelen kutusu): kaynak (kullanıcı / Yaver / mesai), durum, sonuç; koordinatör delegasyonu bunu kullanır.
- Mesai işleri: mevcut scheduler'a çalışan bazlı işler (`office/shifts.py`). Her iş başında `working`, bitince `break`.
- Olay akışı: `GET /api/office/stream` (SSE) → `{employee_id, activity, task, needs_user, ts}`; `GET /api/office/snapshot` ilk yükleme için.
- Delegasyon görünürlüğü: koordinatör → çalışan devri başlarken ikisi `meeting`, bitince `working`/`break`.
- Bütçe: çalışan başına günlük limit; aşılınca mesai işleri durur, `needs_user` ile bildirir.
- Doğrudan sohbet: `POST /api/employees/{id}/chat` — o çalışanın prompt'u ve araçlarıyla, aynı change_set/undo altyapısı.

## Frontend

- Yeni ana ekran: **Ofis** (Takvim / Görev panosu / Raporlar sekmeleri kalır; mevcut Bugün/Hafta görünümleri Takvim'e taşınır).
- Sahne: prototipteki gibi SVG katmanları. Statik katmanlar `scripts/office_scene.py` ile üretilip `web/src/office/scene/*.svg` olarak gelir (koordinatlar ve çizim sırası prototipte doğrulandı). Dinamik katman: çalışan figürleri (React).
- Hareket: prototipteki ızgara + A* yol bulma (engeller listesi prototipte), 0.55 karo adım, 0.9 sn geçiş. Oturma noktaları, yaklaşma noktaları ve z-sırası kuralları prototipten aynen alınır.
- Sol altta küçük çalışan listesi (isim kendi renginde + durum), sağda detay paneli (Şu an, Defter, Mesai planı, Sohbet), altta "Yaver'e yaz" + mikrofon.
- Gece/gündüz gerçek saate göre. Mobilde sahne yatay kaydırılır, panel alta iner.

## Fazlar

| Faz | İçerik | Bitti sayılır |
|---|---|---|
| **O1 – Ofis motoru** | employees/state/notes/tasks tabloları, `set_state`, SSE akışı, koordinatör ve araç çağrılarının durum yayınlaması, doğrudan çalışan sohbeti, `add_note` aracı | Sohbette bir istek verince SSE'de ilgili çalışanın `working` → `break` geçişi görülüyor; defter API'den okunuyor |
| **O2 – Ofis sahnesi** | Prototipin React'e taşınması, statik SVG katmanları, A* hareket, panel, liste, canlı SSE bağlantısı | Ekranda gerçek isteklerle çalışanlar masaya dönüp çalışıyor, delegasyonda toplantı odasına gidiyor |
| **O3 – Yeni çalışanlar** | Orion, Lyra, Mira, Ece, Nova, Arda + mesai işleri; web arama ve diğer entegrasyonlar (anahtar yoksa çalışan "entegrasyon bekliyor" durumunda) | Her çalışan en az bir gerçek mesai işini yapıp defterine yazıyor |
| **O4 – Ritüeller** | 09:00 standup (herkes toplantı odasında, brifing), 21:00 gün sonu raporu, Pazar haftalık toplantı, görev panosu (kanban) | Standup sahnede görünüyor ve brifing sohbete düşüyor |
| **O5 – Cila** | Mesai dışı durumu, ses efektleri (kapatılabilir), masaya tıklayınca ekran yakınlaştırma, performans | — |
