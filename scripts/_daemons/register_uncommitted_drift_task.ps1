# register_uncommitted_drift_task.ps1 - go5-maker (aegis-gl / 2026-09-16).
# Registers a DAILY task that records one line about uncommitted code that is sitting unfolded.
#
# Why: HQ verdict C-079 (2026-09-16). Folding is done by the department that touched the code,
#   in the same turn it writes its change_log line ("no real commit hash => do not write the row").
#   Nobody folds on behalf of anybody, and the 121 stale files are NOT squashed in one batch.
#   So the only thing left to build is an EYE: name, every day, which files a resident daemon
#   actually loads that are still missing from git, how many days they have been sitting (age),
#   and who owns them. C-079 forbids a bare count alarm: the line must carry age + owner.
#
# This task only READS git (diff --numstat / log -1). It never adds, commits or pushes.
#
# Why a scheduled task (not a keeper daemon):
#   pythonw launches uncommitted_drift.py fresh each day, so editing the .py is live on the next
#   tick. Nothing to reload => not added to daemon_keeper.WATCH_FILES / supervise_daemons.ps1
#   (C-042: the reload path is decided here = "re-run picks up new code").
#
# Output: local\llm\uncommitted_drift.jsonl (append only). The "line" field is the daily one line;
#   stdout is invisible under pythonw, so the JSONL is the record of record.
#
# NOTE: keep this file ASCII-only (PowerShell 5.1 reads a no-BOM file as the ANSI codepage).
#
# Reversible: schtasks /Delete /TN go5_uncommitted_drift /F

$ErrorActionPreference = 'Stop'
$TaskName = 'go5_uncommitted_drift'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$script = Join-Path $root 'scripts\_daemons\uncommitted_drift.py'

$pyw = 'C:\Users\chami\AppData\Local\Programs\Python\Python312\pythonw.exe'
if (-not (Test-Path $pyw)) {
  $cmd = (Get-Command pythonw.exe -ErrorAction SilentlyContinue)
  if ($cmd) { $pyw = $cmd.Source } else { throw 'pythonw.exe not found' }
}
if (-not (Test-Path $script)) { throw "uncommitted_drift.py not found: $script" }

# every scheduled task goes through the gate so it can never pop a console window
# (aegis-gl 2026-08-30 / see scripts\_daemons\hidden_task.ps1)
$go5Here = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Definition }
. (Join-Path $go5Here 'hidden_task.ps1')
$action  = New-Go5HiddenAction -Execute $pyw -Argument ('"' + $script + '" --quiet') -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Daily -At 10:00
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Description 'go5-maker: daily one line naming resident code that is still uncommitted, with age and owner (read-only, C-079)' -Force | Out-Null
Write-Host ("Registered scheduled task: {0} (daily 10:00, pythonw hidden, read-only)" -f $TaskName)
