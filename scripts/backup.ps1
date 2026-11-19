# Yaver database backups (Windows PowerShell 7). Needs the `db` container running.
#
#   .\scripts\backup.ps1                              new backup -> $BACKUP_DIR\yaver-YYYYMMDD-HHMMSS.sql.gz (UTC),
#                                                     keeps the newest $BACKUP_KEEP (14)
#   .\scripts\backup.ps1 list                         backups, newest first
#   .\scripts\backup.ps1 restore FILE [DB]            restore into DB (default: yaver_restore, created if missing)
#   .\scripts\backup.ps1 restore FILE yaver -Yes      restore over the live database
#                                                     (stop the api first: docker compose stop api)
#
# BACKUP_DIR, BACKUP_KEEP, POSTGRES_USER, POSTGRES_DB come from the environment or .env.
param(
    [Parameter(Position = 0)][ValidateSet("backup", "list", "restore")][string]$Command = "backup",
    [Parameter(Position = 1)][string]$File,
    [Parameter(Position = 2)][string]$Target = "yaver_restore",
    [switch]$Yes
)
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

function Get-EnvValue([string]$Name, [string]$Default) {
    $fromEnv = [Environment]::GetEnvironmentVariable($Name)
    if ($fromEnv) { return $fromEnv }
    if (Test-Path .env) {
        $line = Get-Content .env | Where-Object { $_ -match "^$Name=" } | Select-Object -Last 1
        if ($line) {
            $value = ($line -replace "^$Name=", "").Trim().Trim('"')
            if ($value) { return $value }
        }
    }
    return $Default
}

$BackupDir = Get-EnvValue "BACKUP_DIR" "./backups"
$Keep = [int](Get-EnvValue "BACKUP_KEEP" "14")
$DbUser = Get-EnvValue "POSTGRES_USER" "yaver"
$DbName = Get-EnvValue "POSTGRES_DB" "yaver"

function Invoke-Db([string[]]$Arguments) {
    & docker compose exec -T db @Arguments
    if ($LASTEXITCODE -ne 0) { throw "docker compose exec db failed: $($Arguments -join ' ')" }
}

function New-Backup {
    New-Item -ItemType Directory -Force $BackupDir | Out-Null
    $name = "yaver-{0:yyyyMMdd-HHmmss}.sql.gz" -f (Get-Date).ToUniversalTime()
    $file = Join-Path $BackupDir $name
    # Dump and gzip inside the container, then copy the file out (no binary data through pipes).
    Invoke-Db @("sh", "-c", "pg_dump -U '$DbUser' -d '$DbName' --clean --if-exists --no-owner --no-privileges | gzip > /tmp/$name")
    & docker compose cp "db:/tmp/$name" "$file.part" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "docker compose cp failed" }
    Invoke-Db @("rm", "-f", "/tmp/$name")
    Move-Item -Force "$file.part" $file
    Write-Output ("backup: {0} ({1} bytes)" -f $file, (Get-Item $file).Length)
    Get-ChildItem $BackupDir -Filter "yaver-*.sql.gz" | Sort-Object Name -Descending |
        Select-Object -Skip $Keep | ForEach-Object {
            Remove-Item $_.FullName
            Write-Output "removed: $($_.FullName)"
        }
}

function Restore-Backup {
    if (-not $File -or -not (Test-Path $File)) { throw "usage: backup.ps1 restore FILE [DB] [-Yes]" }
    if ($Target -eq $DbName -and -not $Yes) {
        throw "Refusing to overwrite the live database '$DbName' without -Yes (stop the api first)."
    }
    $exists = "$(& docker compose exec -T db psql -U $DbUser -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='$Target'")".Trim()
    if ($exists -ne "1") {
        Invoke-Db @("createdb", "-U", $DbUser, $Target)
        Invoke-Db @("psql", "-q", "-U", $DbUser, "-d", $Target, "-c", "CREATE EXTENSION IF NOT EXISTS vector") | Out-Null
    }
    & docker compose cp $File "db:/tmp/yaver-restore.sql.gz" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "docker compose cp failed" }
    Invoke-Db @("sh", "-c", "gunzip -c /tmp/yaver-restore.sql.gz | psql -v ON_ERROR_STOP=1 -q -U '$DbUser' -d '$Target' > /dev/null")
    Invoke-Db @("rm", "-f", "/tmp/yaver-restore.sql.gz")
    Write-Output "restored $File into database '$Target'"
}

switch ($Command) {
    "backup" { New-Backup }
    "list" { Get-ChildItem $BackupDir -Filter "yaver-*.sql.gz" -ErrorAction SilentlyContinue | Sort-Object Name -Descending | ForEach-Object { $_.FullName } }
    "restore" { Restore-Backup }
}
