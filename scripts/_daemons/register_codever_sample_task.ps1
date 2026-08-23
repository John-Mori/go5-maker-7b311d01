# register_codever_sample_task.ps1 - go5-maker (aegis-gl / 2026-08-23).
# Registers an hourly task that records the daemon code-version spread to a JSONL history.
#
# Why: relay_health.py check 14 (HQ, 2026-08-23) flags departments stuck >2h on old code, but
#   (a) it only reports the current instant and (b) NO scheduled task runs relay_health.py at all
#   (checked every registered task's action: 0 hits). So a >2h stall would ring for nobody.
#   Before adding an alarm we measure whether >2h actually happens: HQ saw 4 behind at 08:5x and
#   this room measured 32/32 same at 09:3x and 12:1x. Both are single observations (C-041).
#   This sampler only records. The threshold judgement stays in check_codever (one source).
#
# Why a scheduled task (not a keeper daemon):
#   pythonw launches codever_sample.py fresh each hour, so editing the .py is live on the next tick.
#   Nothing to reload => not added to daemon_keeper.WATCH_FILES / supervise_daemons.ps1 (C-042:
#   the reload path is decided here = "re-run picks up new code").
#
# NOTE: keep this file ASCII-only (PowerShell 5.1 reads a no-BOM file as the ANSI codepage).
#
# Reversible: schtasks /Delete /TN go5_codever_sample /F

$ErrorActionPreference = 'Stop'
$TaskName = 'go5_codever_sample'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$script = Join-Path $root 'scripts\_daemons\codever_sample.py'

$pyw = 'C:\Users\chami\AppData\Local\Programs\Python\Python312\pythonw.exe'
if (-not (Test-Path $pyw)) {
  $cmd = (Get-Command pythonw.exe -ErrorAction SilentlyContinue)
  if ($cmd) { $pyw = $cmd.Source } else { throw 'pythonw.exe not found' }
}
if (-not (Test-Path $script)) { throw "codever_sample.py not found: $script" }

$action  = New-ScheduledTaskAction -Execute $pyw -Argument ('"' + $script + '"') -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 60) -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 5)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Description 'go5-maker: hourly sample of daemon code-version spread (observation only, no alarm)' -Force | Out-Null
Write-Host ("Registered scheduled task: {0} (hourly, pythonw hidden)" -f $TaskName)
