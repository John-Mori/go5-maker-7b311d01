# panic_stop.ps1 - RELIABLE full-stop for the whole orchestration fleet (2026-07-20, O1).
# Purpose: give a single command that stops EVERYTHING, so the last resort is never an OS
#   reboot again (改善書 P0-3 / Chami had to reboot 4x on 2026-07-19 because closing the
#   desktop app did not stop background work).
# ASCII-only (PS 5.1 reads no-BOM as ANSI codepage; non-ASCII corrupts parsing). JP notes -> README.
#
# What it does (in order):
#   1. Disable the 3 auto-RESTART scheduled tasks (else the supervisor rebuilds the fleet in <=10min):
#        go5_daemons_hidden (supervisor)  /  go5_lab_revive (Lab respawn)  /  go5_deadman_check
#   2. Kill every resident daemon python process (the 7 supervised + keeper's 9 dept_daemon + waiters).
#   3. (-IncludeWorkers) also kill daemon-spawned Claude workers (claude.exe with '--print' in cmdline;
#        the interactive desktop app does NOT use --print, so this does not kill your open session).
#
# Flags:
#   -DryRun          : list what WOULD be stopped, kill nothing, disable nothing. (safe to run anytime)
#   -IncludeWorkers  : also terminate '--print' Claude worker subprocesses.
#   -KeepTasks       : do NOT disable the restart tasks (soft stop; supervisor will rebuild in <=10min).
#
# Resume after a real stop:  scripts\_daemons\resume_daemons.ps1   (re-enables tasks + one supervise pass)
param(
  [switch]$DryRun,
  [switch]$IncludeWorkers,
  [switch]$KeepTasks
)
$ErrorActionPreference = 'SilentlyContinue'
$root   = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$suplog = Join-Path $root 'local\_daemons_supervisor.log'
function Write-SupLog($m){ $ts=Get-Date -Format 'yyyy-MM-dd HH:mm:ss'; try{Add-Content -LiteralPath $suplog -Value "$ts $m" -Encoding UTF8}catch{} }

# --- the fleet: every python script that is a resident daemon or session waiter ---
$daemonScripts = @(
  'absence_watchdog.py','local_responder.py','gemini_responder.py','office_daily.py',
  'claude_responder.py','daemon_keeper.py','discord_gateway.py','dept_daemon.py','inbox_waiter.py'
)
$restartTasks = @('go5_daemons_hidden','go5_lab_revive','go5_deadman_check')

$tag = if ($DryRun) { '[DRY-RUN] ' } else { '' }
Write-Host ("{0}panic_stop: scanning fleet..." -f $tag)

# 1) restart tasks
if (-not $KeepTasks) {
  foreach ($t in $restartTasks) {
    $st = Get-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue
    if ($null -eq $st) { Write-Host ("  task {0}: not found (skip)" -f $t); continue }
    if ($DryRun) { Write-Host ("  task {0}: WOULD disable (now={1})" -f $t, $st.State) }
    else {
      Disable-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue | Out-Null
      Write-Host ("  task {0}: disabled" -f $t)
      Write-SupLog ("panic_stop: disabled task {0}" -f $t)
    }
  }
} else {
  Write-Host "  (-KeepTasks: restart tasks left enabled; supervisor will rebuild fleet within ~10min)"
}

# 2) daemon python processes
$allPy = @(Get-CimInstance Win32_Process -Filter "Name='python.exe'")
$killed = 0
foreach ($sc in $daemonScripts) {
  $procs = @($allPy | Where-Object { $_.CommandLine -and ($_.CommandLine -like ('*' + $sc + '*')) })
  foreach ($p in $procs) {
    if ($DryRun) { Write-Host ("  py {0}: WOULD kill pid {1}" -f $sc, $p.ProcessId) }
    else {
      Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
      Write-Host ("  py {0}: killed pid {1}" -f $sc, $p.ProcessId)
      $killed++
    }
  }
}

# 3) optional: daemon-spawned Claude workers (identified by --print; interactive app never uses it)
$wkilled = 0
if ($IncludeWorkers) {
  $allClaude = @(Get-CimInstance Win32_Process -Filter "Name='claude.exe'")
  $workers = @($allClaude | Where-Object { $_.CommandLine -and ($_.CommandLine -match '--print|-p\b') })
  foreach ($p in $workers) {
    if ($DryRun) { Write-Host ("  worker claude --print: WOULD kill pid {0}" -f $p.ProcessId) }
    else {
      Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
      Write-Host ("  worker claude --print: killed pid {0}" -f $p.ProcessId)
      $wkilled++
    }
  }
  if ($workers.Count -eq 0) { Write-Host "  (no '--print' Claude workers found)" }
} else {
  Write-Host "  (-IncludeWorkers not set: Claude worker subprocesses left running)"
}

if ($DryRun) {
  Write-Host "[DRY-RUN] nothing was stopped. Re-run without -DryRun to actually stop."
} else {
  Write-SupLog ("panic_stop: killed {0} daemon proc(s), {1} worker(s), tasks_disabled={2}" -f $killed, $wkilled, (-not $KeepTasks))
  Write-Host ("panic_stop: DONE. daemons killed={0}, workers killed={1}." -f $killed, $wkilled)
  if (-not $KeepTasks) { Write-Host "Restart tasks are DISABLED. To bring everything back: scripts\_daemons\resume_daemons.ps1" }
}
