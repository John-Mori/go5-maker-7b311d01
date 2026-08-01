# register_report_pulse_task.ps1 - register the periodic progress-pulse trigger.
# Fires report_pulse.ps1 every 4 hours (00,04,08,12,16,20 JST base), which pushes the
# UNREPORTED change_log entries since the last marker to the report-notify channel.
#   - Every 4h so "what got changed" surfaces to Chami without going to look (Chami 2026-08-01:
#     "no response, no autonomous reporting, improve it"). Silent when nothing new (not a nag).
#   - StartWhenAvailable => a missed fire (box asleep) runs ASAP after wake instead of skipping.
# No admin required (registered as the current user). ASCII-only (PS 5.1 codepage safety).
$ErrorActionPreference = 'Stop'
$TaskName = 'go5_report_pulse_4h'
if ($PSScriptRoot) { $here = $PSScriptRoot } else { $here = Split-Path -Parent $MyInvocation.MyCommand.Definition }
$root = Split-Path -Parent (Split-Path -Parent $here)
$ps1  = Join-Path $root 'scripts\report\report_pulse.ps1'
if (-not (Test-Path $ps1)) { Write-Error ("report_pulse.ps1 not found: " + $ps1); exit 1 }

$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument ('-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $ps1 + '"')
# Attach a 4h repetition to a daily-at-00:00 trigger (the reliable PS 5.1 way to get "every N hours").
$trigger = New-ScheduledTaskTrigger -Daily -At '00:00'
$rep = (New-ScheduledTaskTrigger -Once -At '00:00' -RepetitionInterval (New-TimeSpan -Hours 4) -RepetitionDuration (New-TimeSpan -Hours 24)).Repetition
$trigger.Repetition = $rep
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 5)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Description 'go5-maker: every 4h - push unreported change_log digest to report-notify (visibility, not a nag).' -Force | Out-Null

Write-Host ("OK: registered '" + $TaskName + "' (every 4h, pushes unreported change_log to report-notify).") -ForegroundColor Green
