# Shared by deploy-live.ps1, rollback-live.ps1 and live.ps1 (dot-sourced, PowerShell 7).
#
# Where things live:
#   $Root                         the repo folder the scripts run from: .env, config\, uploads\, backups\
#   $StateDir = $YAVER_RELEASES\<project>   (default %USERPROFILE%\yaver-releases\yaver-live)
#     state.json                  current / previous release and the deploy history
#     releases\<tag>\             the exported source of each release (git archive), its own
#                                 docker-compose.live.yml is what runs
#     logs\deploy-<tag>.log       full transcript of each deploy / rollback
#   images <image>-api:<tag>, <image>-web:<tag>   (default image prefix yaver-live)
#
# Overridable (a sandbox copy for trying the scripts uses all of them):
#   YAVER_LIVE_PROJECT (yaver-live)  LIVE_WEB_PORT (8080)  YAVER_LIVE_DB_VOLUME (yaver_pgdata)
#   YAVER_LIVE_MODELS_VOLUME (yaver_models)  YAVER_LIVE_IMAGE (yaver-live)  YAVER_RELEASES

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

function Get-EnvValue([string]$Name, [string]$Default) {
    $fromEnv = [Environment]::GetEnvironmentVariable($Name)
    if ($fromEnv) { return $fromEnv }
    $file = Join-Path $Root ".env"
    if (Test-Path $file) {
        $line = Get-Content $file | Where-Object { $_ -match "^$Name=" } | Select-Object -Last 1
        if ($line) {
            $value = ($line -replace "^$Name=", "").Trim().Trim('"')
            if ($value) { return $value }
        }
    }
    return $Default
}

$Live = [ordered]@{
    Project      = Get-EnvValue "YAVER_LIVE_PROJECT" "yaver-live"
    WebPort      = Get-EnvValue "LIVE_WEB_PORT" "8080"
    DbVolume     = Get-EnvValue "YAVER_LIVE_DB_VOLUME" "yaver_pgdata"
    ModelsVolume = Get-EnvValue "YAVER_LIVE_MODELS_VOLUME" "yaver_models"
    Image        = Get-EnvValue "YAVER_LIVE_IMAGE" "yaver-live"
    DbUser       = Get-EnvValue "POSTGRES_USER" "yaver"
    DbName       = Get-EnvValue "POSTGRES_DB" "yaver"
    BackupDir    = Get-EnvValue "BACKUP_DIR" "./backups"
}
if (-not [IO.Path]::IsPathRooted($Live.BackupDir)) { $Live.BackupDir = Join-Path $Root $Live.BackupDir }
$ReleasesRoot = Get-EnvValue "YAVER_RELEASES" (Join-Path $HOME "yaver-releases")
$StateDir = Join-Path $ReleasesRoot $Live.Project
$StateFile = Join-Path $StateDir "state.json"
# compose interpolation of docker-compose.live.yml reads these from the process environment
$env:LIVE_WEB_PORT = $Live.WebPort
$env:YAVER_LIVE_DB_VOLUME = $Live.DbVolume
$env:YAVER_LIVE_MODELS_VOLUME = $Live.ModelsVolume
$env:YAVER_LIVE_IMAGE = $Live.Image

function Write-Step([string]$Text) { Write-Host "`n==> $Text" -ForegroundColor Cyan }
function Write-Ok([string]$Text) { Write-Host "    $Text" -ForegroundColor Green }
function Write-Warn([string]$Text) { Write-Host "    $Text" -ForegroundColor Yellow }

function Get-LiveState {
    if (Test-Path $StateFile) {
        $state = Get-Content $StateFile -Raw | ConvertFrom-Json -AsHashtable
        $state.history = @($state.history | Where-Object { $_ })  # one entry comes back as an object
        return $state
    }
    return @{ current = $null; previous = $null; history = @() }
}

function Save-LiveState([hashtable]$State) {
    New-Item -ItemType Directory -Force $StateDir | Out-Null
    ConvertTo-Json -InputObject $State -Depth 6 | Set-Content -Encoding utf8 "$StateFile.part"
    Move-Item -Force "$StateFile.part" $StateFile
}

function Add-History([hashtable]$State, [hashtable]$Entry) {
    $Entry.at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    $State.history = @(@($Entry) + @($State.history) | Select-Object -First 50)
}

function Get-ReleaseDir([string]$Tag) { Join-Path (Join-Path $StateDir "releases") $Tag }

function Invoke-Native([string]$What, [scriptblock]$Command) {
    & $Command
    if ($LASTEXITCODE -ne 0) { throw "$What failed (exit $LASTEXITCODE)" }
}

# docker compose for the live project, with the compose file of release $Tag.
function Invoke-LiveCompose([string]$Tag, [string[]]$Arguments) {
    $compose = Join-Path (Get-ReleaseDir $Tag) "docker-compose.live.yml"
    if (-not (Test-Path $compose)) { throw "release $Tag has no docker-compose.live.yml ($compose)" }
    $env:YAVER_LIVE_TAG = $Tag
    $envArgs = @()
    if (Test-Path (Join-Path $Root ".env")) { $envArgs = @("--env-file", (Join-Path $Root ".env")) }
    & docker compose -p $Live.Project -f $compose --project-directory $Root @envArgs @Arguments
    if ($LASTEXITCODE -ne 0) { throw "docker compose $($Arguments -join ' ') failed (exit $LASTEXITCODE)" }
}

