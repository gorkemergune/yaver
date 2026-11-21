# Gece raporu — 21/22 Kasım 2026 (masaüstü 401 + ders materyalleri)

Dal: `feat/night-materials` (worktree `C:\Users\PC\Desktop\yaver-qa`). **Push yok.**

**Canlıya dokunulmadı.** `yaver-live`, gerçek DB ve deploy yok. `import-materials-live.ps1` canlıda çalıştırılmadı. `.env`'e dokunulmadı.

Gece 23:43'te **elektrik kesildi**:
- 2. maddenin kodu yazılmıştı ama commit'lenmemişti. Kontrolleri geçirip commit'ledim.
- Açılışta dev stack ana klasörden (`yaver`) kalkmıştı. Materyal kodu ve `/materials` bağlantısı worktree'de olduğu için `yaver-dev`'i yeniden worktree'den başlattım.

Her maddeden sonra kontroller yeşildi: ruff, format, mypy, pytest (son 1125), smoke, LLM'siz e2e (22/22), dev `health/ready` 200.

**LLM harcaması ≈ $1.10 (sınır $3).**
- Dev DB'de $1.08:
  - izlenceler + eşleme $0.22
  - CSE 221 notları $0.71 (bunun $0.35'i düzeltmeden önce çöken ilk okumada boşa gitti, aşağıda)
  - 6 çalışma kağıdı ~$0.13
- Test DB'de canlı soru seti $0.02.

## Özet

| # | Madde | Durum | Commit |
|---|---|---|---|
| 1 | Masaüstü 401 → "Cihaz anahtarı gerekli", ayarlarda anahtar + bağlantı testi, 0.2.0 kurulum | ✅ | `66ce3c3` |
| 2 | Materyaller: sınıflandırma, haftalık plan, içindekiler → hafta, föyler, dev DB | ✅ (EE211 ⚠️) | `ccd601e`, `3e2f617` |
| 3 | Paket + `scripts/import-materials-live.ps1` (çalıştırılmadı) | ✅ | `148ad7f` |
| 4 | CSE 221 Google Sheets kaynağı + Scholar'ın günlük kontrolü | ✅ | `f98acb6` |
| 5 | Haftalık konu analizi, Pazar planı, sınav planı, çalışma kağıtları | ✅ | `b47560b`, `da451a9` |
| 6 | 15 soruluk canlı regresyon | ✅ 15/15 + 14/15 | `18d132a` |

## 1. Masaüstü 401

- **Neden:** kurulu 0.1.0 (20 Kasım) giriş/cihaz anahtarı bilmiyordu. `Authorization` başlığı göndermiyordu, her 401'i "Sunucu hatası (401)" gösteriyordu.
- **Şimdi:**
  - 401'de "Cihaz anahtarı gerekli" ekranı çıkıyor: anahtarın nereden alınacağı ve "Ayarlara git". Yazılan mesaj kutuya geri dönüyor.
  - Ayarlarda anahtar alanı ve "Bağlantıyı test et" var.
- **Kurulum dosyası:** `desktop\src-tauri\target\release\bundle\nsis\Yaver_0.2.0_x64-setup.exe`

## 2. Ders materyalleri (`python -m app.materials.ingest`)

`syllabus/` klasöründeki 11 dosya. Dönem başı: 28 Eylül 2026.

| Ders | Bulunan | Eksik / belirsiz |
|---|---|---|
| CSE 211 | İzlence: 14 hafta, 7 lab ödevi haftası, 3 kitap | Kitap PDF'i yok; haftalarda okuma bölümü yazmıyor |
| CSE 221 | İzlence: 14 hafta, 2 kitap. 2 ödev (hafta 1-2), Labwork01 Part I (3-6), Part II (4). Google Sheets notları (4. madde) | **Çelişki:** ara sınav hem 8. hafta konusunda hem "Midterm I: Week 9" olarak yazıyor. Kitap PDF'i yok |
| EE211 (BME 211) | İzlence (5 kitap, ara sınav 10 Kasım), lab kitabı: 7 deney sayfalarıyla | **İzlencede haftalık plan yok**: deneyler haftalara eşlenmedi (tahmin edilmedi) |
| MATH 221 | 14 hafta, her haftada okuma bölümü (1.1 … 5.2), kitap | Kitap PDF'i yok. **İzlenceye göre ara sınav 27 Kasım Cuma 16:00**, takviminde olup olmadığına bak |
| TKL 201 | 13 hafta, yazılı tarihlerin 13'ü de dönem haftalarıyla tutuyor, 10 kitap | — |
| HUM 103 | 13 hafta, bölüm + sayfa okumaları (`.docx`), kitap | — |

- **Kitaplar:** klasörde ders kitabı PDF'i yok; tek "kitap" EE211 lab kitabı. Bölüm → hafta eşlemesi kodda hazır, kitap gelince çalışır: önce okumadaki "3.5, 3.6"dan, kalanı tek bir Sonnet çağrısıyla. Kitabın yalnız haftaya eşlenen bölümleri gömülür. Embedding süresi dosya başına ~1 sn; CPU sorun değil.
- **karar:** kodu olmayan ama izlencesi olan dersler `--create-courses` ile oluşturuldu. EE211 canlıdaki adıyla, `BME 211` takma adıyla eşlendi.
- **Hata (düzeltildi):** `.gitignore`'daki `materials/` kalıbı kod klasörü `backend/app/materials/`'ı da yok sayıyordu; kod commit'e hiç girmeyecekti. Kalıplar kök dizine sabitlendi (`/syllabus/`, `/materials/`).

## 3. Paket ve canlıya yükleme

- **Dışa aktarma:** `docker compose exec api python -m app.materials.bundle export` → `data\bundles\materials-<zaman>\` (gitignore'da).
  - Pakette DB kimliği yok: dersler kod/takma adla, dosyalar SHA-256 ile eşleşiyor.
  - Embedding'ler aynen taşınıyor, canlıda yeniden hesaplanmıyor.
- **İçe aktarma:**
  - Tek transaction, tek change_set; geri alınabilir.
  - Aynı paket ikinci kez hiçbir şey yazmaz.
  - Embedding modeli farklıysa, kopya bozuksa ya da DB eski şemadaysa reddedilir.
- **Betik:** `scripts\import-materials-live.ps1` sırasıyla:
  1. Paketi ve çalışan sürümde komutun olduğunu kontrol eder.
  2. `backups\preimport\` altına yedek alır.
  3. Paketi api'ye kopyalar, önce kuru deneme yapar, sonra yükler.
  4. Kopyayı temizler, change set kimliğini `imports.log`'a yazar.
  - Seçenekler: `-DryRun`, `-Undo <id>`.
- **Deneme (dev DB'nin kopyasında):** materyalleri silinmiş "canlı gibi" kopyaya:
  - Yükleme: 5 ders oluştu, EE211 eşleşti, 11 dosya, 226 parça.
  - Tekrar yükleme: hiçbir şey yazmadı.
  - Bozulmuş kopya: onarıldı. Onarımı geri almak bozuk hâli birebir geri getirdi.
  - İlk yüklemeyi geri almak: DB başlangıç hâline döndü.
  - Arama sonuçları dev ile birebir aynı.
  - Betiğin kendisi `-Project yaver-dev` ile denendi (yedek, yükleme, geri alma, "yapacak bir şey yok").
- **Hazır paket:** `data\bundles\materials-20261122-0024` (11 dosya, 226 parça, CSE 221 kaynağı ve 11 sekmesi).

## 4. CSE 221 not kaynağı

- **Tablolar:** `course_sources`, `source_items`. Komutlar: `python -m app.materials.sources add / check / list`.
- **Okuma:** xlsx bütün olarak indirilip kodda okunuyor (ek bağımlılık yok). Hücrelerde neredeyse metin yok (yalnız "codes"ta 7 kısa satır), bağlantı yok; asıl içerik **61 görsel**.
- **Model yalnız yeni/değişen sekmeyi okur.** Değişmeyen kaynak = bir indirme, sıfır maliyet. Görseller Sonnet'le okunuyor; okunamayan el yazısı "belirsiz"e yazılıyor, tahmin edilmiyor.
- **Eşleme** (syllabus'la tutarlı):

  | Sekme | Hafta |
  |---|---|
  | num1, compl., signed | 1 |
  | codes | 2 |
  | bool | 2-3 |
  | func, simpl, canonic | 3 |
  | Map | 4-5 |
  | Lab-Debug | 6 |
  | comb1 | 6-7 |

- **Scholar'ın `source_watch` mesai işi** (her gün 08:20): yeni/değişen sekme olursa deftere not, sohbete "CSE 221'e yeni not: Map" ve bildirim. Bildirim commit'ten sonra gidiyor; başarısız olsa da işi geri almıyor.
- **Bağlantılı dosyalar:** sekmenin bağladığı herkese açık PDF'ler (Drive dosyası, Google Doc, .pdf) materyale ekleniyor. Bu tabloda bağlantı yok; bu yol yalnız testle doğrulandı.
- **Hata (düzeltildi):** ilk okuma son sekmede çöktü. Model `pages` dizisini metin olarak döndürdü, tek transaction olduğu için önceki sekmeler de kayboldu ($0.35).
  - Artık çağrı başına 4 görsel.
  - Metin gelen dizi kodda çözülüyor.
  - Okunamayan sekme atlanıp ertesi kontrole kalıyor.

## 5. Haftalık konu analizi (Scholar)

- **`get_syllabus`:**
  - Haftanın konusu, okuması, lab'ı, sınavı.
  - Tek hafta için o haftaya eşlenen kitap/lab bölümleri (sayfalarıyla), paylaşılan not sekmeleri, föyler ve atıf için izlence dosyası.
  - "geçen hafta / bu hafta / haftaya" kodda çözülüyor.
- **`get_exam_scope` (yeni):** dersin sıradaki sınavı ve kapsadığı haftalar.
  - Kullanıcının söylediği konular syllabus'la eşleşir: kelime kökü + küçük bir TR→EN sözlük ("kanonik formlar" → "Canonical Forms").
  - Konuların hepsi bulunursa yalnız o haftalar döner. Bulunamayan konu varsa açıkça söylenir ve kapsanan tüm haftalar döner.
- **Pazar planı:** mesajda kodda üretilen "📚 Derslerde bu hafta" listesi; modele de ders başına okuma görevi önermesi söyleniyor.
- **Sınav tekrar planı:** her haftanın satırına okuma, bölüm (sayfa), not ve föy ekleniyor.
- **Çalışma kağıdı kaynağı:** artık önce o haftaya eşlenmiş materyalleri alıyor. Önceden 4-5. hafta gibi çok haftalı sekmeler haftalık filtreye hiç girmiyordu.
- **karar:** kağıtlar Pazar gecesi üretildi ve sabah okunacak; bu yüzden "bu hafta" = Pazartesi başlayan **9. hafta**.

**Çalışma kağıtları (9. hafta, dev DB):** kalite, dersin gerçek notu olup olmamasına bağlı.

| Ders | Kaynak | Sonuç |
|---|---|---|
| CSE 221 | Paylaşılan notlar (comb1) | İyi |
| EE211 | Lab kitabı | Haftalık plan yok, genel |
| CSE 211, MATH 221, TKL 201, HUM 103 | Yalnız izlence | İnce, ama uydurma yok: "pasajlarda tanım yok" diyor |

Kitap PDF'leri gelince bu dört ders düzelir.

Örnek (CSE 221, kısaltılmış):

```
## Temel kavramlar
**3x8 yüksek-aktif decoder**
- Girişler A, B, C; çıkışlar D0..D7'dir [5].
- D0 = A'B'C' = m0, yani Di = mi [3].
**Decoder ile fonksiyon gerçekleme**
- F(x,y,z) = Σ(1,5) için D1 ve D5 bir OR kapısına bağlanır [3].
- G' = Σ(0,3) yazılır. D0 ve D3 bir NOR kapısına girer ve çıkış G olur [3].
- MUX fikri notlarda yalnızca kısaca geçiyor. DEMUX için pasajlarda bilgi yok.
## Kaynaklar
- [3] CSE 221 notları: comb1, s. 15-16
- [5] CSE 221 notları: comb1, s. 15
```

## 6. Canlı regresyon (`pytest -m live -k materials_talk -s`)

- **Kurulum:** 15 soru senin yazım tarzınla ("bu hafta cse221de ne var", "dsa sınavına neler çalışmam lazım", "labwork01 part 2 hangi haftanın", "ee211 5. deney ne hakkında"…).
  - Test DB'si: regresyon seed'i + gerçek paket (canlıdaki gibi) + DSA takma adı + 3 sınav.
  - Kontrol: cevapta doğru hafta/bölüm/sayfa **ve** kaynak var mı.
- **Sonuç:** ilk tur 8/15 (%53). Düzeltmelerden sonra iki tur **15/15 (%100) ve 14/15 (%93)**. Tek kalan kayıp: bir turda model "8. hafta" numarasını söylemedi.
- **Düzeltilenler:**
  - Ders adı geçen hafta/sınav sorusu takvim sorusu sanılıyordu; artık Scholar'a gidiyor.
  - Model 25 Kasım Çarşamba'ya "Salı" dedi. Gün adı artık kodda veriliyor (ilke 3).
  - Haftalık planı olmayan EE211 için "hiç materyal yok" dendi. Artık dersin materyalleri listeleniyor.
  - Dosya adı ("labwork01 part 2") ve deney numarası ("5. deney" → Experiment #5, s. 39-42) kodda bulunuyor.
  - "Geçen hafta" seçeneği eklendi.
  - DSA'da araç çağırmadan "hangi ders?" diye soruluyordu. Artık önce araç çağrılıyor (takma adı araçlar biliyor).
  - "lineer cebir" bilinmeyen takma ad: bir kez soruluyor, kurala uygun. Testte kullanıcı "evet math221" diyor.
- Paket kişisel olduğu için yoksa test atlanır.

## Sabah adımların (bu sırayla)

1. **Masaüstü:** `desktop\src-tauri\target\release\bundle\nsis\Yaver_0.2.0_x64-setup.exe` kur. Ayarlarda cihaz anahtarını gir, "Bağlantıyı test et".
2. **Birleştir:** `feat/night-materials` → `main`.
3. **Deploy:** `.\scripts\deploy-live.ps1`. İki migration (`d25f6a819ed6`, `4cefff197dd5`) ve materyal kodu bununla gelir. İçe aktarma deploy'dan **önce** çalışmaz: tablolar ve komut yok, betik bunu söyleyip durur.
4. **Ana klasördeki yerel config** (canlı bunu okur, gitignore'da; ben dokunmadım):
   - `config\agents.yaml` → `academic`:
     - `tools`'a `get_exam_scope` ekle.
     - `shift_jobs: - {job: source_watch, at: "08:20", title: Ders notlarına bakıyor}` ekle.
   - `config\providers.yaml` → `routing.purposes`'a `material_map: smart` ve `source_notes: smart` ekle.
   - Sonra `.\scripts\live.ps1 restart api` (ya da bir sonraki deploy).
5. **Paket:** `.\scripts\import-materials-live.ps1 -DryRun` ile raporu gör, sonra `.\scripts\import-materials-live.ps1`.
   - Beğenmezsen `-Undo <imports.log'daki id>`.
   - Canlıda dersler kod/takma adla eşleşir (CSE221 = CSE 221). Bilinmeyen dersler (HUM 103, TKL 201 vb.) yeni ders olarak açılır; dry-run'da "courses created" listesine bak.
6. **Kontrol:**
   - Takvimde MATH 221 ara sınavı (27 Kasım Cuma 16:00) var mı?
   - CSE 221 ara sınavı 8. hafta mı, 9. hafta mı?
   - EE211 lab'larının hangi haftalarda olduğunu Scholar'a söylersen eşleştiririm.
