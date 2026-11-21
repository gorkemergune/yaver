# Deploys a commit (default: main's last commit) to the LIVE stack (project yaver-live).
# PowerShell 7, from the repo folder:  .\scripts\deploy-live.ps1
#
# 1. export the commit into its own folder (git archive; nothing in the working tree is used)
# 2. build its images (api, web, and the api dev image for pytest)
# 3. test them in a throwaway stack (project yaver-e2e-release, ports 8092/8003/5435):
#      pytest (no live LLM tests) -> smoke checks -> Playwright e2e without LLM
# 4. back up the live database (backups\predeploy\), rehearse the migrations on that copy
# 5. switch: stop the old api, alembic upgrade head, start the new images
# 6. health check (container healthy + smoke checks through the web port)
# Any failure before step 5: the live stack is not touched. A failure in 5-6: back to the
# previous images (and the pre-deploy backup when the migration had changed the schema).
# Every run writes logs\deploy-<tag>.log and a line in state.json (see live-common.ps1).
#
#   .\scripts\deploy-live.ps1                      main
#   .\scripts\deploy-live.ps1 -Ref 1a2b3c4         a specific commit / branch / tag
#   .\scripts\deploy-live.ps1 -KeepCandidate       leave the test stack running afterwards (inspect it)
#   .\scripts\deploy-live.ps1 -SkipE2E             without Playwright (pytest + smoke still run)
#   .\scripts\deploy-live.ps1 -NewDatabase         brand-new installation: create the empty database volume
#
# Guide: docs/tr/canli-ve-gelistirme.md
param(
    [string]$Ref = "main",
    [switch]$SkipE2E,
    [switch]$KeepCandidate,
    # A brand-new installation only: create the (empty) database volume when it doesn't exist.
    [switch]$NewDatabase,
    # For trying the script itself (sandbox): make that stage fail on purpose.
    [ValidateSet("", "tests", "health")][string]$SimulateFailure = ""
)
. (Join-Path $PSScriptRoot "live-common.ps1")

$Candidate = [ordered]@{
    Project = Get-EnvValue "YAVER_CANDIDATE_PROJECT" "yaver-e2e-release"
    WebPort = Get-EnvValue "YAVER_CANDIDATE_WEB_PORT" "8092"
    ApiPort = Get-EnvValue "YAVER_CANDIDATE_API_PORT" "8003"
    DbPort  = Get-EnvValue "YAVER_CANDIDATE_DB_PORT" "5435"
}
if (-not $Candidate.Project.StartsWith("yaver-e2e")) { throw "YAVER_CANDIDATE_PROJECT must start with yaver-e2e" }
$E2ePassword = "e2e-test-password"  # fixed in e2e/docker-compose.e2e.yml

# ---- preflight ---------------------------------------------------------------------------
New-Item -ItemType Directory -Force (Join-Path $StateDir "logs"), (Join-Path $StateDir "releases") | Out-Null
$lock = Join-Path $StateDir "deploy.lock"
if (Test-Path $lock) {
    throw "another deploy seems to be running ($lock, $(Get-Content $lock)). Delete the file if it is not."
}
docker info --format "{{.ServerVersion}}" *> $null
if ($LASTEXITCODE -ne 0) { throw "Docker is not running" }
if (-not (Test-Path (Join-Path $Root ".env"))) { throw ".env missing in $Root" }

$sha = "$(git -C $Root rev-parse --verify "$Ref^{commit}")".Trim()
if ($LASTEXITCODE -ne 0 -or -not $sha) { throw "unknown ref $Ref" }
$short = $sha.Substring(0, 7)
$subject = "$(git -C $Root log -1 --format=%s $sha)".Trim()
$tag = "{0:yyyyMMdd-HHmm}-{1}" -f (Get-Date), $short
$releaseDir = Get-ReleaseDir $tag
$logFile = Join-Path $StateDir "logs\deploy-$tag.log"
$state = Get-LiveState
$oldTag = $state.current
$result = @{ kind = "deploy"; tag = $tag; sha = $sha; subject = $subject; from = $oldTag }
$stage = "preflight"
$switched = $false
$candidateCompose = $null
$backupFile = $null
$oldRevision = $null

