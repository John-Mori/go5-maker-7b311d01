# register_quota_alarm_task.ps1 - register go5_quota_alarm (weekly-quota burn watch).
#
# WHY: kenkyujo-HQ order 2026-08-23 (msg 1540938360464474273) item 4:
#   "put quota_burn on a schedule; do NOT use 'Chami reads the % off the phone' as the trigger."
#   quota_alarm.py measures a quantity we own (weighted weekly total) and compares it with the
#   same interval of the previous week. It only dispatches when over threshold, and it debounces
#   for 24h because each dispatched item itself costs ~0.3% of the weekly quota (measured).
#
# Runs every 3 hours. The scan takes ~5 seconds, so the watch itself is free.
# ASCII-only on purpose.

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$Py   = 'C:\Users\chami\AppData\Local\Programs\Python\Python312\python.exe'
if (-not (Test-Path $Py)) { $Py = 'python' }

$Name   = 'go5_quota_alarm'
$Script = Join-Path $Root 'scripts\llm\quota_alarm.py'
if (-not (Test-Path $Script)) { throw "missing: $Script" }

$action = New-ScheduledTaskAction -Execute $Py -Argument ('"{0}"' -f $Script) -WorkingDirectory $Root
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).Date.AddHours(1) `
           -RepetitionInterval (New-TimeSpan -Hours 3)
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
            -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 20) `
            -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName $Name -Action $action -Trigger $trigger -Settings $settings `
    -Description 'Weekly plan-quota burn watch (aegis-gl). Alarms only when over threshold.' `
    -Force | Out-Null

$t = Get-ScheduledTask -TaskName $Name
$i = Get-ScheduledTaskInfo -TaskName $Name
Write-Host ("registered {0} state={1} next={2}" -f $Name, $t.State, $i.NextRunTime)
