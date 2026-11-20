# ROADMAP — Yaver

Her faz bitince kullanılabilir bir şey bırakır. Bir faz, "Bitti sayılır" maddeleri gerçekten çalışınca kapanır.

---

## Faz 0 — Çekirdek: konuşarak program yönetimi
**Hedef:** Tarayıcıdan sohbetle ders programı, devamsızlık, sınav, spor ve görevleri yönetebilmek.

- Repo iskeleti, docker compose (`db`, `api`, `web`), Alembic
- Veri modeli: terms, courses, recurring_blocks, block_overrides, events, attendance, tasks, followups, memories, change_log, llm_usage, conversations/messages
- `time_resolver` + testleri ("yarın", "gelecek cuma", "bu hafta sonu", "28-29 kasım")
- LLM router: Groq + Anthropic provider'ları, failover, budget guard, usage kaydı
- Yaver ekibi: koordinatör + 3 uzman yaver (`config/agents.yaml`; varsayılan: Friday = dersler, Jarvis = ajanda, Karen = disiplin)
- Ajan döngüsü + ilk araç seti + undo (bir mesajdaki tüm yaver değişiklikleri tek geri al)
- Web: sohbet ekranı + salt-okunur günlük/haftalık görünüm (Dayframe tarzı) + değişiklik kartı ve "Geri al"
- İlk kurulum sohbeti: "Ders programını yaz/yapıştır" → ajan tüm blokları oluşturur

