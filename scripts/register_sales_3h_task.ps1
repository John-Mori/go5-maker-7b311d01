param([string]$RepoRoot = "")
$ErrorActionPreference = 'Stop'
$TaskName = 'go5_sales_3h'

# Repo root: prefer the argument; otherwise use this script's folder (scripts) parent.
if (-not $RepoRoot -or $RepoRoot -eq '.') {
  if ($PSScriptRoot) { $scriptDir = $PSScriptRoot } else { $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition }
  $RepoRoot = Split-Path -Parent $scriptDir
}
$RepoRoot = (Resolve-Path $RepoRoot).Path
$bat = Join-Path $RepoRoot 'scripts\sales_fetch_3h.bat'
if (-not (Test-Path $bat)) { Write-Error ("sales_fetch_3h.bat not found: " + $bat); exit 1 }
$vbs = Join-Path $RepoRoot 'scripts\sales_fetch_3h_hidden.vbs'
if (-not (Test-Path $vbs)) { Write-Error ("sales_fetch_3h_hidden.vbs not found: " + $vbs); exit 1 }

# Register "every 3h from 00:00" (0/3/6/9/12/15/18/21) via schtasks.exe.
# PowerShell 5.1 cannot assign .Repetition on a -Daily trigger, so schtasks is used.
# wscript.exe runs the VBS with NO console window (hidden background run).
$tr = 'wscript.exe "' + $vbs + '"'
& schtasks.exe /Create /TN $TaskName /TR $tr /SC HOURLY /MO 3 /ST 00:00 /F | Out-Null
if ($LASTEXITCODE -ne 0) { Write-Error "schtasks registration failed."; exit 1 }

Write-Host ""
Write-Host ("OK: registered scheduled task '" + $TaskName + "' (every 3h from 00:00, hidden).") -ForegroundColor Green
Write-Host ("  runs: " + $bat + "  (fetch_sales.mjs --force)")
Write-Host "  log : %TEMP%\go5-sales-3h.log"
Write-Host "  stop: run the sales-3h stop .bat, or: schtasks /Delete /TN go5_sales_3h /F"
