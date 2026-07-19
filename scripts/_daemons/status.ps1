# status.ps1 - read-only snapshot of the whole orchestration fleet (2026-07-20, O1).
# Answers "what is running right now?" at a glance. Kills/changes nothing.
# ASCII-only (PS 5.1 codepage safety).
$ErrorActionPreference = 'SilentlyContinue'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)

Write-Host "=== ORCHESTRATION FLEET STATUS ==="
Write-Host ("time: {0}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'))

# expected fleet (script -> human role). Keep in sync with supervise_daemons.ps1 (O2: generate from registry).
$fleet = [ordered]@{
  'discord_gateway.py' = 'gateway (Discord -> queue)'
  'daemon_keeper.py'   = 'keeper (guards 9 dept daemons)'
  'dept_daemon.py'     = 'dept character daemons (expect 9)'
  'absence_watchdog.py'= 'watchdog (stalls/DLQ)'
  'local_responder.py' = 'local qwen responder'
  'gemini_responder.py'= 'gemini responder'
  'claude_responder.py'= 'claude fallback responder'
  'office_daily.py'    = 'office daily'
  'inbox_waiter.py'    = 'session waiters (chime)'
}
$allPy = @(Get-CimInstance Win32_Process -Filter "Name='python.exe'")
Write-Host ""
Write-Host "-- daemons (python) --"
foreach ($sc in $fleet.Keys) {
  $procs = @($allPy | Where-Object { $_.CommandLine -and ($_.CommandLine -like ('*' + $sc + '*')) })
  $pids = ($procs | ForEach-Object { $_.ProcessId }) -join ','
  $mark = if ($procs.Count -ge 1) { 'OK ' } else { 'DOWN' }
  Write-Host ("  [{0}] {1,-22} x{2,-2} {3}  ({4})" -f $mark, $sc, $procs.Count, $pids, $fleet[$sc])
}

# Claude workers (daemon-spawned, --print)
$allClaude = @(Get-CimInstance Win32_Process -Filter "Name='claude.exe'")
$workers = @($allClaude | Where-Object { $_.CommandLine -and ($_.CommandLine -match '--print|-p\b') })
Write-Host ("  [{0}] {1,-22} x{2}" -f 'INFO', 'claude --print workers', $workers.Count)

Write-Host ""
Write-Host "-- restart tasks --"
foreach ($t in @('go5_daemons_hidden','go5_lab_revive','go5_deadman_check')) {
  $st = Get-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue
  $state = if ($null -eq $st) { 'MISSING' } else { $st.State.ToString() }
  Write-Host ("  {0,-22} {1}" -f $t, $state)
}

# gateway pulse freshness (stuck-loop indicator)
$gwPulse = Join-Path $root 'local\queue\_gateway_pulse.txt'
Write-Host ""
Write-Host "-- health --"
if (Test-Path -LiteralPath $gwPulse) {
  $age = [int]((Get-Date) - (Get-Item -LiteralPath $gwPulse).LastWriteTime).TotalSeconds
  $pmark = if ($age -le 180) { 'OK' } else { 'STALE' }
  Write-Host ("  gateway pulse: {0}s ago [{1}]  (stale > 180s = event loop stuck)" -f $age, $pmark)
} else {
  Write-Host "  gateway pulse: (no pulse file)"
}
$suplog = Join-Path $root 'local\_daemons_supervisor.log'
if (Test-Path -LiteralPath $suplog) {
  $age = [int]((Get-Date) - (Get-Item -LiteralPath $suplog).LastWriteTime).TotalSeconds
  Write-Host ("  supervisor log: {0}s ago (supervisor runs every ~600s)" -f $age)
}

# queue depth (best-effort; needs python)
$db = Join-Path $root 'local\queue\inbox.db'
if (Test-Path -LiteralPath $db) {
  $py = @'
import sqlite3,sys,time
try:
    c=sqlite3.connect("file:%s?mode=ro"%sys.argv[1],uri=True,timeout=3)
    def n(q):
        try: return c.execute(q).fetchone()[0]
        except Exception: return "?"
    now=time.time()
    print("  queue: pending=%s inflight=%s done=%s dead=%s"%(
        n("SELECT COUNT(*) FROM queue WHERE status='pending'"),
        n("SELECT COUNT(*) FROM queue WHERE status='inflight' OR (status='pending' AND lease_until>%f)"%now),
        n("SELECT COUNT(*) FROM queue WHERE status='done'"),
        n("SELECT COUNT(*) FROM queue WHERE status='dead'")))
except Exception as e:
    print("  queue: (read failed: %s)"%e)
'@
  $tmp = Join-Path $env:TEMP ('go5_status_{0}.py' -f $PID)
  Set-Content -LiteralPath $tmp -Value $py -Encoding UTF8
  & python $tmp $db
  Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
}
Write-Host ""
Write-Host "stop all: scripts\_daemons\panic_stop.ps1 [-IncludeWorkers]   resume: resume_daemons.ps1"
