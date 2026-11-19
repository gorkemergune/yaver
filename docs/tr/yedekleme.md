# Yedekleme ve geri yükleme

> ⚠️ **`docker compose down -v` verini siler.** `-v` bayrağı `pgdata` volume'ünü, yani ders
> programın, sohbet geçmişin ve harcama kayıtlarınla birlikte veritabanını kalıcı olarak siler.
> Durdurmak için `docker compose down` (bayraksız) ya da `docker compose stop` yeterli.

## Otomatik yedek

API her açılışta en yeni yedeğe bakar; 24 saatten eskiyse (ya da hiç yoksa) arka planda
`pg_dump` ile yeni bir yedek alır:

- Dosya: `backups/yaver-YYYYMMDD-HHMMSS.sql.gz` (saat UTC), en yeni 14 tanesi tutulur.
- Klasör: `.env` içindeki `BACKUP_DIR` (varsayılan `./backups`, repoda `.gitignore`'da).
- Ayarlar: `BACKUP_KEEP` (14), `BACKUP_MAX_AGE_HOURS` (24), `BACKUP_ON_STARTUP` (true).

Yedek başka bir diske ya da buluta kopyalanmadıkça bilgisayar arızasına karşı koruma sağlamaz;
`BACKUP_DIR`'i senkronize edilen bir klasöre (OneDrive vb.) yönlendirmek kolay bir çözüm.

## Elle yedek

```powershell
.\scripts\backup.ps1            # Windows (PowerShell 7)
.\scripts\backup.ps1 list
```
```bash
scripts/backup.sh               # Mac / Linux / Git Bash
scripts/backup.sh list
```

## Geri yükleme

Önce ayrı bir veritabanına yükleyip bakmak güvenlidir:

```powershell
.\scripts\backup.ps1 restore backups\yaver-20261120-030000.sql.gz            # -> yaver_restore
docker compose exec db psql -U yaver -d yaver_restore -c "select count(*) from recurring_blocks"
```

Canlı veritabanının üzerine (tablolar yedektekiyle değiştirilir):

```powershell
docker compose stop api
.\scripts\backup.ps1 restore backups\yaver-20261120-030000.sql.gz yaver -Yes
docker compose start api
```

Script canlı veritabanına `-Yes` (bash'te `--yes`) olmadan yazmayı reddeder.
