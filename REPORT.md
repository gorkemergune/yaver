# Rapor — ek kuyruk (22 Kasım 2026)

(Çalışırken doldurulan taslak; sonda baştan yazılacak.) Önceki rapor: `git show bd40f80:REPORT.md`.

## 1. Venture gerçek repo kontrolü

- karar: `.env`'e dokunmadım (okuyamıyorum da). Kontrolü dev'de, `.env`'deki GITHUB_TOKEN ile, salt okunur yaptım.
- **Senin cümlen (depo adı yok):** Venture `github_week_summary`'yi çağırdı, cevap:
  > Venture: week3 özetini çekemedi, çünkü GitHub deposu ayarı hatalı. `GITHUB_STARTUP_REPO` değeri "gorkemergune/<startup>" olarak girilmiş, oysa "owner/name" biçiminde (ör. acme/startup) olmalı. …
- **Önceki cümlen (`github/gorkemergune/startup` ile):**
  > Venture: … "gorkemergune/startup" deposuna GitHub erişemiyor; depo adı yanlış olabilir ya da GITHUB_TOKEN bu depoya yetkili değil. …
- **Token'ın gördüğü depolar:** 55 depo. Hiçbirinde üye bazlı weekN klasörü yok.
  - Nexa ile ilgili olanlar: `nexa-lab-ai/nexa-bench` ve `nexa-tr/website`; ikisinde de week klasörü yok.
  - weekN klasörü olanlar yalnız ders depoları (`cpp-foundations/doc/week01-12`, `c-foundations/lecture/week01-12`).
  - Sonuç: NEXA startup deposu ya başka bir adda, ya da token'ın kapsamı dışında (ör. bir organizasyon deposu, fine-grained token'a eklenmemiş).

## 2. Hata bildirimi (👎 "Hatalı")

