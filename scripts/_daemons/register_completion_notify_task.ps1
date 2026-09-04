# register_completion_notify_task.ps1 - go5-maker (aegis-gl / 2026-09-04).
# Registers a scheduled task that returns ONE line to the ordering department when a
# request reaches `completed` / `replied` in request_log.jsonl.
#
# Why it exists (measured, 2026-09-04):
#   03:15 ad-lab ordered two departments. Both finished by 03:2x and dropped their results
#   into local/consult_intel/. The ordering department did not learn about it until 12:00 -
#   eight and a half hours carrying a finished job as unfinished. The machine knew; only the
#   orderer did not. Results land in a directory (nobody rings), local/ is gitignored (no
#   git log), and request_log already held both `completed` and the landed msg id.
#   The written rule (common discipline 3.8) only binds humans; if the receiving department
#   forgets, the same hole reopens. This is the machine-side fix.
#
# --min-age-min 15: give the receiving department a window to answer for itself first
#   (a duplicate is cheap; a race with the live path is not).
# --since-hours 24: never ring for anything older than a day (so installing it does not
#   fire hundreds of notices at once).
# --limit 5: cap per run.
# Append-only against request_log.jsonl (state `completion_notified` = idempotence key).
# Never resends, never carries the payload, never guesses a destination.
#
# NOTE: keep this file ASCII-only (PowerShell 5.1 reads a no-BOM file as the ANSI codepage).
#
# Reversible: schtasks /Delete /TN go5_completion_notify /F

$ErrorActionPreference = 'Stop'
$TaskName = 'go5_completion_notify'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$script = Join-Path $root 'scripts\_daemons\completion_notify.py'

$pyw = 'C:\Users\chami\AppData\Local\Programs\Python\Python312\pythonw.exe'
if (-not (Test-Path $pyw)) {
  $cmd = (Get-Command pythonw.exe -ErrorAction SilentlyContinue)
  if ($cmd) { $pyw = $cmd.Source } else { throw 'pythonw.exe not found' }
}
if (-not (Test-Path $script)) { throw "completion_notify.py not found: $script" }

# every scheduled task goes through the gate so it can never pop a console window
# (aegis-gl 2026-08-30 / see scripts\_daemons\hidden_task.ps1)
$go5Here = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Definition }
. (Join-Path $go5Here 'hidden_task.ps1')
$action  = New-Go5HiddenAction -Execute $pyw -Argument ('"' + $script + '" --min-age-min 15 --since-hours 24 --limit 5') -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 10) -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Description 'go5-maker: ring the ordering department one line when a request completes' -Force | Out-Null
Write-Host ("Registered scheduled task: {0} (every 10 min, pythonw hidden)" -f $TaskName)
