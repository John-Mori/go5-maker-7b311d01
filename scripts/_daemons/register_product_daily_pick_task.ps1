# register_product_daily_pick_task.ps1 - register the 08:00 JST daily product candidate pick.
# Chami asked (msg 1537485839758663742): "every morning at 8, pick candidates and tell me.
# I'm going to sleep, so set it up." Relayed as a work request by the product-scout dept
# (msg 1537487811081404566) to the platform/infra side.
#   - Runs scripts\_daemons\run_product_daily_pick.py, which generates the pick AND posts it
#     to the product-scout room under the dept persona (C-036: the launcher itself reports;
#     do not rely on an interactive session noticing).
#   - 08:00 exactly, as asked. Three other tasks fire at 08:00 (go5_daily_report_0800,
#     go5_reaction_watch_0800, go5_se_daily_review_0800); they are separate processes and
#     Windows runs them concurrently. Chami said "8", so this one sits on 8.
#   - StartWhenAvailable => if the box was asleep at 08:00, it runs ASAP after wake instead of
#     silently skipping the day (a morning report that quietly does not happen is the worst case).
#   - The generator reads D1 through "npx wrangler", so it needs node on PATH. node lives in the
#     MACHINE PATH (C:\Program Files\nodejs\), which Task Scheduler does inherit - verified
#     2026-08-14 by reading the registry, and again by firing the task once for real.
# No admin required (registered as the current user). ASCII-only (PS 5.1 codepage safety).
$ErrorActionPreference = 'Stop'
$TaskName = 'go5_product_daily_pick_0800'
if ($PSScriptRoot) { $here = $PSScriptRoot } else { $here = Split-Path -Parent $MyInvocation.MyCommand.Definition }
$root = Split-Path -Parent (Split-Path -Parent $here)
$py = Join-Path $root 'scripts\_daemons\run_product_daily_pick.py'
if (-not (Test-Path $py)) { Write-Error ("run_product_daily_pick.py not found: " + $py); exit 1 }

# Resolve python.exe to an ABSOLUTE path. Task Scheduler does not inherit the interactive
# PATH: -Execute 'python' registers fine and then fails at run time with 0x80070002
# ("cannot find the file specified") - i.e. it looks healthy in the task list while never
# producing a report. Measured 2026-08-13 on the kaizen task. Resolve it here instead.
$python = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $python) { Write-Error "python.exe not found on PATH; cannot register a task that would silently fail."; exit 1 }

$action = New-ScheduledTaskAction -Execute $python -Argument ('"' + $py + '"') -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Daily -At '08:00'
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 15)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Description 'go5-maker: 08:00 JST - generate the product candidate pick and post it to the product-scout room (Chami 2026-08-14)' -Force | Out-Null

Write-Host ("OK: registered '" + $TaskName + "' (daily 08:00 JST).") -ForegroundColor Green
