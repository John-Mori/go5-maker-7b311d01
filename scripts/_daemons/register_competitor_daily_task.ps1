# register_competitor_daily_task.ps1 - register the 08:00 JST daily competitor-ranking analysis.
# Fires competitor_daily.ps1 at 08:00 local time (box TZ = Tokyo Standard Time = JST),
# which runs competitor_daily_push.py: analyse -> push the 5-line summary to the analysis room
# (shorts-analyst / Almond Eye). Requested by the analysis dept (Chami: "analyse the competitor
# growth ranking every morning at 8", msg 1537485259237490688 -> delegated unattended to platform-se).
#   - Daily trigger at 08:00.
#   - StartWhenAvailable => a missed 8am (box asleep/off) runs ASAP after wake instead of skipping.
#   - ExecutionTimeLimit 15 min: the GAS fetch retries up to 4x and can take a few minutes.
# No admin required (registered as the current user). ASCII-only (PS 5.1 codepage safety).
$ErrorActionPreference = 'Stop'
$TaskName = 'go5_competitor_daily_0800'
if ($PSScriptRoot) { $here = $PSScriptRoot } else { $here = Split-Path -Parent $MyInvocation.MyCommand.Definition }
$root = Split-Path -Parent (Split-Path -Parent $here)
$ps1  = Join-Path $root 'scripts\report\competitor_daily.ps1'
if (-not (Test-Path $ps1)) { Write-Error ("competitor_daily.ps1 not found: " + $ps1); exit 1 }

$action  = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument ('-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $ps1 + '"')
$trigger = New-ScheduledTaskTrigger -Daily -At '08:00'
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 15)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Description 'go5-maker: 08:00 JST - analyse competitor growth ranking and push the summary to the analysis room (Almond Eye).' -Force | Out-Null

Write-Host ("OK: registered '" + $TaskName + "' (daily 08:00 JST, competitor ranking -> analysis room).") -ForegroundColor Green
