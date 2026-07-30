# register_daily_reflection_task.ps1 - register the 00:00 JST daily self-reflection trigger.
# Fires daily_reflection.ps1 at 00:00 local time (box TZ = Tokyo Standard Time = JST, verified),
# which wakes future-room (現在と未来) to produce that day's reflection.
#   - Daily trigger at 00:00
#   - StartWhenAvailable => if the box was asleep/off at 00:00, it runs ASAP after wake
#     (so a missed midnight still produces the day's reflection instead of silently skipping).
# No admin required (registered as the current user). ASCII-only (PS 5.1 codepage safety).
$ErrorActionPreference = 'Stop'
$TaskName = 'go5_daily_reflection_0000'
if ($PSScriptRoot) { $here = $PSScriptRoot } else { $here = Split-Path -Parent $MyInvocation.MyCommand.Definition }
$root = Split-Path -Parent (Split-Path -Parent $here)
$ps1  = Join-Path $root 'scripts\report\daily_reflection.ps1'
if (-not (Test-Path $ps1)) { Write-Error ("daily_reflection.ps1 not found: " + $ps1); exit 1 }

$action  = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument ('-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $ps1 + '"')
$trigger = New-ScheduledTaskTrigger -Daily -At '00:00'
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Description 'go5-maker: 00:00 JST - wake future-room to write the daily self-reflection about Chami' -Force | Out-Null

Write-Host ("OK: registered '" + $TaskName + "' (daily 00:00 JST, wakes future-room).") -ForegroundColor Green
