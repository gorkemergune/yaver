# Windows wrapper of e2e/stack.sh (same commands): .\e2e\stack.ps1 up | down | reset | logs
#
# Default: project yaver-e2e, web 8090, api 8001, db 5433. A second copy side by side:
#   $env:E2E_PROJECT = "yaver-e2e-mine"; $env:E2E_WEB_PORT = 8091; $env:E2E_API_PORT = 8002
#   $env:E2E_DB_PORT = 5434; .\e2e\stack.ps1 up
# The project name must start with "yaver-e2e" (the tests refuse to touch other containers);
# images are tagged <project>-api / <project>-web so two copies never share an image.
param([string]$Command = "up")
$Root = Split-Path -Parent $PSScriptRoot
$Project = if ($env:E2E_PROJECT) { $env:E2E_PROJECT } else { "yaver-e2e" }
if (-not $Project.StartsWith("yaver-e2e")) { Write-Error "E2E_PROJECT must start with yaver-e2e"; exit 2 }
$ApiPort = if ($env:E2E_API_PORT) { $env:E2E_API_PORT } else { "8001" }
$WebPort = if ($env:E2E_WEB_PORT) { $env:E2E_WEB_PORT } else { "8090" }
if (-not $env:E2E_API_IMAGE) { $env:E2E_API_IMAGE = "$Project-api" }
if (-not $env:E2E_WEB_IMAGE) { $env:E2E_WEB_IMAGE = "$Project-web" }
$EnvArgs = @()
if (Test-Path "$Root/.env") { $EnvArgs = @("--env-file", "$Root/.env") }
function Invoke-E2eCompose { docker compose -p $Project -f "$Root/e2e/docker-compose.e2e.yml" @EnvArgs @args }
switch ($Command) {
  "up" {
    Invoke-E2eCompose up -d --build; if ($LASTEXITCODE) { exit $LASTEXITCODE }
    Invoke-E2eCompose exec -T api alembic upgrade head; if ($LASTEXITCODE) { exit $LASTEXITCODE }
    Invoke-E2eCompose restart api
    foreach ($i in 1..60) {
      try {
        Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:$ApiPort/api/health/ready" -TimeoutSec 3 | Out-Null
        Write-Output "e2e stack $Project ready: web http://127.0.0.1:$WebPort  api http://127.0.0.1:$ApiPort"; exit 0
      } catch { Start-Sleep -Seconds 2 }
    }
    Invoke-E2eCompose logs --tail 80 api; exit 1
  }
  "down" { Invoke-E2eCompose down }
  "reset" { Invoke-E2eCompose down -v }
  "logs" { Invoke-E2eCompose logs --tail 200 api }
  default { Write-Error "usage: stack.ps1 up|down|reset|logs"; exit 2 }
}
