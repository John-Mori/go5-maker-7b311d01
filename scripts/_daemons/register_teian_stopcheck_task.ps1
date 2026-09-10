# register_teian_stopcheck_task.ps1 - register the 07:30 JST one-shot-ish check that the frozen
# teian daily chain (go5_teian_daily_0700) really does NOT fire.
#
# WHY: on 2026-09-10 07:26 the Aegis lab disabled go5_teian_daily_0700 (freeze of the 5sec maker,
# Chami 2026-09-09). "State=Disabled" is only the registration side. Discipline 3: a safety net is
# not done when it is registered - it must be run once through the real firing condition. The real
# firing condition is 07:00 tomorrow and cannot be triggered from here, so the "look again tomorrow"
# is given to a machine instead of to whoever happens to be on shift.
#
#   - Runs scripts\_daemons\verify_teian_stopped.py at 07:30, i.e. after the old chain's window
#     (its last real run wrote its log line at 07:17:57).
#   - The checker reports ONCE and then disables itself when it sees a clean no-fire; it stays
#     enabled on fired / re-enabled / unreadable, so a daily "still stopped" nag never appears.
# Reversible: schtasks /Change /TN go5_teian_stopcheck_0730 /DISABLE   (do not delete)
# ASCII-only (PS 5.1 codepage safety).
$ErrorActionPreference = 'Stop'
$TaskName = 'go5_teian_stopcheck_0730'
if ($PSScriptRoot) { $here = $PSScriptRoot } else { $here = Split-Path -Parent $MyInvocation.MyCommand.Definition }
$root = Split-Path -Parent (Split-Path -Parent $here)
$py = Join-Path $root 'scripts\_daemons\verify_teian_stopped.py'
if (-not (Test-Path $py)) { Write-Error ("verify_teian_stopped.py not found: " + $py); exit 1 }

# absolute python.exe - Task Scheduler does not inherit the interactive PATH (measured 2026-08-13)
$python = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $python) { Write-Error "python.exe not found on PATH; cannot register a task that would silently fail."; exit 1 }

. (Join-Path $here 'hidden_task.ps1')
$action = New-Go5HiddenAction -Execute $python -Argument ('"' + $py + '"') -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Daily -At '07:30'
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 20)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Description 'go5-maker: 07:30 JST - verify that the frozen teian daily chain (go5_teian_daily_0700) did not fire. Reports once to the Aegis lab and disables itself on a clean no-fire; stays enabled if it fired, was re-enabled, or could not be read.' -Force | Out-Null

Write-Host ("OK: registered '" + $TaskName + "' (daily 07:30 JST, self-retiring).") -ForegroundColor Green
