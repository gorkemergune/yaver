# End-to-end smoke test of a running Yaver stack (PowerShell 7).
#
#   .\scripts\smoke.ps1              stack up? health, API, then a real chat message + undo
#   .\scripts\smoke.ps1 -NoChat      everything except the chat (no LLM call, nothing written)
#
# The chat step goes through the real model (fractions of a cent) and writes a smoke
# conversation into your database; the change it makes (a task) is undone right after.
param(
    [string]$BaseUrl = "http://localhost:8080",
    [switch]$NoChat
)
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
$failed = 0

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
    Invoke-RestMethod -Uri "$BaseUrl$Path" -TimeoutSec 20
}

Write-Host "Yaver smoke test -> $BaseUrl"

Step "containers running and healthy" {
    $rows = docker compose ps --format json | ForEach-Object { $_ | ConvertFrom-Json }
    foreach ($service in "db", "api", "web") {
        $row = $rows | Where-Object { $_.Service -eq $service }
        if (-not $row) { throw "$service is not running (docker compose up -d)" }
        if ($row.State -ne "running") { throw "$service is $($row.State)" }
        if ($row.Health -and $row.Health -ne "healthy") { throw "$service is $($row.Health)" }
    }
    "db, api, web"
}
# /api/... in dev too: on port 8080 the Vite dev server answers any other path with index.html
Step "GET /api/health" {
    $health = Get-Json "/api/health"
    if ($health -is [string]) { throw "not JSON - is $BaseUrl the Yaver web port?" }
    $health | ConvertTo-Json -Compress
}
Step "GET /api/health/ready (database)" { (Get-Json "/api/health/ready").status }
Step "GET /api/team" {
    $team = Get-Json "/api/team"
    "$($team.coordinator.name) + $(($team.agents | ForEach-Object name) -join ', ')"
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
            -ContentType "application/json; charset=utf-8" -TimeoutSec 120
        if (-not $reply.change_set_id) { throw "no change was made: $($reply.reply)" }
        $script:changeSet = $reply.change_set_id
        "$($reply.speaker): $($reply.reply.Substring(0, [Math]::Min(60, $reply.reply.Length)))..."
    }
    Step "POST /api/changes/{id}/undo" {
        if (-not $script:changeSet) { throw "nothing to undo (chat step failed)" }
        $undo = Invoke-RestMethod -Uri "$BaseUrl/api/changes/$($script:changeSet)/undo" -Method Post -TimeoutSec 20
        "$($undo.reverted) change(s) reverted"
    }
}

if ($failed -gt 0) {
    Write-Host "$failed check(s) failed" -ForegroundColor Red
    exit 1
}
Write-Host "all checks passed" -ForegroundColor Green
