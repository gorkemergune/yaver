# docker compose for the LIVE stack (project yaver-live) with the current release's compose
# file and images (PowerShell 7, from the repo folder). Examples:
#
#   .\scripts\live.ps1 ps
#   .\scripts\live.ps1 logs -f --tail 100 api
#   .\scripts\live.ps1 restart api          (after editing .env or config\*.yaml)
#   .\scripts\live.ps1 stop                 /  .\scripts\live.ps1 up -d
#   .\scripts\live.ps1 exec api python -m app.llm.check_models
#   .\scripts\live.ps1 status               current / previous release and the last deploys
#
# `down -v` is refused: the database volume is external and would survive anyway, but the
# habit is dangerous. New code goes live only through .\scripts\deploy-live.ps1.
. (Join-Path $PSScriptRoot "live-common.ps1")

$state = Get-LiveState
if ($args.Count -eq 0 -or $args[0] -eq "status") {
    Write-Host "project:  $($Live.Project)   web: http://localhost:$($Live.WebPort)   db volume: $($Live.DbVolume)"
    Write-Host "current:  $($state.current)"
    Write-Host "previous: $($state.previous)"
    $state.history | Select-Object -First 5 | ForEach-Object {
        Write-Host ("  {0}  {1,-8} {2,-8} {3}  {4}" -f $_.at, $_.kind, $_.result, $_.tag, $(if ($_.reason) { $_.reason } else { $_.subject }))
    }
    exit 0
}
if (-not $state.current) { throw "no live release yet: run .\scripts\deploy-live.ps1 first" }
if ($args -contains "-v" -or $args -contains "--volumes") { throw "refusing 'down -v' on the live stack" }
if ($args[0] -eq "up" -or $args[0] -eq "run" -or $args[0] -eq "create") { Assert-DbVolumeFree }
Invoke-LiveCompose $state.current ([string[]]$args)
