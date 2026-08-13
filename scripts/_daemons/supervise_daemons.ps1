# supervise_daemons.ps1 - go5-maker: keep resident daemons hidden & single-instance (idempotent).
# Ensures exactly ONE hidden instance of each of: inbox_poller / absence_watchdog /
# local_responder / gemini_responder. Kills duplicates; (re)starts only what is missing.
# Hidden launch: WScript.Shell.Run(cmd, 0, False)  -> 0 = hidden window (same as sales_poll_hidden.vbs).
# NOTE: keep this file ASCII-only. PowerShell 5.1 reads a no-BOM file as the system ANSI
#       codepage; non-ASCII here corrupts parsing. Japanese notes live in README.md (not executed).
$ErrorActionPreference = 'SilentlyContinue'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$suplog = Join-Path $root 'local\_daemons_supervisor.log'

function Write-SupLog($m) {
  $ts = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
  try { Add-Content -LiteralPath $suplog -Value "$ts $m" -Encoding UTF8 } catch {}
}

$daemons = @(
  # inbox_poller RETIRED from supervision (2026-07-19 cutover complete: Gateway+LeaseQueue is
  #   the delivery path). Kept commented for instant rollback (uncomment + run this script).
  # @{ Name='inbox_poller';     File='inbox_poller.py';     Rel='scripts\discord\inbox_poller.py';     LogRel='local\discord_poller.log' },
  @{ Name='absence_watchdog'; File='absence_watchdog.py'; Rel='scripts\discord\absence_watchdog.py'; LogRel='local\discord_watchdog.log' },
  @{ Name='local_responder';  File='local_responder.py';  Rel='scripts\llm\local_responder.py';      LogRel='local\llm\responder_console.log' },
  @{ Name='gemini_responder'; File='gemini_responder.py'; Rel='scripts\llm\gemini_responder.py';     LogRel='local\llm\gemini_responder_console.log' },
  @{ Name='office_daily';     File='office_daily.py';     Rel='scripts\office\office_daily.py';      LogRel='local\office\_daily.log' },
  # claude_responder (2026-07-17): while the Lab session is dead, process the main box with
  #   `claude --print` so Discord still gets replies when every session is down (root fix for
  #   INC-98). Stays silent when the Lab is alive (lab_alive guard). Needs local\cli_auth_token.txt.
  @{ Name='claude_responder'; File='claude_responder.py'; Rel='scripts\llm\claude_responder.py';     LogRel='local\llm\claude_responder_console.log' },
  # daemon_keeper (2026-07-18, R0): keeps per-department character daemons (dept_daemon.py) alive
  #   with exponential backoff + circuit breaker. Departments never go unmanned (Chami directive).
  #   Two layers: keeper restarts daemons in seconds; this supervisor restarts the keeper in <=10min.
  @{ Name='daemon_keeper';    File='daemon_keeper.py';    Rel='scripts\_daemons\daemon_keeper.py';   LogRel='local\_daemon_keeper.log' },
  # discord_gateway (2026-07-19, cutover): real-time Gateway -> LeaseQueue producer. Runs alongside
  #   the pigeon during pilot (GO5_POLLER_SKIP_DEPTS decides which depts are queue-only). Env vars
  #   GO5_GATEWAY_JOBS / GO5_GATEWAY_JOBS_DEPTS / GO5_POLLER_SKIP_DEPTS are USER-level env
  #   (set via [Environment]::SetEnvironmentVariable) so schtasks-spawned instances inherit them.
  @{ Name='discord_gateway';  File='discord_gateway.py';  Rel='scripts\queue\discord_gateway.py';    LogRel='local\queue\_gateway_console.log' }
)

# gateway liveness (2026-07-19 INC): TCP:443 can stay ESTABLISHED while discord.py's event
#   loop silently stalls (observed: 2h41m with zero message intake, process healthy per OS).
#   "process exists" alone (the check below) cannot see this. job_pulse touches this file
#   every 45s from inside the event loop itself - staleness here means the loop is stuck,
#   not just that Discord has been quiet.
$gwPulse = Join-Path $root 'local\queue\_gateway_pulse.txt'
$gwPulseStaleSec = 180

