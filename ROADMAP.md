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

**Bitti sayılır:**
- [ ] "Pazartesi 9-11 Linear Algebra, Çarşamba 13-15 EE211 lab..." yazınca haftalık program oluşuyor
- [ ] "Bugün linear iptal" → sadece bugünkü blok iptal, diff + geri al çalışıyor
- [ ] "Bugün EE211'e gitmedim" → devamsızlık sayılıyor, limit soruluyor/gösteriliyor
- [ ] "Yarın ne var?" doğru cevaplanıyor (override'lar ve event'ler dahil)
- [ ] Claude harcaması `llm_usage`'da görünüyor
- [ ] Karışık bir mesaj doğru yaverlere bölünüyor, cevapta kimin ne yaptığı görünüyor

## Faz 1 — Proaktif asistan
**Hedef:** Sen sormadan konuşması.

- Scheduler: sabah brifingi (ilk açılışta catch-up), akşam yarın önizlemesi, followup kontrolü, devamsızlık limiti uyarısı, sınav geri sayımı
- Pazar akşamı haftalık planlama seansı (`smart` tier): taslak hafta önerir, onaylanınca task'lara yazar
- PWA + Web Push (iPhone'da ana ekrana ekle, iOS push)
- Tailscale ile telefondan erişim + HTTPS (`tailscale serve`)
- Basit auth: tek kullanıcı parolası + httpOnly session cookie

**Bitti sayılır:**
- [ ] Windows açılınca o günün brifingi geliyor ("Günaydın Görkem, bugün...")
- [ ] Hackathon followup'ı her gün soruluyor, "kabul geldi" deyince kapanıyor ve event'e dönüşüyor
- [ ] iPhone'a push bildirimi düşüyor

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

**Bitti sayılır:**
- [ ] EE211 syllabus'u yükleyince haftalar oluşuyor
- [ ] "Bu haftanın devreler notlarından çalışma kağıdı" → kaynak gösteren bir kağıt geliyor

## Faz 4 — Masaüstü arkadaşı + ekran süresi
- Tauri v2 uygulaması: hep üstte, sürüklenebilir yuvarlak logo; tıklayınca mini sohbet
- Ara ara proaktif balon mesajları (brifing, hatırlatma)
- Windows: ön plandaki pencere/process'i 5 sn'de bir örnekle → `screen_sessions`
- macOS: frontmost app (NSWorkspace)
- `app_limits`: ör. VALORANT günlük 90 dk. %80'de uyarı, %100'de 2 dk geri sayım → process kapatma
- Limit aşımı için "pazarlık": ajana gerekçe söylenir, loglanır, ertesi gün özetlenir
- Windows'ta oturum açılışında otomatik başlatma

**Bitti sayılır:**
- [ ] Logo masaüstünde duruyor, sohbet açılıyor
- [ ] Günlük ekran süresi raporu
- [ ] Valorant limiti uygulanıyor

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
