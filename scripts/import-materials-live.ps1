# Loads a course-materials bundle into the LIVE stack (project yaver-live).
# PowerShell 7, from the repo folder, AFTER deploy-live.ps1 has put a release with the
# materials code (app.materials.bundle, migration d25f6a819ed6) on live.
#
# The bundle is made in dev:  docker compose exec api python -m app.materials.bundle export
#   -> data\bundles\materials-YYYYMMDD-HHMM\ (gitignored: manifest.json, data.json.gz, files\)
#
#   .\scripts\import-materials-live.ps1                          the newest bundle in data\bundles
#   .\scripts\import-materials-live.ps1 -Bundle data\bundles\materials-20261122-0300
#   .\scripts\import-materials-live.ps1 -DryRun                  only what would be written (no backup)
#   .\scripts\import-materials-live.ps1 -Undo <change_set_id>    take an import back (backup first)
#
# 1. checks: the bundle (manifest), the live api running and knowing the bundle command
# 2. backup of the live database -> backups\preimport\yaver-preimport-<time>.sql.gz
# 3. the bundle is copied into the api container (/tmp), a dry run prints the plan, then the
#    import: one transaction, one change set (courses by code / alias, files by SHA-256)
# 4. the copy is removed; the change set id goes to backups\preimport\imports.log
# Idempotent: running it again writes nothing ("same" everywhere). A failed import writes
# nothing either (one transaction); the backup is only for "I want yesterday back".
# Guide: docs/tr/materyaller.md
param(
    [string]$Bundle,
    [switch]$DryRun,
    [string]$Undo,
    # For trying the script on another stack (e.g. yaver-dev); default the live project.
    [string]$Project
)
. (Join-Path $PSScriptRoot "live-common.ps1")
if ($Project) { $Live.Project = $Project }

$Stamp = (Get-Date).ToString("yyyyMMdd-HHmmss")
$PreImportDir = Join-Path $Live.BackupDir "preimport"

function Get-Api {
    $api = Get-ServiceContainer $Live.Project "api"
    if (-not $api) { throw "the api of $($Live.Project) is not running (.\scripts\live.ps1 ps)" }
    docker exec $api python -c "import app.materials.bundle" 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw "the running release of $($Live.Project) has no app.materials.bundle: merge the materials branch into main and run .\scripts\deploy-live.ps1 first"
    }
    return $api
}

# Runs `python -m app.materials.bundle ...` in the api; returns its JSON report.
function Invoke-Bundle([string]$Api, [string[]]$Arguments) {
    $out = docker exec $Api python -m app.materials.bundle @Arguments 2>$null
    $code = $LASTEXITCODE
    $text = ($out | Out-String).Trim()
    try { $report = $text | ConvertFrom-Json -AsHashtable } catch { throw "bundle $($Arguments[0]) gave no report (exit $code): $text" }
    if ($report.error) { throw "bundle $($Arguments[0]): $($report.error)" }
    if ($code -ne 0) { throw "bundle $($Arguments[0]) failed (exit $code)" }
    return $report
}

function Show-Report([hashtable]$Report) {
    $created = @($Report.courses_created) -join ", "
    Write-Ok ("courses created: {0}" -f ($created ? $created : "-"))
    if (@($Report.courses_updated).Count) { Write-Ok ("courses updated: {0}" -f (@($Report.courses_updated) -join ", ")) }
    foreach ($key in "materials", "weeks", "books", "sources") {
        $c = $Report[$key]
        if ($c) { Write-Ok ("{0,-10} new {1}, updated {2}, same {3}" -f $key, $c.new, $c.updated, $c.same) }
    }
    Write-Ok ("passages written: {0}, files written: {1}" -f $Report.passages_written, $Report.files_written)
    foreach ($note in @($Report.notes)) { if ($note) { Write-Warn $note } }
}

function Backup-BeforeImport {
    $file = Join-Path $PreImportDir "yaver-preimport-$Stamp.sql.gz"
    Write-Step "Backup of $($Live.Project)'s database -> $file"
    Backup-LiveDb $file
    Write-Ok ("{0:N0} bytes" -f (Get-Item $file).Length)
    return $file
}

function Add-ImportLog([string]$Line) {
    New-Item -ItemType Directory -Force $PreImportDir | Out-Null
    Add-Content -Encoding utf8 (Join-Path $PreImportDir "imports.log") ("{0}  {1}" -f (Get-Date).ToString("yyyy-MM-dd HH:mm:ss"), $Line)
}

# ---- undo ----------------------------------------------------------------------------------
if ($Undo) {
    if ($Undo -notmatch '^[0-9a-fA-F-]{36}$') { throw "-Undo takes a change set id (from imports.log)" }
    $api = Get-Api
    $backup = Backup-BeforeImport
    Write-Step "Undo $Undo"
    $result = Invoke-Bundle $api @("undo", $Undo)
    if ($result.undone) { Write-Ok "$($result.undone) changes undone" } else { Write-Warn $result.note }
    Add-ImportLog "undo $Undo ($($result.undone) changes)  project=$($Live.Project)  backup=$backup"
    exit 0
}

# ---- import --------------------------------------------------------------------------------
if (-not $Bundle) {
    $newest = Get-ChildItem (Join-Path $Root "data\bundles") -Directory -ErrorAction SilentlyContinue |
        Where-Object { Test-Path (Join-Path $_.FullName "manifest.json") } |
        Sort-Object Name -Descending | Select-Object -First 1
    if (-not $newest) { throw "no bundle in data\bundles (make one in dev: docker compose exec api python -m app.materials.bundle export)" }
    $Bundle = $newest.FullName
}
$BundleDir = (Resolve-Path $Bundle).Path
$manifestFile = Join-Path $BundleDir "manifest.json"
if (-not (Test-Path $manifestFile)) { throw "$BundleDir has no manifest.json" }
$manifest = Get-Content $manifestFile -Raw | ConvertFrom-Json
Write-Step "Bundle $(Split-Path $BundleDir -Leaf) (made $($manifest.created_at))"
Write-Ok ("courses: {0}" -f ($manifest.courses -join ", "))
Write-Ok ("{0} materials, {1} passages, {2} weeks, {3} books, {4} sources" -f $manifest.counts.materials, $manifest.counts.passages, $manifest.counts.weeks, $manifest.counts.books, $manifest.counts.sources)

$api = Get-Api
$backup = $null
if (-not $DryRun) { $backup = Backup-BeforeImport }

$inside = "/tmp/yaver-bundle-$Stamp"
Write-Step "Copying the bundle into the api ($($Live.Project))"
Invoke-Native "docker cp" { docker cp $BundleDir "${api}:$inside" | Out-Null }
try {
    Write-Step "Dry run (nothing written)"
    $plan = Invoke-Bundle $api @("import", $inside, "--dry-run")
    Show-Report $plan
    if ($DryRun) {
        Write-Ok "(-DryRun: nothing written)"
    } elseif (-not $plan.change_set_id) {
        Write-Step "Nothing to do: everything in the bundle is already there"
        Add-ImportLog "import $(Split-Path $BundleDir -Leaf): nothing new  project=$($Live.Project)"
    } else {
        Write-Step "Import"
        $done = Invoke-Bundle $api @("import", $inside)
        Show-Report $done
        Add-ImportLog "import $(Split-Path $BundleDir -Leaf) change_set=$($done.change_set_id)  project=$($Live.Project)  backup=$backup"
        Write-Step "Done. To take it back:"
        Write-Host "    .\scripts\import-materials-live.ps1 -Undo $($done.change_set_id)"
    }
} finally {
    docker exec -u root $api rm -rf $inside | Out-Null
}
