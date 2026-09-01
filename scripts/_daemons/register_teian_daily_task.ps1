# register_teian_daily_task.ps1 - register the 07:00 JST daily "teian" chain.
# Ordered by the alpha repair room (Otacon, 2026-09-02, msg DISPATCH-aegis-gl-1788297884562);
# wired by the Aegis lab because scheduler/daemon layout is base infrastructure (C-015).
#
# WHY: the proposal page's "no 3 choices" bug had a single root cause - teian/latest.json was
# frozen at 2026-08-24 for 8 days because NO scheduled task ever ran scripts\teian\run_daily_teian.py
# (measured: schtasks had no teian/daily job). A hand-run job rots silently. C-038 permanent fix.
#
#   - Runs scripts\_daemons\run_daily_teian_job.py (NOT the chain directly). That wrapper always
#     writes a pulse file and reports a non-zero chain exit to the alpha room, so a dead job is
#     visible instead of silent. Registering the chain bare would rebuild the exact hole we are closing.
#   - 07:00 JST, not 08:00: seven go5_*_0800 tasks already fire at 08:00 and this one is the heavy
#     one (Gemini vision calls). Running first also means the 08:00 rooms read fresh data.
#   - StartWhenAvailable => if the box was asleep at 07:00 it runs after wake instead of skipping
#     the day. This job needs local\gemini_api_key.txt and wrangler credentials = this PC only.
#   - ExecutionTimeLimit 2h: the wrapper itself times the chain out at 1h, so the task limit is
#     only a backstop; it must be larger or it would kill the wrapper before it can report.
# No admin required (registered as the current user). ASCII-only (PS 5.1 codepage safety).
$ErrorActionPreference = 'Stop'
$TaskName = 'go5_teian_daily_0700'
if ($PSScriptRoot) { $here = $PSScriptRoot } else { $here = Split-Path -Parent $MyInvocation.MyCommand.Definition }
$root = Split-Path -Parent (Split-Path -Parent $here)
$py = Join-Path $root 'scripts\_daemons\run_daily_teian_job.py'
if (-not (Test-Path $py)) { Write-Error ("run_daily_teian_job.py not found: " + $py); exit 1 }

# Resolve python.exe to an ABSOLUTE path. Task Scheduler does not inherit the interactive PATH:
# -Execute 'python' registers fine and then fails at run time with 0x80070002 while the task
# list still looks healthy (measured 2026-08-13 on the kaizen task).
$python = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $python) { Write-Error "python.exe not found on PATH; cannot register a task that would silently fail."; exit 1 }

# every scheduled task goes through the gate so it can never pop a console window
# (aegis-gl 2026-08-30 / see scripts\_daemons\hidden_task.ps1)
. (Join-Path $here 'hidden_task.ps1')
$action = New-Go5HiddenAction -Execute $python -Argument ('"' + $py + '"') -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Daily -At '07:00'
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 2)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Description 'go5-maker: 07:00 JST - run the daily teian chain (regenerate -> carry over comments -> vision -> publish) via run_daily_teian_job.py. Ordered by alpha repair room 2026-09-02; fixes the 8-day silent freeze of teian/latest.json.' -Force | Out-Null

Write-Host ("OK: registered '" + $TaskName + "' (daily 07:00 JST).") -ForegroundColor Green
