# register_deadman_task.ps1 - go5-maker (permanent-fix #1 / 2026-07-18).
# Registers an INDEPENDENT scheduled task that runs the fleet dead-man check every 15 minutes.
# It must NOT be managed by supervise_daemons: the whole point is to detect the supervisor's
# own death, so it has to run from a separate scheduler entry (otherwise they die together).
# Hidden: launched via pythonw.exe (no console window). --once so each run exits; the task
# repetition re-fires it, which also survives a hung run (next fire is independent).
#
# NOTE: keep this file ASCII-only. PowerShell 5.1 reads a no-BOM file as the system ANSI
#       codepage; non-ASCII here corrupts parsing. Japanese notes live in README.md.
#
# Reversible: schtasks /Delete /TN go5_deadman_check /F   (or Unregister-ScheduledTask).

$ErrorActionPreference = 'Stop'
$TaskName = 'go5_deadman_check'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$script = Join-Path $root 'scripts\_daemons\deadman_check.py'

# Resolve pythonw.exe (hidden interpreter). Prefer the real Python install over the WindowsApps shim.
$pyw = 'C:\Users\chami\AppData\Local\Programs\Python\Python312\pythonw.exe'
if (-not (Test-Path $pyw)) {
  $cmd = (Get-Command pythonw.exe -ErrorAction SilentlyContinue)
  if ($cmd) { $pyw = $cmd.Source } else { throw 'pythonw.exe not found' }
}
if (-not (Test-Path $script)) { throw "deadman_check.py not found: $script" }

$action  = New-ScheduledTaskAction -Execute $pyw -Argument ('"' + $script + '" --once') -WorkingDirectory $root
# Repeat every 15 min, effectively forever. StartWhenAvailable catches missed runs (sleep/off).
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 15) -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 3)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Description 'go5-maker: independent fleet dead-man (detects supervisor death, alerts Discord incident ch)' -Force | Out-Null
Write-Host ("Registered scheduled task: {0} (every 15 min, pythonw hidden)" -f $TaskName)
