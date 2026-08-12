# register_kaizen_daily_repair.ps1 - register the 08:10 JST daily "alpha repair / recurrence" analysis.
# Chami asked (ad-room 2026-08-12): every morning at 8, aggregate the last 24h of repairs and
# recurrences so the generation mechanism gets more accurate over time. Narrowed to the alpha
# repair dept (system-engineer = the 5sec movie maker itself) by Chami's follow-up.
#   - Runs scripts\_daemons\run_kaizen_daily_repair.py, which runs the analysis AND delivers
#     the result to the improvement dept's queue (C-036: the launcher itself reports; do not
#     rely on an interactive session noticing).
#   - 08:10, NOT 08:00: three tasks already fire at 08:00 (go5_daily_report_0800,
#     go5_reaction_watch_0800, go5_se_daily_review_0800). Ten minutes of clearance.
#   - StartWhenAvailable => if the box was asleep at 08:10, it runs ASAP after wake instead of
#     silently skipping the day (a morning report that quietly does not happen is the worst case).
# No admin required (registered as the current user). ASCII-only (PS 5.1 codepage safety).
$ErrorActionPreference = 'Stop'
$TaskName = 'go5_kaizen_daily_0810'
if ($PSScriptRoot) { $here = $PSScriptRoot } else { $here = Split-Path -Parent $MyInvocation.MyCommand.Definition }
$root = Split-Path -Parent (Split-Path -Parent $here)
$py = Join-Path $root 'scripts\_daemons\run_kaizen_daily_repair.py'
if (-not (Test-Path $py)) { Write-Error ("run_kaizen_daily_repair.py not found: " + $py); exit 1 }

# Resolve python.exe to an ABSOLUTE path. Task Scheduler does not inherit the interactive
# PATH: -Execute 'python' registers fine and then fails at run time with 0x80070002
# ("cannot find the file specified") - i.e. it looks healthy in the task list while never
# producing a report. Measured 2026-08-13 by actually firing it once. Resolve it here instead.
$python = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $python) { Write-Error "python.exe not found on PATH; cannot register a task that would silently fail."; exit 1 }

$action = New-ScheduledTaskAction -Execute $python -Argument ('"' + $py + '"') -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Daily -At '08:10'
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Description 'go5-maker: 08:10 JST - aggregate last 24h of alpha-repair changes/recurrences and deliver to the improvement dept (Chami 2026-08-12)' -Force | Out-Null

Write-Host ("OK: registered '" + $TaskName + "' (daily 08:10 JST).") -ForegroundColor Green
