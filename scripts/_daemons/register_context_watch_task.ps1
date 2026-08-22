# register_context_watch_task.ps1 - go5-maker (aegis-gl / 2026-08-22).
# Registers a scheduled task that measures the context size of every live Claude session
# and warns HQ when a session OUTSIDE session_relay's control crosses the absolute line.
#
# Why a separate scheduler entry:
#   session_relay compacts (120,000) and rotates (185,000) only the sessions it launched.
#   A hand-opened window is never touched. Measured 2026-08-22: the lab main session
#   0351851c ran at a median context of 486,209 tokens (max 933,992) for 7,526 turns,
#   while every relay-managed room stayed at 100k-150k. Cache reads = 71.2% of the weekly
#   quota (HQ measurement msg 1540618940533841982).
#   The per-turn hook (scripts/hooks/context_guard.py) warns inside such a session;
#   this task is the outside observer, so growth is noticed even when nobody is looking.
#
# The line is an ABSOLUTE token count read from session_relay.py. It is deliberately NOT
# derived from the model context window: the old "CLI auto-compacts near 167,000" figure
# was measured on 200K-window models, and silently rises to ~930,000 on a 1M-window model.
#
# Read-only: reads ~/.claude/projects/**/*.jsonl and local ledgers. Appends one row to
# local/llm/context_watch.jsonl. --alert puts one message on the HQ queue (not Discord),
# at most once per hour per session.
#
# NOTE: keep this file ASCII-only (PowerShell 5.1 reads a no-BOM file as the ANSI codepage).
#
# Reversible: schtasks /Delete /TN go5_context_watch /F

$ErrorActionPreference = 'Stop'
$TaskName = 'go5_context_watch'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$script = Join-Path $root 'scripts\llm\context_watch.py'

$pyw = 'C:\Users\chami\AppData\Local\Programs\Python\Python312\pythonw.exe'
if (-not (Test-Path $pyw)) {
  $cmd = (Get-Command pythonw.exe -ErrorAction SilentlyContinue)
  if ($cmd) { $pyw = $cmd.Source } else { throw 'pythonw.exe not found' }
}
if (-not (Test-Path $script)) { throw "context_watch.py not found: $script" }

$action  = New-ScheduledTaskAction -Execute $pyw -Argument ('"' + $script + '" --hours 12 --record --alert') -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 60) -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Description 'go5-maker: watch context size of sessions outside session_relay (weekly quota)' -Force | Out-Null
Write-Host ("Registered scheduled task: {0} (every 60 min, pythonw hidden)" -f $TaskName)
