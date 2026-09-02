# register_clean_reader_refresh_task.ps1 - go5-maker (aegis-gl / 2026-09-03).
#
# WHY: the analysis dept (Almond Eye) shipped scripts\analysis\clean_reader.py (commit 741c12a)
#   and asked HQ to put "--refresh-all" on a clock. HQ routed the runner to us (C-015: the
#   execution vessel is infrastructure). The tool itself belongs to the analysis dept and is
#   NOT touched here - we only call it.
#
# WHAT RUNS: scripts\_daemons\clean_reader_refresh.py (thin wrapper).
#   It calls clean_reader.refresh_all() and ALWAYS appends one line to
#   local\_work\clean_reader_refresh.log. Reason: refresh_all() swallows per-URL failures and
#   still returns 0, so "ran but updated nothing" would be invisible under pythonw. That log is
#   registered in local\llm\producers.json so absence_watchdog alerts on staleness (C-042).
#
# SCHEDULE: 07:40 and 19:40 local time (box TZ = Tokyo Standard Time = JST).
#   - Measured cost: 0.6s wall, 2 article fetches (3 targets, 1 is a site root and is skipped).
#     Negligible against C-058, but 08:00 is already crowded (competitor_daily / frontend_design
#     / product_daily_pick / reaction_watch / daily_report all fire at 08:00-08:10), so we sit
#     20 minutes before it instead of joining the pile.
#   - Twice a day = fresh before Chami reads in the morning and again before the evening.
#   - StartWhenAvailable => a missed run (box asleep/off) fires ASAP after wake instead of
#     being skipped. Same known hole as every other task: the box must be logged on.
#
# NOTE: keep this file ASCII-only (PowerShell 5.1 reads a no-BOM file as the ANSI codepage).
#
# Reversible: schtasks /Delete /TN go5_clean_reader_refresh /F

$ErrorActionPreference = 'Stop'
$TaskName = 'go5_clean_reader_refresh'
if ($PSScriptRoot) { $here = $PSScriptRoot } else { $here = Split-Path -Parent $MyInvocation.MyCommand.Definition }
$root = Split-Path -Parent (Split-Path -Parent $here)
$script = Join-Path $root 'scripts\_daemons\clean_reader_refresh.py'
if (-not (Test-Path $script)) { throw ("clean_reader_refresh.py not found: " + $script) }

$pyw = 'C:\Users\chami\AppData\Local\Programs\Python\Python312\pythonw.exe'
if (-not (Test-Path $pyw)) {
  $cmd = (Get-Command pythonw.exe -ErrorAction SilentlyContinue)
  if ($cmd) { $pyw = $cmd.Source } else { throw 'pythonw.exe not found' }
}

# every scheduled task goes through the gate so it can never pop a console window
# (aegis-gl 2026-08-30 / see scripts\_daemons\hidden_task.ps1)
. (Join-Path $here 'hidden_task.ps1')
$action = New-Go5HiddenAction -Execute $pyw -Argument ('"' + $script + '"') -WorkingDirectory $root
$triggers = @(
  (New-ScheduledTaskTrigger -Daily -At '07:40'),
  (New-ScheduledTaskTrigger -Daily -At '19:40')
)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $triggers -Settings $settings -Description 'go5-maker: 07:40 / 19:40 JST - re-fetch every clean-view target (clean_reader --refresh-all) and rebuild the index. Owner of the tool: analysis dept (Almond Eye).' -Force | Out-Null

Write-Host ("OK: registered '" + $TaskName + "' (daily 07:40 and 19:40 JST, pythonw hidden).") -ForegroundColor Green
