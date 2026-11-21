# Ders materyalleri: klasörden veritabanına, geliştirmeden canlıya

Syllabus'lar, lab kitapları, ödev / lab föyleri ve kitaplar **kişiseldir, repoya girmez**
(`/syllabus/`, `/materials/`, `data/` `.gitignore`'da). Akış:

1. Dosyalar repo kökündeki `syllabus/` klasörüne (alt klasör olabilir: `syllabus/cse221-extra/`).
2. **Geliştirmede** yükle ve kontrol et (dev bu klasörü `/materials` olarak salt okunur görür).
3. Geliştirme DB'sinden **paket** çıkar (`data/bundles/`).
4. **Canlıya** paketi `scripts/import-materials-live.ps1` ile yükle (önce yedek alır).

## 1-2. Geliştirmede yükleme

```powershell
docker compose exec api python -m app.materials.ingest /materials --dry-run `
    --term-start 2026-09-28 --alias "BME 211=EE211"          # yalnız ne nereye gider
docker compose exec api python -m app.materials.ingest /materials `
    --term-start 2026-09-28 --term-end 2027-01-22 --alias "BME 211=EE211" --create-courses
```

Git Bash'te `MSYS_NO_PATHCONV=1` ekle (yoksa `/materials` bir Windows yoluna çevrilir).

- Ders: dosya adındaki ya da ilk sayfalardaki kod. İki kod geçiyorsa **tahmin yok**, rapora "belirsiz".
- Syllabus → Sonnet: haftalık plan (konu, yazıldığı gibi tarih, okuma, lab, sınav), kitaplar,
  sınavlar. Yazılı hafta tarihleri dönem başına göre kodda kontrol edilir ("tarih uyuşmuyor").
- Kitap / lab kitabı → içindekiler (PDF yer imleri, yoksa basılı içindekiler sayfası) +
  bölüm → hafta eşlemesi (önce kodda: okumadaki "1.3, 1.4"; kalanı tek bir Sonnet çağrısı).
  Kitabın yalnız haftaya eşlenen bölümleri gömülür (CPU); lab kitabı tamamen.
- Ödev / lab föyü → çalıştırdığı haftalar.
- Aynı dosya (SHA-256) ikinci kez okunmaz; `--force` yeniden okur, `--only <regex>` tek dosya.

## 3. Paket

```powershell
docker compose exec api python -m app.materials.bundle export
# -> data\bundles\materials-YYYYMMDD-HHMM\  manifest.json, data.json.gz, files\<sha256>.<ext>
```

Pakette veritabanı kimliği yok: dersler kod (ve takma ad), dosyalar SHA-256 ile eşleşir;
embedding'ler aynen taşınır (yeniden hesaplanmaz). Model farklıysa yükleme reddedilir.

## 4. Canlıya yükleme (Görkem çalıştırır)

Önce materyal kodunu içeren sürüm canlıda olmalı (`main`'e birleştir, `.\scripts\deploy-live.ps1`;
yeni tablolar o migration'la gelir). Sonra:

```powershell
.\scripts\import-materials-live.ps1 -DryRun      # yalnız rapor: ne eklenecek / güncellenecek
.\scripts\import-materials-live.ps1              # yedek -> kuru deneme -> yükleme
.\scripts\import-materials-live.ps1 -Undo <id>   # geri al (yine önce yedek)
```

- Yedek: `backups\preimport\yaver-preimport-<zaman>.sql.gz`; her yükleme / geri alma
  `backups\preimport\imports.log`'a change set kimliğiyle yazılır.
- Tekrar çalıştırmak güvenli: aynı paket ikinci kez hiçbir şey yazmaz.
- Yükleme tek transaction: yarıda hata olursa hiçbir şey yazılmaz.
- Geri alma: yüklemenin eklediği her şey silinir, güncellediği satırlar eski hâline döner.