function Get-ServiceContainer([string]$Project, [string]$Service, [switch]$All) {
    $filter = @("--filter", "label=com.docker.compose.project=$Project", "--filter", "label=com.docker.compose.service=$Service")
    $id = if ($All) { docker ps -aq @filter } else { docker ps -q @filter }
    return "$id".Trim()
}

function Wait-ContainerHealthy([string]$Container, [int]$Seconds = 120) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        $state = "$(docker inspect --format '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{end}}' $Container 2>$null)".Trim()
        if ($state -eq "running healthy" -or $state -eq "running") { return }
        if ($state -like "exited*" -or $state -like "dead*") { throw "container $Container stopped: $state" }
        Start-Sleep -Seconds 2
    }
    throw "container $Container not healthy after $Seconds s"
}

function Wait-HttpOk([string]$Url, [int]$Seconds = 90) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $res = Invoke-WebRequest -UseBasicParsing $Url -TimeoutSec 5
            if ($res.StatusCode -eq 200) { return }
        } catch { Start-Sleep -Seconds 2 }
    }
    throw "$Url did not answer 200 within $Seconds s"
}

# pg_dump of the live database -> $File (gzip), made inside the db container.
function Backup-LiveDb([string]$File) {
    $db = Get-ServiceContainer $Live.Project "db"
    if (-not $db) { throw "live db container is not running" }
    New-Item -ItemType Directory -Force (Split-Path $File) | Out-Null
    $tmp = "/tmp/" + (Split-Path $File -Leaf)
    Invoke-Native "pg_dump" { docker exec $db sh -c "pg_dump -U '$($Live.DbUser)' -d '$($Live.DbName)' --clean --if-exists --no-owner --no-privileges | gzip > $tmp" }
    Invoke-Native "docker cp" { docker cp "${db}:$tmp" "$File.part" | Out-Null }
    docker exec $db rm -f $tmp | Out-Null
    Move-Item -Force "$File.part" $File
    if ((Get-Item $File).Length -lt 200) { throw "backup $File is suspiciously small" }
}

# Replaces the live database with a dump: drop, create, restore. The api must be stopped.
function Restore-LiveDb([string]$File) {
    $db = Get-ServiceContainer $Live.Project "db"
    if (-not $db) { throw "live db container is not running" }
    $u = $Live.DbUser; $n = $Live.DbName
    Invoke-Native "docker cp" { docker cp $File "${db}:/tmp/yaver-restore.sql.gz" | Out-Null }
    Invoke-Native "drop database" { docker exec $db dropdb -U $u --force --if-exists $n }
    Invoke-Native "create database" { docker exec $db createdb -U $u $n }
    Invoke-Native "create extension" { docker exec $db psql -q -U $u -d $n -c "CREATE EXTENSION IF NOT EXISTS vector" | Out-Null }
    Invoke-Native "restore" { docker exec $db sh -c "gunzip -c /tmp/yaver-restore.sql.gz | psql -v ON_ERROR_STOP=1 -q -U '$u' -d '$n' > /dev/null" }
    docker exec $db rm -f /tmp/yaver-restore.sql.gz | Out-Null
}

function Get-LiveRevision {
    $db = Get-ServiceContainer $Live.Project "db"
    if (-not $db) { return $null }
    $rev = "$(docker exec $db psql -U $Live.DbUser -d $Live.DbName -tAc 'SELECT version_num FROM alembic_version' 2>$null)".Trim()
    if ($LASTEXITCODE -ne 0) { return $null }
    return $rev
}

# Smoke checks against the running live stack (login with APP_PASSWORD from .env).
function Test-LiveSmoke {
    & (Join-Path $PSScriptRoot "smoke.ps1") -Project $Live.Project -BaseUrl "http://127.0.0.1:$($Live.WebPort)" -NoChat
    if ($LASTEXITCODE -ne 0) { throw "smoke checks on the live stack failed" }
}

# Refuses when another compose project uses the real database volume: two PostgreSQL servers
# on one data directory corrupt it (the old single stack "yaver" used the same volume).
function Assert-DbVolumeFree {
    $users = docker ps -q --filter "volume=$($Live.DbVolume)"
    foreach ($id in $users) {
        $project = "$(docker inspect --format '{{index .Config.Labels "com.docker.compose.project"}}' $id)".Trim()
        if ($project -ne $Live.Project) {
            $name = "$(docker inspect --format '{{.Name}}' $id)".Trim("/ ")
            $hint = if ($project) { "docker compose -p $project stop" } else { "docker stop $name" }
            throw "the database volume $($Live.DbVolume) is in use by $name (project '$project'). Stop it first: $hint"
        }
    }
}