$sh = New-Object -ComObject WScript.Shell
$allPy = @(Get-CimInstance Win32_Process -Filter "Name='python.exe'")

# --- code version watch (C-042, added 2026-08-13 by aegis-gl) ---------------------------
# Liveness alone cannot see "fixed but not loaded": a daemon reads its code once at start,
# so a process older than its files keeps running the old code forever. Measured (HQ msg
# 1537346679299112960): the dead-letter stale alarm shipped 8/12 02:51 never fired because
# the running absence_watchdog had started 8/11 23:36 and stayed up 13h -> a 12.3h silence.
# daemon_code_version.py reports, per daemon, a sha1 over its transitive local import closure
# (function-level imports included: resolved once at start, then cached in sys.modules).
# The VERSION IS THE CONTENT HASH, not mtime: measured 2026-08-13, a parallel session's git
# operation (pull --rebase --autostash) rewrote the worktree and pushed all 7 daemons to the
# same mtime second - an mtime rule would have restarted every daemon on every git command.
# This script records the hash it launched each daemon with, under local\_daemon_codever\,
# so the comparison is against what that pid actually loaded. For a pid that predates this
# mechanism there is no record, so the fallback is the last COMMIT touching its closure vs
# the process start (that is the 15-day-stale case measured here: 5 daemons up since 7/29).
# Two floors, same as daemon_keeper: 90s settle (never reload mid-edit) and 600s minimum
# process age (2026-07-29: hours of continuous edits restarted daemons every few minutes and
# ate the deliveries). At most $codeMaxReloads per pass, so one shared module (leasequeue.py
# is read by 4 of these) cannot restart everything at once; the rest are logged, not dropped.
# Fail-open: if python or the script is unavailable, this pass falls back to liveness only.
$codeDebounceSec = 90
$codeMinAgeSec  = 600
$codeMaxReloads = 2
$codeReloads = 0
$codeVerDir = Join-Path $root 'local\_daemon_codever'
if (-not (Test-Path -LiteralPath $codeVerDir)) { New-Item -ItemType Directory -Path $codeVerDir | Out-Null }
$codeVer = @{}
try {
  $verLines = & python (Join-Path $root 'scripts\_daemons\daemon_code_version.py')
  foreach ($ln in $verLines) {
    $parts = "$ln".Split("`t")
    if ($parts.Count -ge 5) {
      $codeVer[$parts[0]] = @{ Epoch = [double]$parts[1]; File = $parts[2]; Hash = $parts[3]
                               Commit = [double]$parts[4] }
    }
  }
} catch { Write-SupLog ("code version: error ({0})" -f $_.Exception.Message) }
if ($codeVer.Count -eq 0) { Write-SupLog "code version: no data - liveness only this pass" }
$nowEpoch = [DateTimeOffset]::Now.ToUnixTimeSeconds()

