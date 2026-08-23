# register_envelope_naming_watch_task.ps1 - go5-maker (aegis-gl / 2026-08-23).
# Registers an hourly task that checks the spelling of person names inside the envelope
# (the discipline file + the ruling-catalog headings that go into EVERY room's EVERY message).
#
# Why a scheduled task and not "just check 15":
#   HQ asked aegis-gl to hang envelope_naming_check.py on relay_health.py's check list
#   (DISPATCH-aegis-gl-1787459939764). Done = check 15. But NO scheduled task runs
#   relay_health.py at all (measured: walked every registered task's action, 0 hits), so
#   check 15 only rings when a human remembers to run the diagnosis. Meanwhile a wrong
#   spelling keeps being taught to every room on every message. This task owns the
#   unattended half. The verdict itself stays in envelope_naming_check.scan() (one source).
#
# Cost: near zero. The watcher exits immediately unless the mtime of one of its inputs moved
#   (discipline / catalog / naming-rules json / the check itself). No LLM call. It mails HQ
#   only when the set of violations changes, so a standing violation is reported once.
#
# Why a scheduled task (not a keeper daemon):
#   pythonw launches the script fresh each hour, so editing the .py is live on the next tick.
#   Nothing to reload => not added to daemon_keeper.WATCH_FILES / supervise_daemons.ps1
#   (C-042: the reload path is decided here = "re-run picks up new code").
#
# NOTE: keep this file ASCII-only (PowerShell 5.1 reads a no-BOM file as the ANSI codepage).
#
# Reversible: schtasks /Delete /TN go5_envelope_naming_watch /F
#             (or Disable-ScheduledTask -TaskName go5_envelope_naming_watch)

$ErrorActionPreference = 'Stop'
$TaskName = 'go5_envelope_naming_watch'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$script = Join-Path $root 'scripts\_daemons\envelope_naming_watch.py'

$pyw = 'C:\Users\chami\AppData\Local\Programs\Python\Python312\pythonw.exe'
if (-not (Test-Path $pyw)) {
  $cmd = (Get-Command pythonw.exe -ErrorAction SilentlyContinue)
  if ($cmd) { $pyw = $cmd.Source } else { throw 'pythonw.exe not found' }
}
if (-not (Test-Path $script)) { throw "envelope_naming_watch.py not found: $script" }

$action  = New-ScheduledTaskAction -Execute $pyw -Argument ('"' + $script + '"') -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 60) -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 5)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Description 'go5-maker: hourly guard that the envelope teaches only the correct spelling of person names (aegis-gl)' -Force | Out-Null
Write-Host ("Registered scheduled task: {0} (hourly, pythonw hidden)" -f $TaskName)
