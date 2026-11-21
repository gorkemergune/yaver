# End-to-end smoke test of a running Yaver stack (PowerShell 7).
#
#   .\scripts\smoke.ps1                      live stack (yaver-live, :8080) if it runs, else dev (yaver-dev, :8180)
#   .\scripts\smoke.ps1 -Stack dev           the development stack
#   .\scripts\smoke.ps1 -NoChat              everything except the chat (no LLM call, nothing written)
#   .\scripts\smoke.ps1 -BaseUrl http://127.0.0.1:8092 -Project yaver-e2e-release -Password ...   any copy
#
# Logs in with APP_PASSWORD (from the environment or .env) when the stack has a login.
# The chat step goes through the real model (fractions of a cent) and writes a smoke
# conversation into that stack's database; the change it makes (a task) is undone right after.
param(
    [ValidateSet("auto", "live", "dev")][string]$Stack = "auto",
    [string]$BaseUrl,
    [string]$Project,
    [string]$Password,
    [switch]$NoChat
)
$ErrorActionPreference = "Stop"
$Root = Join-Path $PSScriptRoot ".."
$failed = 0

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

function Test-ProjectRunning([string]$Name) {
    [bool](docker ps -q --filter "label=com.docker.compose.project=$Name" 2>$null)
}

$liveProject = Get-EnvValue "YAVER_LIVE_PROJECT" "yaver-live"
if ($Stack -eq "auto" -and -not $Project) {
    $Stack = if (Test-ProjectRunning $liveProject) { "live" } else { "dev" }
}
if (-not $Project) { $Project = if ($Stack -eq "live") { $liveProject } else { "yaver-dev" } }
if (-not $BaseUrl) {
    $port = if ($Stack -eq "live") { Get-EnvValue "LIVE_WEB_PORT" "8080" } else { Get-EnvValue "DEV_WEB_PORT" "8180" }
    $BaseUrl = "http://127.0.0.1:$port"
}
if (-not $PSBoundParameters.ContainsKey("Password")) { $Password = Get-EnvValue "APP_PASSWORD" "" }
$session = New-Object Microsoft.PowerShell.Commands.WebRequestSession

function Step([string]$Name, [scriptblock]$Check) {
    $started = Get-Date
    try {
        $detail = & $Check
        $ms = [int]((Get-Date) - $started).TotalMilliseconds
        Write-Host ("  OK   {0,-34} {1,6} ms  {2}" -f $Name, $ms, $detail) -ForegroundColor Green
    } catch {
        $script:failed++
        Write-Host ("  FAIL {0,-34} {1}" -f $Name, $_.Exception.Message) -ForegroundColor Red
    }
}

function Get-Json([string]$Path) {
    Invoke-RestMethod -Uri "$BaseUrl$Path" -TimeoutSec 20 -WebSession $session
}

Write-Host "Yaver smoke test -> $BaseUrl (project $Project)"

Step "containers running and healthy" {
    $names = @()
    foreach ($service in "db", "api", "web") {
        $id = docker ps -q --filter "label=com.docker.compose.project=$Project" --filter "label=com.docker.compose.service=$service"
        if (-not $id) { throw "$service of $Project is not running" }
        $state = docker inspect --format "{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{end}}" $id
        $status, $health = "$state".Trim() -split " "
        if ($status -ne "running") { throw "$service is $status" }
        if ($health -and $health -ne "healthy") { throw "$service is $health" }
        $names += $service
    }
    $names -join ", "
}
# /api/... in dev too: the Vite dev server answers any other path with index.html
Step "GET /api/health" {
    $health = Get-Json "/api/health"
    if ($health -is [string]) { throw "not JSON - is $BaseUrl the Yaver web port?" }
    $health | ConvertTo-Json -Compress
}
Step "GET /api/health/ready (database)" { (Get-Json "/api/health/ready").status }
Step "login" {
    $status = Get-Json "/api/auth/status"
    if (-not $status.enabled) { return "no login (APP_PASSWORD empty)" }
    if (-not $Password) { throw "the stack has a login but no APP_PASSWORD was given" }
    $body = @{ password = $Password } | ConvertTo-Json
    $null = Invoke-RestMethod -Uri "$BaseUrl/api/auth/login" -Method Post -WebSession $session -TimeoutSec 20 `
        -Body ([Text.Encoding]::UTF8.GetBytes($body)) -ContentType "application/json; charset=utf-8"
    if (-not (Get-Json "/api/auth/status").authenticated) { throw "login did not stick" }
    "session cookie"
}
Step "GET /api/team" {
    $team = Get-Json "/api/team"
    "$($team.coordinator.name) + $(($team.agents | ForEach-Object name) -join ', ')"
}
Step "GET /api/office/snapshot" {
    $office = Get-Json "/api/office/snapshot"
    if (-not $office.ready) { throw "office not ready" }
    "$($office.employees.Count) employees"
}
Step "GET /api/plan/day" { "$((Get-Json '/api/plan/day').items.Count) items today" }
Step "GET /api/usage/month" {
    $usage = Get-Json "/api/usage/month"
    "Claude `$$($usage.budget.spent_usd) / `$$($usage.budget.limit_usd)"
}

if (-not $NoChat) {
    $script:changeSet = $null
    Step "POST /api/chat (real model)" {
        $body = @{ message = "Smoke test: 31 Aralık'a 'Yaver smoke test' görevi ekle" } | ConvertTo-Json
        $reply = Invoke-RestMethod -Uri "$BaseUrl/api/chat" -Method Post -Body ([Text.Encoding]::UTF8.GetBytes($body)) `
            -ContentType "application/json; charset=utf-8" -TimeoutSec 120 -WebSession $session
        if (-not $reply.change_set_id) { throw "no change was made: $($reply.reply)" }
        $script:changeSet = $reply.change_set_id
        "$($reply.speaker): $($reply.reply.Substring(0, [Math]::Min(60, $reply.reply.Length)))..."
    }
    Step "POST /api/changes/{id}/undo" {
        if (-not $script:changeSet) { throw "nothing to undo (chat step failed)" }
        $undo = Invoke-RestMethod -Uri "$BaseUrl/api/changes/$($script:changeSet)/undo" -Method Post -TimeoutSec 20 -WebSession $session
        "$($undo.reverted) change(s) reverted"
    }
}

if ($failed -gt 0) {
    Write-Host "$failed check(s) failed" -ForegroundColor Red
    exit 1
}
Write-Host "all checks passed" -ForegroundColor Green
