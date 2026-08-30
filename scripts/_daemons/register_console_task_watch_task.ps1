# register_console_task_watch_task.ps1 - go5-maker (aegis-gl / 2026-08-30).
# Registers a 6-hourly task that checks NO go5_* task pops a black console window.
#
# Why this exists:
#   Chami (msg 1543598413340475462): "the black windows that pop up periodically in Task
#   Scheduler - please don't show them on screen". HQ measured 19 of 31 go5_* tasks running
#   python.exe / powershell.exe directly (= owns a console = a window is drawn) and converted
#   them to wscript.exe + run_hidden.vbs.
#   HQ's own words when handing the follow-up to aegis-gl: "this time a HUMAN noticed and a
#   HUMAN fixed it => the same hole will open again". This task owns the unattended half.
#
# Two halves, one verdict:
#   entry gate      = hidden_task.ps1        (New-Go5HiddenAction; nothing can be registered wrong)
#   unattended eye  = console_task_watch.py  (this task; catches whatever bypassed the gate)
#   Both read scripts\_daemons\console_window_policy.json. The list of console-owning exes and
#   the deliberate exceptions live there ONCE - two copies guarantee one goes stale.
#
# Cost: near zero. One Get-ScheduledTask + a walk over scripts\*.ps1. No LLM call. It mails
#   HQ only when the SET of violations changes, so a standing violation is reported once
#   (a net that rings every 6 hours is a net everybody learns to ignore).
#
# Why 6-hourly and not hourly: nothing here changes without a human running a register script.
#
# Dogfood: this registration goes through New-Go5HiddenAction like every other one. pythonw
#   is already console-free so the gate passes it through untouched - that is the point, the
#   gate is a no-op on things that were already right.
#
# NOTE: keep this file ASCII-only (PowerShell 5.1 reads a no-BOM file as the ANSI codepage).
#
# Reversible: schtasks /Delete /TN go5_console_task_watch /F

$ErrorActionPreference = 'Stop'
$TaskName = 'go5_console_task_watch'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$script = Join-Path $root 'scripts\_daemons\console_task_watch.py'

$pyw = 'C:\Users\chami\AppData\Local\Programs\Python\Python312\pythonw.exe'
if (-not (Test-Path $pyw)) {
  $cmd = (Get-Command pythonw.exe -ErrorAction SilentlyContinue)
  if ($cmd) { $pyw = $cmd.Source } else { throw 'pythonw.exe not found' }
}
if (-not (Test-Path $script)) { throw "console_task_watch.py not found: $script" }

# every scheduled task goes through the gate so it can never pop a console window
# (aegis-gl 2026-08-30 / see scripts\_daemons\hidden_task.ps1)
$go5Here = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Definition }
. (Join-Path $go5Here 'hidden_task.ps1')
$action  = New-Go5HiddenAction -Execute $pyw -Argument ('"' + $script + '"') -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Hours 6) -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 5)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Description 'go5-maker: 6-hourly guard that no scheduled task pops a console window (aegis-gl)' -Force | Out-Null
Write-Host ("Registered scheduled task: {0} (every 6h, pythonw hidden)" -f $TaskName)
