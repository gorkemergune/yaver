# Bug reports (👎 "Hatalı" in the chat) from the LIVE database to one markdown file, READ ONLY.
# PowerShell 7, from the repo folder:
#
#   .\scripts\export-bugs.ps1                   open reports -> docs\bugs\bugs-<time>.md
#   .\scripts\export-bugs.ps1 -All              closed ones too
#   .\scripts\export-bugs.ps1 -Since 2026-11-20 only reports from that day on
#   .\scripts\export-bugs.ps1 -Project yaver-dev   another stack (trying the script)
#
# The query runs in a read-only transaction (default_transaction_read_only): it cannot change
# anything. docs\bugs\ is gitignored - reports hold chat messages; hand the file over yourself.
param(
    [switch]$All,
    [string]$Since,
    [string]$Project,
    [string]$Out = "docs\bugs"
)
. (Join-Path $PSScriptRoot "live-common.ps1")
if ($Project) { $Live.Project = $Project }
$OutputEncoding = [Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)

$db = Get-ServiceContainer $Live.Project "db"
if (-not $db) { throw "the db of $($Live.Project) is not running" }

$where = @()
if (-not $All) { $where += "status = 'open'" }
if ($Since) {
    if ($Since -notmatch '^\d{4}-\d{2}-\d{2}$') { throw "-Since takes YYYY-MM-DD" }
    $where += "created_at >= '$Since'::date"
}
$filter = if ($where) { "WHERE " + ($where -join " AND ") } else { "" }
$sql = "SELECT coalesce(json_agg(row_to_json(b) ORDER BY b.id), '[]'::json) FROM (SELECT id, created_at, status, source, agent_id, message_id, conversation_id, user_text, reply_text, note, tools, intents, errors, log_summary FROM bug_reports $filter) b"

Write-Step "Bug reports of $($Live.Project) (read only)"
$json = docker exec -e "PGOPTIONS=-c default_transaction_read_only=on" $db psql -X -q -tA -U $Live.DbUser -d $Live.DbName -c $sql
if ($LASTEXITCODE -ne 0) { throw "psql failed (is the bug_reports table there? it comes with the release that added it)" }
$reports = @(($json | Out-String).Trim() | ConvertFrom-Json)

function Format-Report($r) {
    $lines = @()
    $when = ([datetime]$r.created_at).ToLocalTime().ToString("yyyy-MM-dd HH:mm")
    $lines += "## #$($r.id) - $when - $($r.agent_id ?? '?') ($($r.source), $($r.status))"
    $lines += ""
    if ($r.note) { $lines += "**Not:** $($r.note)"; $lines += "" }
    $lines += "**Mesaj:**"
    $lines += ""
    $lines += (($r.user_text ?? "") -split "`n" | ForEach-Object { "> $_" })
    $lines += ""
    $lines += "**Cevap:**"
    $lines += ""
    $lines += (($r.reply_text ?? "") -split "`n" | ForEach-Object { "> $_" })
    $lines += ""
    if (@($r.intents).Count) {
        $lines += "**Yönlendirme:** " + ((@($r.intents) | ForEach-Object { "$($_[0]) -> $($_[1] ?? 'yaver')" }) -join ", ")
    }
    if (@($r.tools).Count) {
        $lines += "**Araçlar:**"
        foreach ($t in @($r.tools)) {
            $extra = @()
            if ($t.area) { $extra += "alan: $($t.area)" }
            if ($t.reason) { $extra += "neden: $($t.reason)" }
            if ($t.error) { $extra += "HATA: $($t.error)" }
            $suffix = if ($extra) { " (" + ($extra -join "; ") + ")" } else { "" }
            $lines += "- $($t.agent_id): ``$($t.tool)``$suffix"
        }
    }
    if (@($r.errors).Count) { $lines += "**Hatalar:** " + (@($r.errors) -join " | ") }
    if ($r.log_summary) {
        $lines += ""
        $lines += "<details><summary>Log ($((($r.log_summary -split "`n").Count)) satır)</summary>"
        $lines += ""
        $lines += '```'
        $lines += $r.log_summary
        $lines += '```'
        $lines += "</details>"
    }
    $lines += ""
    $lines += "message_id $($r.message_id), conversation $($r.conversation_id)"
    $lines += ""
    return $lines
}

$dir = if ([IO.Path]::IsPathRooted($Out)) { $Out } else { Join-Path $Root $Out }
New-Item -ItemType Directory -Force $dir | Out-Null
$file = Join-Path $dir ("bugs-{0:yyyyMMdd-HHmm}.md" -f (Get-Date))
$body = @("# Yaver hata raporları ($($Live.Project), $(Get-Date -Format 'yyyy-MM-dd HH:mm'))", "")
$body += "$($reports.Count) rapor" + $(if ($All) { " (açık + kapalı)" } else { " (açık)" }) + $(if ($Since) { ", $Since'ten beri" } else { "" })
$body += ""
foreach ($r in $reports) { $body += Format-Report $r }
Set-Content -Path $file -Value ($body -join "`n") -Encoding utf8
Write-Ok ("{0} reports -> {1}" -f $reports.Count, $file)
