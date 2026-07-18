param([string]$RepoRoot = "")
$ErrorActionPreference = 'Stop'
$TaskName = 'go5_product_scout_morning'

# Repo root: prefer the argument; otherwise use this script's folder (scripts\product_scout),
# two levels up to reach the repo root.
if (-not $RepoRoot -or $RepoRoot -eq '.') {
  if ($PSScriptRoot) { $scriptDir = $PSScriptRoot } else { $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition }
  $RepoRoot = Split-Path -Parent (Split-Path -Parent $scriptDir)
}
$RepoRoot = (Resolve-Path $RepoRoot).Path
$bat = Join-Path $RepoRoot 'scripts\product_scout\morning_scan.bat'
if (-not (Test-Path $bat)) { Write-Error ("morning_scan.bat not found: " + $bat); exit 1 }
$vbs = Join-Path $RepoRoot 'scripts\product_scout\morning_scan_hidden.vbs'
if (-not (Test-Path $vbs)) { Write-Error ("morning_scan_hidden.vbs not found: " + $vbs); exit 1 }

# Register "daily at 06:10" via schtasks.exe.
# wscript.exe runs the VBS with NO console window (hidden background run).
$tr = 'wscript.exe "' + $vbs + '"'
& schtasks.exe /Create /TN $TaskName /TR $tr /SC DAILY /ST 06:10 /F | Out-Null
if ($LASTEXITCODE -ne 0) { Write-Error "schtasks registration failed."; exit 1 }

Write-Host ""
Write-Host ("OK: registered scheduled task '" + $TaskName + "' (daily at 06:10, hidden).") -ForegroundColor Green
Write-Host ("  runs: " + $bat + "  (morning_scan.py, no --dry-run)")
Write-Host "  log : %TEMP%\go5-product-scout-morning.log"
Write-Host ("  stop: schtasks /Delete /TN " + $TaskName + " /F")
