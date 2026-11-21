# Puts the LIVE stack back on an earlier release (PowerShell 7, from the repo folder).
#
#   .\scripts\rollback-live.ps1                     the previous release (state.json "previous")
#   .\scripts\rollback-live.ps1 -To 20261121-2215-1a2b3c4    a release that is still kept
#   .\scripts\rollback-live.ps1 -RestoreBackup      also put the database back to the dump taken
#                                                   right before the current release was deployed
#                                                   (everything written since is lost; asked first)
#   .\scripts\rollback-live.ps1 -List               releases that can be rolled back to
#
# Without -RestoreBackup the database stays as it is. That is right unless the current release
# changed the schema in a way the older code can't read (the script warns when the revision
# the old release expects differs from the one in the database).
param(
    [string]$To,
    [switch]$RestoreBackup,
    [switch]$Yes,
    [switch]$List
)
. (Join-Path $PSScriptRoot "live-common.ps1")

$state = Get-LiveState
$kept = @(Get-ChildItem (Join-Path $StateDir "releases") -Directory -ErrorAction SilentlyContinue | Sort-Object Name -Descending | ForEach-Object Name)
if ($List) {
    Write-Host "current:  $($state.current)"
    Write-Host "previous: $($state.previous)"
    Write-Host "kept releases: $($kept -join ', ')"
    $state.history | Select-Object -First 10 | ForEach-Object {
        Write-Host ("  {0}  {1,-8} {2}  {3}" -f $_.at, $_.result, $_.tag, $(if ($_.reason) { $_.reason } else { $_.subject }))
    }
    exit 0
}

$current = $state.current
if (-not $To) { $To = $state.previous }
if (-not $To) { throw "no previous release recorded; pass -To <tag> (see -List)" }
if ($To -eq $current) { throw "$To is already the current release" }
if ($To -notin $kept) { throw "release $To is no longer kept (kept: $($kept -join ', '))" }
foreach ($kind in "api", "web") {
    docker image inspect "$($Live.Image)-${kind}:$To" *> $null
    if ($LASTEXITCODE -ne 0) { throw "image $($Live.Image)-${kind}:$To is missing" }
}
Assert-DbVolumeFree

$entry = $state.history | Where-Object { $_.tag -eq $current -and $_.kind -eq "deploy" -and $_.result -eq "ok" } | Select-Object -First 1
$backup = if ($entry) { $entry.backup } else { $null }
$logFile = Join-Path $StateDir "logs\rollback-$((Get-Date).ToString('yyyyMMdd-HHmm'))-to-$To.log"
New-Item -ItemType Directory -Force (Split-Path $logFile) | Out-Null
Start-Transcript -Path $logFile -Append | Out-Null
$result = @{ kind = "rollback"; tag = $To; from = $current; subject = "rollback from $current" }
try {
    Write-Host "Rollback: $current -> $To"
    $revision = Get-LiveRevision
    $expected = ($state.history | Where-Object { $_.tag -eq $To -and $_.kind -eq "deploy" -and $_.result -eq "ok" } | Select-Object -First 1).revision_after
    if ($expected -and $revision -and $expected -ne $revision -and -not $RestoreBackup) {
        Write-Warn "the database is at schema $revision, $To was deployed at $expected."
        Write-Warn "If $To fails to start, run again with -RestoreBackup ($backup)."
    }
    if ($current) { Invoke-LiveCompose $current @("stop", "api", "web") }
    if ($RestoreBackup) {
        if (-not $backup -or -not (Test-Path $backup)) { throw "no pre-deploy backup recorded for $current" }
        if (-not $Yes) {
            $answer = Read-Host "Restore $backup over the live database? Everything written since it was taken is lost. (evet/hayır)"
            if ($answer -ne "evet") { throw "cancelled; nothing restored (api and web are stopped: .\scripts\live.ps1 up -d)" }
        }
        Write-Step "restore $backup"
        Restore-LiveDb $backup
        $result.restored = $backup
    }
    Write-Step "start $To"
    Invoke-LiveCompose $To @("up", "-d", "--remove-orphans")
    Wait-ContainerHealthy (Get-ServiceContainer $Live.Project "api") 150
    Wait-HttpOk "http://127.0.0.1:$($Live.WebPort)/api/health/ready" 60
    Test-LiveSmoke
    $state.current = $To
    $state.previous = $current
    $result.result = "ok"
    Add-History $state $result
    Save-LiveState $state
    Write-Host "`nLIVE IS ON $To (was $current)" -ForegroundColor Green
    exit 0
}
catch {
    Write-Host "`nROLLBACK FAILED: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "log: $logFile"
    $result.result = "failed"
    $result.reason = "$($_.Exception.Message)"
    Add-History $state $result
    Save-LiveState $state
    exit 1
}
finally {
    Stop-Transcript | Out-Null
}