**Durum: bitti (2026-11-19).** Kanıt: canlı senaryolar (`pytest -m live -k scenarios`, gerçek DB'de 5 mesaj; fast = Groq ve fast = Haiku düzenlerinde) + fake-LLM testleri.

**Bitti sayılır:**
- [x] "Pazartesi 9-11 Linear Algebra, Çarşamba 13-15 EE211 lab..." yazınca haftalık program oluşuyor — canlı senaryo 1: 4 blok (ders, lab, 2 spor) + EE211 dersi DB'de; ilk kurulumda yapıştırılan tablo da (Sonnet, 9/9 satır)
- [x] "Bugün linear iptal" → sadece bugünkü blok iptal, diff + geri al çalışıyor — canlı senaryo 2: yalnız 23 Kasım için `cancel` override'ı, diğer haftalar etkilenmedi; değişiklik kartı + "Geri al" (`POST /api/changes/{id}/undo`); mesajın tamamının tek adımda geri alınması `test_full_week_story`'de
- [x] "Bugün EE211'e gitmedim" → devamsızlık sayılıyor, limit soruluyor/gösteriliyor — canlı senaryo 3 ("Geçen salı EE211'e gitmedim"): devamsızlık 1 olarak kaydedildi, limit bilinmediği için soruldu, o gün ders olmadığı da söylendi; limit biliniyorsa kalan hak gösteriliyor (`test_attendance_with_limit`), Durum sayfasında devamsızlık kartı
- [x] "Yarın ne var?" doğru cevaplanıyor (override'lar ve event'ler dahil) — canlı senaryo 4: toplantı + spor; iptal/taşıma override'ları ve sınavlar `test_day_plan_from_database`, `test_tomorrow_quiz`'de
- [x] Claude harcaması `llm_usage`'da görünüyor — her deneme (hatalılar dahil) maliyetiyle yazılıyor; `/api/usage/month` + üst çubuktaki harcama göstergesi; 0.4 canlı testleri
- [x] Karışık bir mesaj doğru yaverlere bölünüyor, cevapta kimin ne yaptığı görünüyor — canlı senaryo 2: Friday (iptal), Jarvis (toplantı), Karen (spor: gün belirsiz, sordu); arayüzde yaver etiketleri ve adımlar

## Faz 1 — Proaktif asistan
**Hedef:** Sen sormadan konuşması.

- Scheduler: sabah brifingi (ilk açılışta catch-up), akşam yarın önizlemesi, followup kontrolü, devamsızlık limiti uyarısı, sınav geri sayımı
- Pazar akşamı haftalık planlama seansı (`smart` tier): taslak hafta önerir, onaylanınca task'lara yazar
- Akşam check-in: her akşam 21:00'de (config: `CHECKIN_TIME`) tek bir özet mesajı - günün dersleri, sporu, görevleri
  - Dersler varsayılan "katıldı" sayılır; kullanıcı "EE211'e gitmedim" derse devamsızlık yazılır (`log_attendance`, `direction="past"`)
  - Spor ve görevler için durum sorulur; tek cümleyle cevaplanabilir ("spor hariç hepsi tamam")
  - Mesajda hızlı cevap butonları: "✓ Hepsi tamam" ve "Düzenle" (UI'deki "Geri al" dışındaki tek buton istisnası; ikisi de sohbete mesaj olarak gider)
  - Cevapsız kalırsa ertesi sabah brifinginde bir kez hatırlatılır, ısrar edilmez
- PWA + Web Push (iPhone'da ana ekrana ekle, iOS push)
- Tailscale ile telefondan erişim + HTTPS (`tailscale serve`)
- Basit auth: tek kullanıcı parolası + httpOnly session cookie

**Durum (2026-11-20):** zamanlayıcı, brifing, check-in, takip, haftalık plan ve sınav hazırlığı sohbette çalışıyor; Web Push (Chrome'da uçtan uca denendi) ve parola + oturum (web, masaüstü) kodda hazır. Kalan: Tailscale + HTTPS ve iPhone'da push denemesi (Görkem).

**Bitti sayılır:**
- [ ] Windows açılınca o günün brifingi geliyor ("Günaydın Görkem, bugün...")
- [ ] Hackathon followup'ı her gün soruluyor, "kabul geldi" deyince kapanıyor ve event'e dönüşüyor
- [ ] iPhone'a push bildirimi düşüyor
- [ ] 21:00'de check-in geliyor; "✓ Hepsi tamam" dersler + spor + görevleri tek change_set ile işaretliyor, "spor hariç hepsi tamam" sporu açık bırakıyor
- [ ] Check-in'e cevap verilmezse ertesi sabah brifinginde tek satırla hatırlatılıyor, ikinci gün tekrar edilmiyor

## Faz 2 — Ses
- Mikrofon butonu (web) → Groq Whisper → ajan
- Sesli cevap: tarayıcı `speechSynthesis` (sonra Piper opsiyonel)
- iPhone Siri Kısayolu: ses kaydı → `POST /api/voice` (Tailscale üzerinden, token ile)

**Bitti sayılır:**
- [ ] "Hey Siri, Yaver'e söyle: yarın quiz var" çalışıyor

## Faz 3 — Ders materyali ve çalışma
- Syllabus PDF yükleme → haftalık konu çıkarma → `courses`'a bağlama
- Not/slayt yükleme (PDF, görsel, md) → chunk + embed (pgvector)
- "Bu hafta ne işlendi?" → syllabus + yüklenen notlar
- Çalışma kağıdı / özet / soru üretimi (`smart` tier), `study_sheets`'e kayıt, PDF/MD indir
- Sınav öncesi otomatik "son hafta tekrar planı"

**Durum: kod tamam (2026-11-20), gerçek ders materyaliyle denenmesi bekleniyor.** Embedding yerel (fastembed, çok dilli MiniLM); ayrıntı `DAY_REPORT.md` 5-8.

**Bitti sayılır:**
- [x] EE211 syllabus'u yükleyince haftalar oluşuyor — canlı test (uydurma `examples/syllabus/ee211_syllabus.pdf`): Sonnet 14 haftayı tablo olarak önerdi, "evet" ile `syllabus_weeks` + aranabilir parçalar yazıldı
- [x] "Bu haftanın devreler notlarından çalışma kağıdı" → kaynak gösteren bir kağıt geliyor — canlı test: kağıt yalnızca notlardan, her bilgi [n] ile, "Kaynaklar" (dosya + sayfa) kodla ekleniyor; web'de Markdown, .md indir, PDF olarak kaydet
- [x] Not yükleme (PDF / fotoğraf) → ders + hafta (syllabus'tan öneri) → aranabilir; "bu hafta ne işlendi?" (`get_syllabus`)
- [x] Sınava ~1 hafta kala tekrar planı önerisi (konular + notlar + boş saatler), "evet" ile görevlere

## Faz 4 — Masaüstü arkadaşı + ekran süresi
- Tauri v2 uygulaması: hep üstte, sürüklenebilir yuvarlak logo; tıklayınca mini sohbet
- Ara ara proaktif balon mesajları (brifing, hatırlatma)
- Windows: ön plandaki pencere/process'i 5 sn'de bir örnekle → `screen_sessions`
- macOS: frontmost app (NSWorkspace)
- `app_limits`: ör. VALORANT günlük 90 dk. %80'de uyarı, %100'de 2 dk geri sayım → process kapatma
- Limit aşımı için "pazarlık": ajana gerekçe söylenir, loglanır, ertesi gün özetlenir
- Windows'ta oturum açılışında otomatik başlatma

**Durum: kısmen (2026-11-20, `desktop/`, ayrıntı `desktop/RAPOR.md`).** Yapılanlar:
- [x] Tauri v2 uygulaması: şeffaf, hep üstte, sürüklenebilir logo (konum hatırlanıyor); tıklayınca mini sohbet (`POST /api/chat`, yaver etiketi + renk, Geri al)
- [x] Windows ön plan örneklemesi 5 sn'de bir → yerel SQLite `screen_sessions` (boşta kalma kuralı, pencere başlığı tutulmaz)
- [x] `app_limits` (config.json): %80 ve %100'de balon + Windows bildirimi, günde bir kez
- [x] Windows oturum açılışında otomatik başlatma (varsayılan kapalı) + tepsi menüsü + tek instance
- [ ] %100'de geri sayım → process kapatma, "pazarlık" akışı
- [ ] Proaktif balon mesajları (balon penceresi hazır, içerik kaynağı yok)
- [ ] macOS frontmost app

**Bitti sayılır:**
- [ ] Logo masaüstünde duruyor, sohbet açılıyor — kod hazır, Görkem'in kurulu uygulamayla denemesi bekleniyor (`desktop/RAPOR.md` → Sabah denemen gerekenler)
- [x] Günlük ekran süresi raporu — masaüstü 10 dk'da bir ve kapanışta günlük özeti gönderiyor (backend kapalıyken yerelde bekliyor), Karen `get_screen_time` ile cevaplıyor, akşam check-in'de "bugün X saat ekran, Y dk VALORANT" satırı (2026-11-20)
- [ ] Valorant limiti uygulanıyor — %80/%100 uyarısı var, kapatma yok

## Faz 5 — Open source cilası
- `examples/` ile demo verisi, tek komut kurulum, ekran görüntüleri / GIF
- README: Windows / Mac kurulum, Tailscale, iPhone PWA + Siri Kısayolu rehberi
- Provider rehberi (Groq ücretsiz key alma, Claude, Ollama)
- CI: lint + test (GitHub Actions)
- v0.1.0 release

## Backlog (sonra)
- Yeni yaverler: ör. kariyer/staj başvuruları, startup işleri, finans (`agents.yaml`'a ekleyerek)
- Yaver başına farklı ses (TTS) ve masaüstünde farklı logo/renk
- Gmail read-only entegrasyonu: followup'lar için "dönüş maili geldi mi?" otomatik kontrol
- Yeditepe ders programı / akademik takvim içe aktarma (PDF/ICS)
- ICS export → iPhone Takvim'e abonelik
- Spor takibi detayları (set/tekrar, streak) — Dayframe metrikleri
- VPS'e taşıma rehberi (7/24 erişim)
