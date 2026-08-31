# register_persona_queue_poller_task.ps1 - go5-maker (aegis-gl / 2026-09-01).
# Registers a 1-minute task that drains the persona-icon queue on R2 into the ledger.
#
# Why this exists:
#   The persona hub page uploads an image (PUT /api/img/<sha256>) and then declares
#   "this key belongs to <persona>" (POST /api/persona/enqueue, appended to the R2 key
#   persona/queue.jsonl). Nothing on the PC watches that file - and R2 has no object
#   listing through wrangler (r2 object = get/put/delete only, measured 2026-09-01),
#   so the PC can only find new declarations by reading that one fixed key.
#   Without this task the button on the page looks alive and silently does nothing,
#   which is the worst failure mode we have (silence).
#
# Why now (2026-09-01): go5-sync is deployed with the enqueue route live
#   (version e4334c98-f3d8-410a-bc64-dcc6b6e13538 / measured: token-less POST -> 403,
#   an unknown route -> 404, so the route really exists).
#
# Cost (measured, this machine): an empty poll = 2.4-2.5 s wall, one npx wrangler read
#   of a single small key. No LLM call, no writes when the queue key is absent.
#   1 minute is the shortest interval Task Scheduler accepts and it is what the
#   acceptance condition ("pick an image -> tens of seconds later it is in the ledger")
#   needs. MultipleInstances IgnoreNew keeps polls from stacking on a slow network.
#
# Why a scheduled task (not a keeper daemon):
#   pythonw starts the script fresh every tick, so editing the .py is live on the next
#   run - nothing to reload. Therefore it is NOT added to daemon_keeper.WATCH_FILES /
#   supervise_daemons.ps1 (C-042: the reload path is decided here = "re-run picks up
#   new code"). Same shape as register_envelope_naming_watch_task.ps1.
#
# SYNC_TOKEN is NOT needed and must NOT be placed on this PC: writes go through the
#   Worker, reads go through wrangler (account credentials). Keep that direction.
#
# NOTE: keep this file ASCII-only (PowerShell 5.1 reads a no-BOM file as the ANSI codepage).
#
# Reversible: schtasks /Delete /TN go5_persona_queue_poller /F
#             (or Disable-ScheduledTask -TaskName go5_persona_queue_poller)

$ErrorActionPreference = 'Stop'
$TaskName = 'go5_persona_queue_poller'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$script = Join-Path $root 'scripts\_daemons\persona_queue_poller.py'

$pyw = 'C:\Users\chami\AppData\Local\Programs\Python\Python312\pythonw.exe'
if (-not (Test-Path $pyw)) {
  $cmd = (Get-Command pythonw.exe -ErrorAction SilentlyContinue)
  if ($cmd) { $pyw = $cmd.Source } else { throw 'pythonw.exe not found' }
}
if (-not (Test-Path $script)) { throw "persona_queue_poller.py not found: $script" }

# every scheduled task goes through the gate so it can never pop a console window
# (aegis-gl 2026-08-30 / see scripts\_daemons\hidden_task.ps1)
$go5Here = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Definition }
. (Join-Path $go5Here 'hidden_task.ps1')
$action  = New-Go5HiddenAction -Execute $pyw -Argument ('"' + $script + '"') -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 1) -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 5)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Description 'go5-maker: drains persona/queue.jsonl on R2 into persona_avatars.json (aegis-gl)' -Force | Out-Null
Write-Host ("Registered scheduled task: {0} (every 1 min, pythonw hidden)" -f $TaskName)
