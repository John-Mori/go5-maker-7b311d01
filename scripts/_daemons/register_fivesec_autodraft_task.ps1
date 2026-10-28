# register_fivesec_autodraft_task.ps1 - register the morning unattended draft run (beta-5c).
# Requested by 5S dept (Klopp via Modric, 2026-10-29).
#   - Daily 06:30, repeated every 30 min until 09:00 (5S writes daily_pick_YYYYMMDD.json after the 06:00 wake).
#   - StartWhenAvailable => a missed run starts after wake instead of skipping.
#   - ExecutionTimeLimit 20min. MultipleInstances IgnoreNew (never two Chromes on the same profile).
# No admin required (registered as the current user). ASCII-only (PS 5.1 codepage safety).
$ErrorActionPreference = 'Stop'
$TaskName = 'fivesec_autodraft_0630'
if ($PSScriptRoot) { $here = $PSScriptRoot } else { $here = Split-Path -Parent $MyInvocation.MyCommand.Definition }
$ps1 = Join-Path $here 'fivesec_autodraft.ps1'
if (-not (Test-Path $ps1)) { Write-Error ("fivesec_autodraft.ps1 not found: " + $ps1); exit 1 }

# every scheduled task goes through the gate so it can never pop a console window
$gate = Join-Path $here 'hidden_task.ps1'
if (-not (Test-Path $gate)) { $gate = 'D:\SougouStartFolder\5SecMovieMaker\scripts\_daemons\hidden_task.ps1' }
. $gate
$action  = New-Go5HiddenAction -Execute 'powershell.exe' -Argument ('-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $ps1 + '"') -WorkingDirectory 'D:\SougouStartFolder\5SecMovieMaker'
$trigger = New-ScheduledTaskTrigger -Daily -At '06:30'
$rep = New-ScheduledTaskTrigger -Once -At '06:30' -RepetitionInterval (New-TimeSpan -Minutes 30) -RepetitionDuration (New-TimeSpan -Hours 2 -Minutes 31)
$trigger.Repetition = $rep.Repetition
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 20)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Description '06:30-09:00 JST every 30 min - make drafts from today daily_pick (5S dept, beta-5c).' -Force | Out-Null

Write-Host ("OK: registered '" + $TaskName + "' (daily 06:30, every 30 min until 09:00, 5S autodraft).") -ForegroundColor Green
