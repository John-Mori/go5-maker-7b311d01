param([string]$RepoRoot = "")
$ErrorActionPreference = 'Stop'
$TaskName = 'go5_sales_3h'

# Repo root: prefer the argument; otherwise use this script's folder (scripts) parent.
if (-not $RepoRoot) {
  if ($PSScriptRoot) { $scriptDir = $PSScriptRoot } else { $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition }
  $RepoRoot = Split-Path -Parent $scriptDir
}
$bat = Join-Path $RepoRoot 'scripts\sales_fetch_3h.bat'
if (-not (Test-Path $bat)) { Write-Error ("sales_fetch_3h.bat not found: " + $bat); exit 1 }
$vbs = Join-Path $RepoRoot 'scripts\sales_fetch_3h_hidden.vbs'
if (-not (Test-Path $vbs)) { Write-Error ("sales_fetch_3h_hidden.vbs not found: " + $vbs); exit 1 }

# wscript.exe（コンソール無しのスクリプトホスト）経由で VBS を実行 → VBS が bat を非表示ウィンドウで起動。
# これで3時間ごとの実行時に黒いターミナル窓が一切表示されない。
$action  = New-ScheduledTaskAction -Execute 'wscript.exe' -Argument ('"' + $vbs + '"')
# 毎日 00:00 起点で3時間ごと（0/3/6/9/12/15/18/21時）に実行。RepetitionDuration 24h でその日ぶんを回す。
$trigger = New-ScheduledTaskTrigger -Daily -At '00:00'
$trigger.Repetition = (New-ScheduledTaskTrigger -Once -At '00:00' -RepetitionInterval (New-TimeSpan -Hours 3) -RepetitionDuration (New-TimeSpan -Hours 24)).Repetition
# StartWhenAvailable: run ASAP after a missed start (sleep/off). WakeToRun: wake if needed. IgnoreNew: no overlap.
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -WakeToRun -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 2)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Description 'go5-maker: full sales fetch every 3h from 00:00 (PC=JP IP, hidden). --force' -Force | Out-Null

Write-Host ""
Write-Host ("OK: registered scheduled task '" + $TaskName + "' (every 3h from 00:00, hidden).") -ForegroundColor Green
Write-Host ("  runs: " + $bat + "  (fetch_sales.mjs --force)")
Write-Host "  log : %TEMP%\go5-sales-3h.log"
Write-Host "  stop: run the '販売数-3時間ごと自動取得を停止.bat'."
Write-Host ""
try { Start-ScheduledTask -TaskName $TaskName; Write-Host "Started once now for a quick check." } catch {}