- Web sohbetinde, ofis panelinde (doğrudan sohbet) ve masaüstü mini sohbette her cevabın altında 👎 Hatalı → kısa not → Kaydet → "Kaydedildi (hata #N)".
- `bug_reports`: mesaj, cevap, cevaplayan çalışan, araçlar (hataları, handoff alanı/nedeni), yönlendirme, o cevabın log satırları, not, kaynak (web/desktop), durum.
- `scripts/export-bugs.ps1`: canlıdaki açık raporları `docs\bugs\bugs-<zaman>.md` tek dosyasına yazar (`-All`, `-Since`). Salt okunur oturumda çalışıyor; dev'de denedim, yazma "read-only transaction" hatasıyla reddedildi.
- karar: CLAUDE.md'deki "UI'de tek buton Geri al" kuralına ikinci istisna ekledim (👎 kullanıcı verisi değil, uygulama hakkında rapor); change_log'a girmez, geri alınmaz.
- karar: araç izi artık her cevabın `messages.meta` alanında (yönlendirme, araçlar, hatalar, handoff'lar, maliyet). Hem rapor hem Raporlar sekmesi buradan okuyor. Eski mesajlarda yok.
- karar: log özeti bellekteki son 400 satırdan (WARNING+ ve app.agent INFO: yönlendirme / handoff satırları); diske yazılmıyor, API yeniden başlayınca boşalır. Pencere: kullanıcının mesajından bir sonraki mesaja kadar (en çok 10 dk).
- karar: `docs/bugs/` gitignore'da (sohbet içeriği).
- karar: cevabı hiç kaydedilmemiş (akış hatası) bir mesaj da raporlanabilir; o zaman istemci ekrandakini gönderir.

## 3. Raporlar sekmesi

- Yeni sekme **Raporlar** (`#/reports`): Gün / Hafta seçimi, ‹ › ile önceki/sonraki dönem.
  - Çalışan başına: senden gelen istek, Yaver'den gelen, mesai işi, başarısız, geri verdi, araç hatası, LLM maliyeti.
  - Başarısız ve geri verilen istekler, nedenleriyle (alan; "sözle mi, araçla mı").
  - Yönlendirme kararları: mesaj → niyet → çalışan.
  - Açık hata raporları.
- `GET /api/reports?period=day|week&date=YYYY-MM-DD`.
- karar: "şu an boş Raporlar sekmesi" kodda yoktu (web'de de masaüstünde de); üst menüye yeni sekme olarak ekledim. Telefonda alt menü 6 sütun oldu.
- karar: yönlendirme ve handoff verisi `messages.meta`'dan geliyor; bu sürümden önceki mesajlar sekmede görünmez (istek sayısı ve maliyet eski veriden de gelir).

## 4. "Pes etmeme" denetimi + 60 cümlelik gerçek konuşma

- **Tarama:** prompt'larda ve araçlarda "yapıştır / erişimim yok" diyen bir kural yoktu. Canlı sette Metrics'in tek gerçek örneği: "geçen ayın harcamasını doğrudan sorgulayamıyor", `get_ad_report`'u hiç çağırmadan.
- **Kural (agent prompt 13a):** önce aracını dene; araç bir ayarın eksik olduğunu söylerse ayarın adını söyle; kullanıcıdan okuyabileceğin şeyi yapıştırmasını isteme; alan dışıysa handoff.
- **Kodda emniyet:** bir cevap "erişimim yok / yapamam / yapıştır / sorgulayamıyor…" diyorsa, hiç gerçek araç çalışmamışsa ve bir ayar adı (`*_KEY`, `*_TOKEN`, `GITHUB_*`) yoksa, aynı çalışan bir kez daha çalışır ("önce araçlarını dene" notuyla). Hem delege edilen çalışanda hem son cevapta.
  - Raporlar sekmesinde `gave_up` adımı olarak görünür.
  - Ekli görsel ya da dosyası olan mesaj hariç: kod zaten okumayı denemiş oluyor.
- **Gerçek konuşma seti:** 41 → **60** cümle, dokuz çalışanın hepsi.
  - Yeni: Venture (sahte GitHub ile week3, issue, readme, rakipler), Metrics, Creator, Buddy, Mentor, "bana yapıştırır mısın" denemesi, tek mesajda iki iş, Coach'a yeni haftalık spor.
  - Her cevap ayrıca "denemeden pes etti mi" diye kontrol ediliyor.
- **Sonuç:** 2 tur, **59/60 + 59/60 (%98)**, hedef ≥%95; maliyet $0.086.
  - Kaçanlar: #2 (bilinen DSA açık-soru akışı, 2. turda geçti) ve #48 (Metrics pes etti).
  - #48 için desen genişletildi; 2, 47, 48, 57 iki tur yeniden: 8/8. Metrics bu kez `gave_up` sonrası `get_ad_report`'u çağırdı.
- karar: 58 ("linear quiz pazartesi", bugün pazartesi) ve 60 (salı-perşembe 19-20'de zaten spor var) test hatasıydı. Ekibin sorması doğru; testleri düzelttim, uygulamayı değil.
- karar: `get_ad_report` "rapor yok" sonucuna "hesap ayarlarını adıyla söyle" notu (META_ACCESS_TOKEN / META_AD_ACCOUNT_ID).

## 5. Bu akşamki toplantı (NEXA)

- **"bugün akşam NEXA toplantısı var"** → Chrono etkinliği ekliyor (saat yoksa akşam 19:00) ve kod onu Venture'a bağlıyor (`events.owner_id`).
  - Chrono cevabında söylüyor: "Toplantıdan bir saat önce haftanın sunum taslağını ve klasörü boş olanları sana yazacak."
  - Dev'de gerçek modelle denendi.
- **Hatırlatma:** her 5 dakikada bir kontrol. Toplantıya ≤1 saat kala Venture sohbete yazıyor ve push gönderiyor, bir kez. İçerik: son week klasörünün üye bazlı taslağı (klasör/dosya, commit yazarı, README başlığı, son commit), "Klasörü boş: …", "Geçen hafta teslim edip bu hafta klasörü olmayan: …". LLM yok.
- **Testler (sahte GitHub, week3'e boş bir `ece/` klasörü eklenerek):**
  - 3 saat önce gitmiyor, 55 dk kala gidiyor, ikinci kez gitmiyor.
  - Iceberg toplantısı bağlanmıyor; "EE211 lab" bağlanmıyor ("Lab" tek başına ad değil).
  - Tüm gün etkinliğe gitmiyor.
  - GitHub ayarı yoksa ayarın adını söylüyor.
  - "Geri al" etkinliği ve bağı geri alıyor.
- **Dev'de iş 18:05'te çalıştırıldı.** `.env`'deki repo ayarı yüzünden mesaj: "NEXA toplantısı 19:00'de (1 saatten az kaldı). Sunum taslağını hazırlayamadım: GITHUB_STARTUP_REPO geçersiz: 'gorkemergune/<startup>' …"
- karar: hangi toplantının startup'ın olduğunu `keywords` + Venture'ın alan metnindeki özel adlar ("Nexa Lab", ilk kelimesi "NEXA" da sayılır) + repo/weekN kelimeleri belirliyor. Senin yerel `agents.yaml`'ında keywords yok, ama alan metninde "Nexa Lab" var; bu yüzden çalışıyor.
- karar: hangi hafta: depodaki en büyük weekN klasörü.
