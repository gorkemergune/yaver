# Yedekleme ve geri yükleme

> Gerçek veri **canlı** kurulumda (`yaver-live`, volume `yaver_pgdata`); aşağıdaki komutlar
> varsayılan olarak onu yedekler. Geliştirme veritabanı için `-Stack dev` (bash: `STACK=dev`).
> Kurulumlar: [canli-ve-gelistirme.md](canli-ve-gelistirme.md).
>
> ⚠️ Canlının veritabanı volume'ü "external"dır: `docker compose down -v` onu silemez ve
> `.\scripts\live.ps1` `down -v`'yi reddeder. Yine de `docker volume rm yaver_pgdata` yazma.
> Geliştirme stack'inde `docker compose down -v` geliştirme veritabanını siler (gerçeğe dokunmaz).

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
docker exec yaver-live-db-1 psql -U yaver -d yaver_restore -c "select count(*) from recurring_blocks"
```

Canlı veritabanının üzerine (tablolar yedektekiyle değiştirilir):

```powershell
.\scripts\live.ps1 stop api
.\scripts\backup.ps1 restore backups\yaver-20261120-030000.sql.gz yaver -Yes
.\scripts\live.ps1 start api
```

Deploy'dan hemen önceki hâle dönmek için `.\scripts\rollback-live.ps1 -RestoreBackup` daha kolay
(yedek `backups\predeploy\` altında).

Script canlı veritabanına `-Yes` (bash'te `--yes`) olmadan yazmayı reddeder.
