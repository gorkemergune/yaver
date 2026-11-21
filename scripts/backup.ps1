# Yaver database backups (Windows PowerShell 7). Needs the stack's `db` container running.
# Default: the LIVE stack (project yaver-live, the real data). -Stack dev: the development
# database (project yaver-dev); its dumps go to $BACKUP_DIR\dev so they never mix with the real ones.
#
#   .\scripts\backup.ps1                              new backup -> $BACKUP_DIR\yaver-YYYYMMDD-HHMMSS.sql.gz (UTC),
#                                                     keeps the newest $BACKUP_KEEP (14)
#   .\scripts\backup.ps1 list                         backups, newest first
#   .\scripts\backup.ps1 restore FILE [DB]            restore into DB (default: yaver_restore, created if missing)
#   .\scripts\backup.ps1 restore FILE yaver -Yes      restore over the database itself
#                                                     (stop the api first: .\scripts\live.ps1 stop api)
#   .\scripts\backup.ps1 -Stack dev                   the dev stack instead
#
# BACKUP_DIR, BACKUP_KEEP, POSTGRES_USER, POSTGRES_DB come from the environment or .env.
# scripts\deploy-live.ps1 keeps its own pre-deploy dumps in $BACKUP_DIR\predeploy.
param(
    [Parameter(Position = 0)][ValidateSet("backup", "list", "restore")][string]$Command = "backup",
    [Parameter(Position = 1)][string]$File,
    [Parameter(Position = 2)][string]$Target = "yaver_restore",
    [ValidateSet("live", "dev")][string]$Stack = "live",
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
$Project = if ($Stack -eq "live") { Get-EnvValue "YAVER_LIVE_PROJECT" "yaver-live" } else { "yaver-dev" }
if ($Stack -eq "dev") { $BackupDir = Join-Path $BackupDir "dev" }
$DbContainer = "$(docker ps -q --filter "label=com.docker.compose.project=$Project" --filter "label=com.docker.compose.service=db")".Trim()
if (-not $DbContainer -and $Command -ne "list") {
    throw "The db container of $Project is not running (live: .\scripts\live.ps1 up -d db, dev: docker compose up -d db)."
}

function Invoke-Db([string[]]$Arguments) {
    & docker exec -i $DbContainer @Arguments
    if ($LASTEXITCODE -ne 0) { throw "docker exec db ($Project) failed: $($Arguments -join ' ')" }
}

function New-Backup {
    New-Item -ItemType Directory -Force $BackupDir | Out-Null
    $name = "yaver-{0:yyyyMMdd-HHmmss}.sql.gz" -f (Get-Date).ToUniversalTime()
    $file = Join-Path $BackupDir $name
    # Dump and gzip inside the container, then copy the file out (no binary data through pipes).
    Invoke-Db @("sh", "-c", "pg_dump -U '$DbUser' -d '$DbName' --clean --if-exists --no-owner --no-privileges | gzip > /tmp/$name")
    & docker cp "${DbContainer}:/tmp/$name" "$file.part" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "docker cp failed" }
    Invoke-Db @("rm", "-f", "/tmp/$name")
    Move-Item -Force "$file.part" $file
    Write-Output ("backup ({0}): {1} ({2} bytes)" -f $Project, $file, (Get-Item $file).Length)
    Get-ChildItem $BackupDir -Filter "yaver-*.sql.gz" | Sort-Object Name -Descending |
        Select-Object -Skip $Keep | ForEach-Object {
            Remove-Item $_.FullName
            Write-Output "removed: $($_.FullName)"
        }
}

function Restore-Backup {
    if (-not $File -or -not (Test-Path $File)) { throw "usage: backup.ps1 restore FILE [DB] [-Yes]" }
    if ($Target -eq $DbName -and -not $Yes) {
        throw "Refusing to overwrite the database '$DbName' of $Project without -Yes (stop the api first)."
    }
    $exists = "$(& docker exec -i $DbContainer psql -U $DbUser -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='$Target'")".Trim()
    if ($exists -ne "1") {
        Invoke-Db @("createdb", "-U", $DbUser, $Target)
        Invoke-Db @("psql", "-q", "-U", $DbUser, "-d", $Target, "-c", "CREATE EXTENSION IF NOT EXISTS vector") | Out-Null
    }
    & docker cp $File "${DbContainer}:/tmp/yaver-restore.sql.gz" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "docker cp failed" }
    Invoke-Db @("sh", "-c", "gunzip -c /tmp/yaver-restore.sql.gz | psql -v ON_ERROR_STOP=1 -q -U '$DbUser' -d '$Target' > /dev/null")
    Invoke-Db @("rm", "-f", "/tmp/yaver-restore.sql.gz")
    Write-Output "restored $File into database '$Target' ($Project)"
}

switch ($Command) {
    "backup" { New-Backup }
    "list" { Get-ChildItem $BackupDir -Filter "yaver-*.sql.gz" -ErrorAction SilentlyContinue | Sort-Object Name -Descending | ForEach-Object { $_.FullName } }
    "restore" { Restore-Backup }
}
