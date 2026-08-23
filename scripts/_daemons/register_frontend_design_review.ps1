# register_frontend_design_review.ps1 - register the 08:00 JST "morning design review" wake-up.
# Chami asked (frontend room, 2026-08-24): "review the day's changes for design every morning at 8".
# The frontend room already owns the procedure (design-preferences.md section 100); the only
# missing piece was the firing. Ordered by AD-room (Modric), wired by Aegis lab.
#   - Runs scripts\_daemons\run_frontend_design_review.py, which sends ONE letter to the
#     frontend room's queue (C-036: the launcher itself delivers; do not rely on a session
#     noticing). The procedure text stays in the frontend doc - the letter only points at it.
#   - 08:00 JST exactly (Chami said 8 o'clock). The runner is tiny (one dispatch), so it does
#     not fight the other 08:00 tasks for API time.
#   - Same window twice = one letter only (the runner keeps state), so a manual rehearsal and
#     the timed run cannot wake the room twice.
#   - StartWhenAvailable => if the box was asleep at 08:00, it runs ASAP after wake instead of
#     silently skipping the day.
# No admin required (registered as the current user). ASCII-only (PS 5.1 codepage safety).
$ErrorActionPreference = 'Stop'
$TaskName = 'go5_frontend_design_0800'
if ($PSScriptRoot) { $here = $PSScriptRoot } else { $here = Split-Path -Parent $MyInvocation.MyCommand.Definition }
$root = Split-Path -Parent (Split-Path -Parent $here)
$py = Join-Path $root 'scripts\_daemons\run_frontend_design_review.py'
if (-not (Test-Path $py)) { Write-Error ("run_frontend_design_review.py not found: " + $py); exit 1 }

# Resolve python.exe to an ABSOLUTE path. Task Scheduler does not inherit the interactive PATH:
# -Execute 'python' registers fine and then fails at run time with 0x80070002 while the task
# list still looks healthy (measured 2026-08-13 on the kaizen task).
$python = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $python) { Write-Error "python.exe not found on PATH; cannot register a task that would silently fail."; exit 1 }

$action = New-ScheduledTaskAction -Execute $python -Argument ('"' + $py + '"') -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Daily -At '08:00'
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Description 'go5-maker: 08:00 JST - wake the frontend design room to run the morning design review (design-preferences.md section 100). Chami 2026-08-24.' -Force | Out-Null

Write-Host ("OK: registered '" + $TaskName + "' (daily 08:00 JST).") -ForegroundColor Green
