param([string]$RepoRoot = "")
$ErrorActionPreference = 'Stop'
# 5secMovieMaker: register a daily hidden task that drains comp_frame_pending with gemini-2.5-pro
# (free-tier only; stops when the daily pro quota runs out, carries the rest to the next day).
# ASCII-only on purpose (PS5.1 reads BOM-less ps1 as cp932).
$TaskName = 'go5_comp_frames_daily'

if (-not $RepoRoot -or $RepoRoot -eq '.') {
  if ($PSScriptRoot) { $scriptDir = $PSScriptRoot } else { $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition }
  $RepoRoot = Split-Path -Parent $scriptDir
}
$RepoRoot = (Resolve-Path $RepoRoot).Path
$vbs = Join-Path $RepoRoot 'scripts\comp_frames_hidden.vbs'
if (-not (Test-Path $vbs)) { Write-Error ("comp_frames_hidden.vbs not found: " + $vbs); exit 1 }

# Daily at 06:40 (just after product-scout 06:10; morning quota is fresh after the PT midnight reset).
$tr = 'wscript.exe "' + $vbs + '"'
& schtasks.exe /Create /TN $TaskName /TR $tr /SC DAILY /ST 06:40 /F | Out-Null
if ($LASTEXITCODE -ne 0) { Write-Error "schtasks registration failed."; exit 1 }

Write-Host ("OK: registered scheduled task '" + $TaskName + "' (daily at 06:40, hidden).") -ForegroundColor Green
Write-Host ("  runs: " + (Join-Path $RepoRoot 'scripts\comp_frames.bat') + "  (comp_frames.py --limit 50)")
Write-Host "  log : %TEMP%\go5-comp-frames.log"
Write-Host ("  stop: schtasks /Delete /TN " + $TaskName + " /F")