Set-Content -Path $lock -Value "$tag pid $PID"
Start-Transcript -Path $logFile -Append | Out-Null
try {
    Write-Host "Deploy $tag  ($short $subject)"
    Write-Host "live: project $($Live.Project), web :$($Live.WebPort), db volume $($Live.DbVolume); current release: $(if ($oldTag) { $oldTag } else { 'none (first deploy)' })"
    if (-not (docker volume ls -q --filter "name=^$($Live.DbVolume)$")) {
        if (-not $NewDatabase) {
            throw "database volume $($Live.DbVolume) does not exist. A brand-new installation: run again with -NewDatabase"
        }
        Invoke-Native "create volume" { docker volume create $Live.DbVolume | Out-Null }
        Write-Warn "created an empty database volume $($Live.DbVolume)"
    }
    if (-not (docker volume ls -q --filter "name=^$($Live.ModelsVolume)$")) {
        Invoke-Native "create volume" { docker volume create $Live.ModelsVolume | Out-Null }
    }
    Assert-DbVolumeFree

    # ---- 1. export ------------------------------------------------------------------------
    $stage = "export"
    Write-Step "export $short -> $releaseDir"
    New-Item -ItemType Directory -Force $releaseDir | Out-Null
    $tar = "$releaseDir.tar"
    Invoke-Native "git archive" { git -C $Root archive --format=tar -o $tar $sha }
    Invoke-Native "tar" { tar -xf $tar -C $releaseDir }
    Remove-Item $tar
    foreach ($needed in "docker-compose.live.yml", "e2e\docker-compose.e2e.yml") {
        if (-not (Test-Path (Join-Path $releaseDir $needed))) { throw "the release has no $needed" }
    }
    if (-not (Select-String -Quiet -Path (Join-Path $releaseDir "e2e\docker-compose.e2e.yml") -Pattern "E2E_API_IMAGE")) {
        throw "the release's e2e/docker-compose.e2e.yml can't run prebuilt images (E2E_API_IMAGE); it predates the live/dev split"
    }

    # ---- 2. build -------------------------------------------------------------------------
    $stage = "build"
    $apiImage = "$($Live.Image)-api:$tag"
    $webImage = "$($Live.Image)-web:$tag"
    $testImage = "$($Live.Image)-test:$tag"
    Write-Step "build $apiImage, $webImage, $testImage"
    $label = @("--label", "yaver.release=$tag", "--label", "yaver.sha=$sha")
    Invoke-Native "build api" { docker build -q --target prod -t $apiImage @label (Join-Path $releaseDir "backend") }
    Invoke-Native "build api (dev, pytest)" { docker build -q --target dev -t $testImage @label (Join-Path $releaseDir "backend") }
    Invoke-Native "build web" { docker build -q --target prod -t $webImage @label (Join-Path $releaseDir "web") }

    # ---- 3. test in a throwaway stack ---------------------------------------------------
    $stage = "tests"
    $env:E2E_API_IMAGE = $apiImage
    $env:E2E_WEB_IMAGE = $webImage
    $env:E2E_WEB_PORT = $Candidate.WebPort
    $env:E2E_API_PORT = $Candidate.ApiPort
    $env:E2E_DB_PORT = $Candidate.DbPort
    $candidateCompose = @("compose", "-p", $Candidate.Project, "-f", (Join-Path $releaseDir "e2e\docker-compose.e2e.yml"), "--env-file", (Join-Path $Root ".env"))
    Write-Step "test stack $($Candidate.Project) (web :$($Candidate.WebPort), api :$($Candidate.ApiPort))"
    docker @candidateCompose down -v *> $null  # leftovers of an interrupted run
    Invoke-Native "test stack up" { docker @candidateCompose up -d --no-build }
    Invoke-Native "migrations (empty db)" { docker @candidateCompose exec -T api alembic upgrade head }
    Invoke-Native "api restart" { docker @candidateCompose restart api }
    Wait-HttpOk "http://127.0.0.1:$($Candidate.ApiPort)/api/health/ready" 120
    Write-Ok "test stack ready"

    Write-Step "pytest"
    $network = "$($Candidate.Project)_default"
    Invoke-Native "pytest" {
        docker run --rm --network $network `
            -e "DATABASE_URL=postgresql+asyncpg://yaver_e2e:yaver_e2e@db:5432/yaver_e2e" `
            -v "$(Join-Path $releaseDir 'config'):/config:ro" -v "$(Join-Path $releaseDir 'examples'):/examples:ro" `
            $testImage pytest -q -p no:cacheprovider
    }
    Write-Ok "pytest passed"

    Write-Step "smoke checks (test stack)"
    & (Join-Path $PSScriptRoot "smoke.ps1") -Project $Candidate.Project -BaseUrl "http://127.0.0.1:$($Candidate.WebPort)" -Password $E2ePassword -NoChat
    if ($LASTEXITCODE -ne 0) { throw "smoke checks failed on the test stack" }

    if ($SkipE2E) {
        Write-Warn "Playwright e2e skipped (-SkipE2E)"
    } else {
        Write-Step "Playwright e2e (no LLM)"
        $e2eDir = Join-Path $releaseDir "e2e"
        Push-Location $e2eDir
        try {
            Invoke-Native "npm ci" { npm ci --no-audit --no-fund --loglevel=error }
            Invoke-Native "playwright install" { npx playwright install chromium }
            $env:E2E_WEB_URL = "http://127.0.0.1:$($Candidate.WebPort)"
            $env:E2E_API_URL = "http://127.0.0.1:$($Candidate.ApiPort)"
            $env:E2E_DB_CONTAINER = "$($Candidate.Project)-db-1"
            $env:E2E_WEB_CONTAINER = "$($Candidate.Project)-web-1"
            $env:LIVE = $null
            Invoke-Native "playwright" { npx playwright test --reporter=list }
        } finally {
            Pop-Location
        }
        Write-Ok "e2e passed"
    }
    if ($SimulateFailure -eq "tests") { throw "simulated test failure (-SimulateFailure tests)" }

    # ---- 4. backup + migration rehearsal on a copy -------------------------------------
    $stage = "backup"
    Write-Step "live database: start db, back up"
    Invoke-LiveCompose $tag @("up", "-d", "--wait", "db")
    $oldRevision = Get-LiveRevision
    $backupFile = Join-Path $Live.BackupDir "predeploy\yaver-predeploy-$tag.sql.gz"
    Backup-LiveDb $backupFile
    Write-Ok ("{0} ({1:N0} bytes), schema revision {2}" -f $backupFile, (Get-Item $backupFile).Length, $(if ($oldRevision) { $oldRevision } else { "none" }))

    $stage = "rehearsal"
    Write-Step "migration rehearsal on a copy of the live database"
    $candDb = Get-ServiceContainer $Candidate.Project "db"
    Invoke-Native "copy backup" { docker cp $backupFile "${candDb}:/tmp/rehearsal.sql.gz" | Out-Null }
    Invoke-Native "create rehearsal db" { docker exec $candDb sh -c "dropdb -U yaver_e2e --if-exists rehearsal && createdb -U yaver_e2e rehearsal && psql -q -U yaver_e2e -d rehearsal -c 'CREATE EXTENSION IF NOT EXISTS vector' >/dev/null" }
    Invoke-Native "restore copy" { docker exec $candDb sh -c "gunzip -c /tmp/rehearsal.sql.gz | psql -v ON_ERROR_STOP=1 -q -U yaver_e2e -d rehearsal >/dev/null" }
    Invoke-Native "alembic upgrade head (copy)" {
        docker run --rm --network $network -e "DATABASE_URL=postgresql+asyncpg://yaver_e2e:yaver_e2e@db:5432/rehearsal" $apiImage alembic upgrade head
    }
    Write-Ok "migrations apply cleanly to today's data"

    if (-not $KeepCandidate) {
        docker @candidateCompose down -v *> $null
    }

    # ---- 5. switch ----------------------------------------------------------------------
    $stage = "switch"
    Write-Step "switch to $tag"
    $switched = $true
    if (Get-ServiceContainer $Live.Project "api") {
        if ($oldTag) { Invoke-LiveCompose $oldTag @("stop", "api", "web") }
        else { Invoke-LiveCompose $tag @("stop", "api", "web") }
    }
    Invoke-LiveCompose $tag @("run", "--rm", "--no-deps", "api", "alembic", "upgrade", "head")
    Invoke-LiveCompose $tag @("up", "-d", "--remove-orphans")

    # ---- 6. health ----------------------------------------------------------------------
    $stage = "health"
    Write-Step "health check"
    Wait-ContainerHealthy (Get-ServiceContainer $Live.Project "api") 150
    Wait-HttpOk "http://127.0.0.1:$($Live.WebPort)/api/health/ready" 60
    if ($SimulateFailure -eq "health") { throw "simulated health failure (-SimulateFailure health)" }
    Test-LiveSmoke

    $state.previous = $oldTag
    $state.current = $tag
    $result.result = "ok"
    $result.backup = $backupFile
    $result.revision_before = $oldRevision
    $result.revision_after = Get-LiveRevision
    Add-History $state $result
    Save-LiveState $state
    Write-Host "`nDEPLOYED $tag ($short $subject)" -ForegroundColor Green
    Write-Host "rollback: .\scripts\rollback-live.ps1   log: $logFile"

    # keep the current, previous and one more release; delete older folders and images
    $keep = @($state.history | Where-Object { $_.result -eq "ok" } | ForEach-Object { $_.tag } | Select-Object -Unique -First 3)
    Get-ChildItem (Join-Path $StateDir "releases") -Directory | Where-Object { $_.Name -notin $keep } | ForEach-Object {
        foreach ($kind in "api", "web", "test") { docker rmi "$($Live.Image)-${kind}:$($_.Name)" *> $null }
        Remove-Item -Recurse -Force $_.FullName
    }
    Get-ChildItem (Join-Path $Live.BackupDir "predeploy") -Filter "yaver-predeploy-*.sql.gz" | Sort-Object Name -Descending |
        Select-Object -Skip 5 | Remove-Item
    exit 0
}
catch {
    $reason = "$($_.Exception.Message)"
    Write-Host "`nDEPLOY FAILED at stage '$stage': $reason" -ForegroundColor Red
    $result.result = "failed"
    $result.stage = $stage
    $result.reason = $reason
    $result.backup = $backupFile
    if (-not $switched) {
        Write-Host "The live stack was not touched; it still runs $(if ($oldTag) { $oldTag } else { 'what it ran before' })." -ForegroundColor Yellow
    } else {
        Write-Step "rolling back"
        try {
            $newRevision = Get-LiveRevision
            Invoke-LiveCompose $tag @("stop", "api", "web")
            if ($backupFile -and $newRevision -ne $oldRevision) {
                Write-Warn "schema changed ($oldRevision -> $newRevision): restoring $backupFile"
                Restore-LiveDb $backupFile
            }
            if ($oldTag) {
                Invoke-LiveCompose $oldTag @("up", "-d", "--remove-orphans")
                Wait-ContainerHealthy (Get-ServiceContainer $Live.Project "api") 150
                Test-LiveSmoke
                Write-Host "Back on $oldTag." -ForegroundColor Yellow
                $result.rolled_back_to = $oldTag
            } else {
                Write-Host "No earlier release to go back to (first deploy): api and web stay stopped. Start the old stack again: docker start yaver-db-1 yaver-api-1 yaver-web-1 (see the guide)." -ForegroundColor Yellow
                Invoke-LiveCompose $tag @("stop")
            }
        } catch {
            Write-Host "ROLLBACK FAILED: $($_.Exception.Message) - run .\scripts\rollback-live.ps1 and see $logFile" -ForegroundColor Red
            $result.rollback_error = "$($_.Exception.Message)"
        }
    }
    if ($candidateCompose -and -not $KeepCandidate) { docker @candidateCompose down -v *> $null }
    if ($tag -ne $state.current) {
        # the failed release is not kept: its images and folder go, the log stays
        foreach ($kind in "api", "web", "test") { docker rmi "$($Live.Image)-${kind}:$tag" *> $null }
        if (-not $KeepCandidate) { Remove-Item -Recurse -Force $releaseDir -ErrorAction SilentlyContinue }
    }
    Add-History $state $result
    Save-LiveState $state
    Write-Host "log: $logFile"
    exit 1
}
finally {
    Stop-Transcript | Out-Null
    Remove-Item -Force $lock -ErrorAction SilentlyContinue
}
