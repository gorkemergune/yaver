# Windows wrapper of e2e/stack.sh (same commands): .\e2e\stack.ps1 up | down | reset | logs
param([string]$Command = "up")
$Root = Split-Path -Parent $PSScriptRoot
$EnvArgs = @()
if (Test-Path "$Root/.env") { $EnvArgs = @("--env-file", "$Root/.env") }
function Invoke-E2eCompose { docker compose -p yaver-e2e -f "$Root/e2e/docker-compose.e2e.yml" @EnvArgs @args }
switch ($Command) {
  "up" {
    Invoke-E2eCompose up -d --build; if ($LASTEXITCODE) { exit $LASTEXITCODE }
    Invoke-E2eCompose exec -T api alembic upgrade head; if ($LASTEXITCODE) { exit $LASTEXITCODE }
    Invoke-E2eCompose restart api
    foreach ($i in 1..60) {
      try {
        Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8001/api/health/ready -TimeoutSec 3 | Out-Null
        Write-Output "e2e stack ready: web http://127.0.0.1:8090  api http://127.0.0.1:8001"; exit 0
      } catch { Start-Sleep -Seconds 2 }
    }
    Invoke-E2eCompose logs --tail 80 api; exit 1
  }
  "down" { Invoke-E2eCompose down }
  "reset" { Invoke-E2eCompose down -v }
  "logs" { Invoke-E2eCompose logs --tail 200 api }
  default { Write-Error "usage: stack.ps1 up|down|reset|logs"; exit 2 }
}
