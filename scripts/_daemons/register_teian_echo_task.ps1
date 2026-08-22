# register_teian_echo_task.ps1 - go5-maker (platform-se / 2026-08-23).
# Registers a 5-minute scheduled task that echoes new "teian_decide" sheet rows to gunji (route B).
#
# Why a scheduled task (not a keeper daemon):
#   The task launches teian_echo_poll.py fresh with pythonw every 5 minutes. Editing the .py is
#   therefore live on the next tick with no reload step. We do NOT add this to daemon_keeper.WATCH_FILES /
#   supervise_daemons.ps1 / preflight_daemon_lifecycle.py, because it is not a resident process to
#   supervise (C-042: the reload path is decided here = "re-run picks up new code, nothing to reload").
#
# The poller is fail-open: if the GAS read endpoint is down / returns HTML / the JSON is broken
# (including before the read endpoint even exists), it advances no watermark and stays quiet,
# ringing once only on the Nth consecutive failure.
#
# NOTE: keep this file ASCII-only (PowerShell 5.1 reads a no-BOM file as the ANSI codepage).
#
# Reversible: schtasks /Delete /TN go5_teian_echo /F

$ErrorActionPreference = 'Stop'
$TaskName = 'go5_teian_echo'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$script = Join-Path $root 'scripts\_daemons\teian_echo_poll.py'

$pyw = 'C:\Users\chami\AppData\Local\Programs\Python\Python312\pythonw.exe'
if (-not (Test-Path $pyw)) {
  $cmd = (Get-Command pythonw.exe -ErrorAction SilentlyContinue)
  if ($cmd) { $pyw = $cmd.Source } else { throw 'pythonw.exe not found' }
}
if (-not (Test-Path $script)) { throw "teian_echo_poll.py not found: $script" }

$action  = New-ScheduledTaskAction -Execute $pyw -Argument ('"' + $script + '"') -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 5)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Description 'go5-maker: echo new teian_decide rows to gunji (route B, watermark-gated, fail-open)' -Force | Out-Null
Write-Host ("Registered scheduled task: {0} (every 5 min, pythonw hidden)" -f $TaskName)
