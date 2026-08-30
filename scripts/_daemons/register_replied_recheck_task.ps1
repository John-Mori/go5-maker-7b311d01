# register_replied_recheck_task.ps1 - go5-maker (aegis-gl / 2026-08-05).
# Registers a scheduled task that re-judges `replied_unverified` rows AFTER the fact.
#
# Why a separate scheduler entry (not inside dept_daemon):
#   dept_daemon verifies its own reply synchronously, at most ~4 seconds after posting.
#   Measured post-vs-record gaps run from +0s to +237s, so the synchronous check can never
#   settle it, and widening the wait would stall the reply path itself. The late re-judge
#   must therefore run on its own clock, decoupled from the daemon.
#
# --min-age-min 15: never touch a record younger than 15 minutes (no race with the live path).
# Read-only against Discord; append-only against request_log.jsonl; never resends anything.
#
# NOTE: keep this file ASCII-only (PowerShell 5.1 reads a no-BOM file as the ANSI codepage).
#
# Reversible: schtasks /Delete /TN go5_replied_recheck /F

$ErrorActionPreference = 'Stop'
$TaskName = 'go5_replied_recheck'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$script = Join-Path $root 'scripts\_daemons\replied_recheck.py'

$pyw = 'C:\Users\chami\AppData\Local\Programs\Python\Python312\pythonw.exe'
if (-not (Test-Path $pyw)) {
  $cmd = (Get-Command pythonw.exe -ErrorAction SilentlyContinue)
  if ($cmd) { $pyw = $cmd.Source } else { throw 'pythonw.exe not found' }
}
if (-not (Test-Path $script)) { throw "replied_recheck.py not found: $script" }

# every scheduled task goes through the gate so it can never pop a console window
# (aegis-gl 2026-08-30 / see scripts\_daemons\hidden_task.ps1)
$go5Here = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Definition }
. (Join-Path $go5Here 'hidden_task.ps1')
$action  = New-Go5HiddenAction -Execute $pyw -Argument ('"' + $script + '" --min-age-min 15') -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 30) -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Description 'go5-maker: late re-judge of replied_unverified (real misses only)' -Force | Out-Null
Write-Host ("Registered scheduled task: {0} (every 30 min, pythonw hidden)" -f $TaskName)
