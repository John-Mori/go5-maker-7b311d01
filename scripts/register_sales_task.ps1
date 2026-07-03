param([string]$RepoRoot = "")
$ErrorActionPreference = 'Stop'
$TaskName = 'go5_sales_auto'

# Repo root: prefer the argument; otherwise use this script's folder (scripts) parent.
if (-not $RepoRoot) {
  if ($PSScriptRoot) { $scriptDir = $PSScriptRoot } else { $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition }
  $RepoRoot = Split-Path -Parent $scriptDir
}
$poll = Join-Path $RepoRoot 'scripts\sales_poll.bat'
if (-not (Test-Path $poll)) { Write-Error ("sales_poll.bat not found: " + $poll); exit 1 }

$action  = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument ('/c "' + $poll + '"')
# Repeat every 15 minutes indefinitely, starting now.
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 15) -RepetitionDuration (New-TimeSpan -Days 3650)
# StartWhenAvailable: run ASAP after a missed start (sleep/off). WakeToRun: wake if needed. IgnoreNew: no overlap.
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -WakeToRun -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 2)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Description 'go5-maker: fetch tracked-circle sales every 15min (PC=JP IP). --poll' -Force | Out-Null

Write-Host ""
Write-Host ("OK: registered scheduled task '" + $TaskName + "' (every 15 min).") -ForegroundColor Green
Write-Host ("  runs: " + $poll)
Write-Host "  log : %TEMP%\go5-sales-poll.log"
Write-Host "  stop: run the '販売数-自動取得を停止.bat'."
Write-Host ""
try { Start-ScheduledTask -TaskName $TaskName; Write-Host "Started once now for a quick check." } catch {}