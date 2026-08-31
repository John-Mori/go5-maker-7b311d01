# register_window_catcher_task.ps1 - go5-maker (aegis-gl / 2026-08-31).
# Keeps HQ's black-window stakeout (local\_work\hq_window_catcher.py) running even when no
# Claude session is open.
#
# Why this exists:
#   HQ (msg 1543845369719558285): the stakeout dies together with the HQ session. To tell
#   whether deadman_check.py:241 (commit 7f6e71c, 00_AI-HQ) really brought the window count
#   to 0, somebody has to keep watching across several 15-minute deadman cycles WITH NO
#   SESSION OPEN. A watcher that only lives inside a chat session cannot answer that.
#
# Shape:
#   - the catcher runs FOREVER (first arg 0 = no deadline). It is the resident, not the task.
#   - the task's 15-minute repetition is a REVIVER, not a re-run: MultipleInstances IgnoreNew
#     means the tick is dropped while the catcher is alive, and starts it again if it died.
#     Worst-case blind gap after a crash = 15 minutes, and that gap is VISIBLE because the
#     liveness file stops beating (see below).
#   - AtLogOn trigger so a reboot does not silently end the stakeout.
#
# Two files, on purpose:
#   local\_work\hq_window_catch.jsonl        = evidence. ONLY window rows. 0 rows = 0 windows.
#   local\_work\hq_window_catch_alive.jsonl  = liveness. start / alive (5 min) / stop / end.
#   Mixing them would destroy the only thing HQ is trying to measure: "no window appeared"
#   and "nobody was watching" both look like an empty evidence file.
#
# Stop it without killing anything:
#   New-Item local\_work\hq_window_catcher.stop   (the catcher writes a stop row and exits)
# Reversible:
#   schtasks /Delete /TN go5_window_catcher /F
#
# The registration goes through the gate (New-Go5HiddenAction) like every other go5_ task, and
# the name starts with go5_ on purpose so console_task_watch.py already covers it. A stakeout
# for black windows must not be the thing that pops one.
#
# NOTE: keep this file ASCII-only (PowerShell 5.1 reads a no-BOM file as the ANSI codepage).

$ErrorActionPreference = 'Stop'
$TaskName = 'go5_window_catcher'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$script = Join-Path $root 'local\_work\hq_window_catcher.py'

$pyw = 'C:\Users\chami\AppData\Local\Programs\Python\Python312\pythonw.exe'
if (-not (Test-Path $pyw)) {
  $cmd = (Get-Command pythonw.exe -ErrorAction SilentlyContinue)
  if ($cmd) { $pyw = $cmd.Source } else { throw 'pythonw.exe not found' }
}
if (-not (Test-Path $script)) { throw "hq_window_catcher.py not found: $script" }

$go5Here = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Definition }
. (Join-Path $go5Here 'hidden_task.ps1')
# 0 = watch forever, 0.4 = poll seconds (a powershell one-liner's window can live under 1s)
$action = New-Go5HiddenAction -Execute $pyw -Argument ('"' + $script + '" 0 0.4') -WorkingDirectory $root

$t1 = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 15) -RepetitionDuration (New-TimeSpan -Days 3650)
# -User is required: an AtLogOn trigger for ANY user needs elevation (0x80070005 without it).
$t2 = New-ScheduledTaskTrigger -AtLogOn -User ("{0}\{1}" -f $env:USERDOMAIN, $env:USERNAME)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Days 3650)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger @($t1, $t2) -Settings $settings -Description 'go5-maker: keeps the black-window stakeout alive with no session open (aegis-gl, for HQ-0223)' -Force | Out-Null
Write-Host ("Registered scheduled task: {0} (resident catcher, 15min reviver, pythonw hidden)" -f $TaskName)
