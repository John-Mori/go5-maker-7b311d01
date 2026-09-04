param([string]$RepoRoot = "")
$ErrorActionPreference = 'Stop'
# 5secMovieMaker: register a daily hidden task that collects competitor daily stats via yt-dlp (no API key)
# and writes them back to the sheet through GAS SpreadsheetApp ops, bypassing the GAS urlfetch quota that
# froze runCompetitorDaily for 17 days (2026-08-18..). Direction 2 / Modric handoff REQ-research-room-de08ad55fc.
# ASCII-only on purpose (PS5.1 reads BOM-less ps1 as cp932).
$TaskName = 'go5_comp_daily'

if (-not $RepoRoot -or $RepoRoot -eq '.') {
  if ($PSScriptRoot) { $scriptDir = $PSScriptRoot } else { $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition }
  $RepoRoot = Split-Path -Parent $scriptDir
}
$RepoRoot = (Resolve-Path $RepoRoot).Path
$vbs = Join-Path $RepoRoot 'scripts\comp_daily_hidden.vbs'
if (-not (Test-Path $vbs)) { Write-Error ("comp_daily_hidden.vbs not found: " + $vbs); exit 1 }

# Daily at 05:30: after the 04:00 GAS attempt (so the pc_writeback status row is the LAST today-row = green),
# and well before the 08:00 morning brief / freeze watcher (so recovery is visible the same morning).
$tr = 'wscript.exe "' + $vbs + '"'
& schtasks.exe /Create /TN $TaskName /TR $tr /SC DAILY /ST 05:30 /F | Out-Null
if ($LASTEXITCODE -ne 0) { Write-Error "schtasks registration failed."; exit 1 }

Write-Host ("OK: registered scheduled task '" + $TaskName + "' (daily at 05:30, hidden).") -ForegroundColor Green
Write-Host ("  runs: " + (Join-Path $RepoRoot 'scripts\comp_daily.bat') + "  (comp_daily.py --max 800)")
Write-Host "  log : %TEMP%\go5-comp-daily.log"
Write-Host ("  stop: schtasks /Delete /TN " + $TaskName + " /F")