foreach ($d in $daemons) {
  $procs = @($allPy | Where-Object { $_.CommandLine -and ($_.CommandLine -like ('*' + $d.File + '*')) })
  if ($d.Name -eq 'discord_gateway' -and $procs.Count -eq 1 -and (Test-Path -LiteralPath $gwPulse)) {
    $age = (Get-Date) - (Get-Item -LiteralPath $gwPulse).LastWriteTime
    if ($age.TotalSeconds -gt $gwPulseStaleSec) {
      Write-SupLog ("{0}: STALE PULSE ({1}s, event loop likely hung) - killing pid {2}" -f $d.Name, [int]$age.TotalSeconds, $procs[0].ProcessId)
      Stop-Process -Id $procs[0].ProcessId -Force
      $procs = @()  # fall through to the missing-process restart path below
    }
  }
  $verFile = Join-Path $codeVerDir ($d.Name + '.txt')
  if ($procs.Count -eq 1 -and $codeVer.ContainsKey($d.Name)) {
    $cv = $codeVer[$d.Name]
    $startEpoch = ([DateTimeOffset]$procs[0].CreationDate).ToUnixTimeSeconds()
    $loaded = ''
    if (Test-Path -LiteralPath $verFile) { $loaded = (Get-Content -LiteralPath $verFile -Raw).Trim() }
    # No record = this pid predates the mechanism, so the hash cannot say what it loaded.
    # Fall back to the last COMMIT that touched its closure: content-bound, so a worktree
    # rewrite does not move it. Newer than the process start -> it is running old code.
    # Otherwise adopt the current hash without a restart (availability over freshness);
    # the next real change moves the hash and reloads it normally.
    $stale = $false
    if ($loaded -eq '') {
      if ($cv.Commit -gt 0 -and $cv.Commit -gt $startEpoch) {
        $stale = $true
        $why = ('no record; closure committed {0}s after this pid started' -f [int]($cv.Commit - $startEpoch))
      } else {
        Set-Content -LiteralPath $verFile -Value $cv.Hash -Encoding ASCII
        Write-SupLog ("{0}: adopted running pid {1} at code version {2}" -f $d.Name, $procs[0].ProcessId, $cv.Hash)
      }
    } elseif ($loaded -ne $cv.Hash) {
      $stale = $true
      $why = ('loaded {0}, now {1}, newest {2}' -f $loaded, $cv.Hash, $cv.File)
    }
    if ($stale -and ($nowEpoch - $cv.Epoch) -ge $codeDebounceSec `
        -and ($nowEpoch - $startEpoch) -ge $codeMinAgeSec) {
      if ($codeReloads -ge $codeMaxReloads) {
        Write-SupLog ("{0}: STALE CODE ({1}) - deferred to next pass (cap {2}/pass)" -f $d.Name, $why, $codeMaxReloads)
      } else {
        Write-SupLog ("{0}: STALE CODE ({1}) - reload pid {2} (up {3}s)" -f $d.Name, $why, $procs[0].ProcessId, ($nowEpoch - $startEpoch))
        Stop-Process -Id $procs[0].ProcessId -Force
        $procs = @()  # fall through to the restart path below
        $codeReloads++
      }
    }
  }
  if ($procs.Count -eq 1) {
    Write-SupLog ("{0}: ok (1 running, pid {1})" -f $d.Name, $procs[0].ProcessId)
    continue
  }
  if ($procs.Count -gt 1) {
    foreach ($p in $procs) { Stop-Process -Id $p.ProcessId -Force }
    Write-SupLog ("{0}: deduped ({1} instances -> restart 1)" -f $d.Name, $procs.Count)
  }
  $logAbs = $root + '\' + $d.LogRel
  $cmd = 'cmd /c cd /d "' + $root + '" && python "' + $d.Rel + '" >> "' + $logAbs + '" 2>&1'
  $sh.Run($cmd, 0, $false) | Out-Null
  # Record the code version this instance was launched with. This file - not mtime - is what
  # the next pass compares against, so "fixed but not loaded" cannot hide behind a git touch.
  if ($codeVer.ContainsKey($d.Name)) {
    Set-Content -LiteralPath $verFile -Value $codeVer[$d.Name].Hash -Encoding ASCII
  }
  Write-SupLog ("{0}: started hidden" -f $d.Name)
}
# boot report (O1 P0-7): fire-and-forget, hidden, non-blocking. Idempotent - boot_report.py posts
#   only once per boot (state file). Fires within one supervise cycle (<=10min) after any reboot,
#   so an unattended Windows Update restart never goes unnoticed again (kaizen doc P0-7).
$brCmd = 'cmd /c cd /d "' + $root + '" && python "scripts\_daemons\boot_report.py" --once >> "' + $root + '\local\_boot_report.log" 2>&1'
$sh.Run($brCmd, 0, $false) | Out-Null

Write-SupLog "supervise pass done"
