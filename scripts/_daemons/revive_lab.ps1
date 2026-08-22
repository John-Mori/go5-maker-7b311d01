# revive_lab.ps1 - go5-maker: revive the Lab (kenkyushitsu) Claude session after logon / crash.
#
# WHY: every other line (Discord chime, daemons) only DELIVERS. Something must ANSWER.
#   The Lab session is the single always-open catch-all. If the PC reboots (Windows Update,
#   power loss) or the session dies while Chami is away, nothing answers in-character until he
#   opens it by hand - which he cannot do remotely. This restores it automatically.
#   (Availability itself is already floored by claude_responder.py's unmanned stand-in; this brings
#    back a FULL character-capable Lab, which is strictly better than mechanical acks.)
#
# LIVENESS DETECTION (rewritten 2026-07-18, INC-104):
#   The old check "any claude.exe process alive -> ok" NEVER fired: ~25 unrelated claude.exe
#   processes (desktop app, subagents, `claude --print`) are always alive, so it always logged
#   "ok" and never revived a truly-dead Lab. Now we shell out to scripts/llm/presence.py --check,
#   the SINGLE source of truth for Lab liveness (2-signal: readiness OR liveness+HARD_CAP). PS
#   never re-implements that logic -> no drift (drift between responders is exactly what caused
#   INC-104).
#
# FRESH SPAWN, NOT RESUME (rewritten 2026-07-18, INC-104):
#   The old code did `claude -r <hardcoded labId>`. That id (46c7212b...) was stale - it matched
#   no current session - so a fire would have resumed a dead/wrong session. Session ids are also
#   no longer reliably discoverable: the multi-session env writes many concurrent *.jsonl and even
#   the Lab cannot identify its own id by "newest file". So we drop resume entirely and spawn a
#   FRESH Lab with a self-contained boot prompt, mirroring the proven open_dept_window.ps1 (the
#   boot prompt re-arms the waiter and drains the inbox on its own - it does not need prior context).
#
# IDEMPOTENT / no pileup:
#   - if presence says the Lab is alive -> do nothing.
#   - if a `inbox_waiter --name main` process exists -> a Lab window is already booting -> skip.
#   - cooldown: never respawn more than once per 15 min (guards a spawn that fails to arm a waiter).
#
# NOTE: keep this file ASCII-only. PowerShell 5.1 reads a no-BOM file as the system ANSI
#       codepage; non-ASCII here corrupts parsing. Japanese notes live in README.md / the prompt.
$ErrorActionPreference = 'SilentlyContinue'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$log  = Join-Path $root 'local\_lab_revive.log'
$stateFile = Join-Path $root 'local\_lab_revive_state.txt'  # epoch seconds of last spawn (cooldown)
$cooldownSec = 15 * 60

function Write-Log($m) {
  $ts = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
  try { Add-Content -LiteralPath $log -Value "$ts $m" -Encoding UTF8 } catch {}
}

# ===========================================================================
# JUDGMENT LIBRARY (2026-08-22, aegis-gl. HQ msg 1540735472282767440)
#
#   WHY THE JUDGMENT MOVED INTO FUNCTIONS: it used to be inline, so the ONLY way it could
#   ever be checked was by reading it - and it was wrong. On 2026-08-22 this script killed
#   the live commander TWICE (22:32:11 = session 0ebedfa2, whose transcript shows 5h27m of
#   real work; 23:02:11 = the next window, 30 min old). Both times the reason logged was
#   "claude.exe alive but 0 CPU over 5s - deaf zombie". Daily count of that line:
#   08-13:1 / 08-14:5 / 08-15:2 / 08-22:3.
#
#   WHAT WAS BROKEN (C-041: one observation used as a state):
#     - ONE 5-second CPU sample decided life or death. The same window measured cpu+31ms at
#       22:52 (spared) and cpu+0ms at 23:02 (killed). An idle-but-live TUI and a wedged one
#       burn the same trickle, so CPU cannot tell them apart - and the sparing side required
#       18 consecutive passes while the KILLING side needed exactly one. Backwards: a pileup
#       is slow, visible and recoverable; killing the commander is silent and is not.
#
#   WHAT REPLACES IT:
#     (A) the killing side now needs LAB_ZOMBIE_MAX consecutive passes of 0 CPU on the SAME
#         shell pid, with presence dead every time (we only get here when presence says dead).
#     (B) a proof of life that is not CPU: the window's own transcript. A window that became
#         the Lab kept writing to ~/.claude/projects/<slug>/<sid>.jsonl for minutes or hours
#         after it opened (0ebedfa2: created 16:42:16, last write 22:09:46, 885KB); a corpse
#         writes the boot burst and stops. The transcript is matched to the window by
#         creation time vs the claude.exe process start (measured: 3 seconds apart).
#     (C) the pre-warm now needs a POSITIVE proof of success (.credentials.json advanced),
#         because "did not match my 5 failure words" logged ok for 175 windows that had died
#         saying "Credit balance is too low".
#
#   Dot-source with LAB_REVIVE_LIB=1 to load these functions WITHOUT running a revival:
#   scripts\_daemons\test_revive_lab.ps1 does exactly that and runs the real judgment and the
#   real branching with fake inputs, with only Stop-Process replaced.
# ===========================================================================
$script:LAB_ZOMBIE_MAX     = 3     # consecutive 0-CPU passes before a shell may be reaped (~30 min at 10 min/pass)
$script:LAB_SPARE_MAX      = 18    # consecutive spares of a CPU-burning shell before we call it stuck (~3 h)
$script:LAB_WORKED_MIN_SEC = 180   # transcript span that proves the window became a working Lab
$script:LAB_STALE_HOURS    = 6     # a worked window silent longer than this stops counting as proof
$script:LAB_MATCH_SEC      = 180   # transcript creation vs claude.exe start, to pair them
$script:LAB_PREWARM_FAIL   = 'Please run /login|Not logged in|401|Invalid API key|authentication_error|Credit balance'

function Get-LabWindowActivity {
  # Pair a claude.exe with its transcript by start time, and report what that transcript proves.
  # Returns @{Matched; Worked; LastWrite; SpanSec}. Unknown -> Matched=$false (never a verdict).
  param($Files, $StartTime, [int]$MatchSec = -1)
  if ($MatchSec -lt 0) { $MatchSec = $script:LAB_MATCH_SEC }
  $res = @{ Matched = $false; Worked = $false; LastWrite = $null; SpanSec = 0 }
  if ($null -eq $Files -or $null -eq $StartTime) { return $res }
  $best = $null
  foreach ($f in $Files) {
    if ($null -eq $f.CreationTime) { continue }
    $d = [math]::Abs((New-TimeSpan -Start $StartTime -End $f.CreationTime).TotalSeconds)
    if ($d -le $MatchSec) {
      if ($null -eq $best -or $f.LastWriteTime -gt $best.LastWriteTime) { $best = $f }
    }
  }
  if ($null -eq $best) { return $res }
  $res.Matched   = $true
  $res.LastWrite = $best.LastWriteTime
  $res.SpanSec   = [int](New-TimeSpan -Start $best.CreationTime -End $best.LastWriteTime).TotalSeconds
  $res.Worked    = ($res.SpanSec -ge $script:LAB_WORKED_MIN_SEC)
  return $res
}

function Get-LabShellVerdict {
  # THE decision. Action = reap | spare | watch. Busy = positively proven alive (blocks a spawn).
  param(
    [bool]$HasClaudeChild,
    [bool]$CpuMeasured,
    [int]$CpuMs,
    $Activity,
    $Now,
    [int]$ZombieCount = 0,
    [int]$SpareCount = 0
  )
  $v = @{ Action = 'reap'; Reason = 'corpse'; Busy = $false; Zombie = 0; Spare = 0 }
  if (-not $HasClaudeChild) { return $v }        # no claude.exe under the shell = confirmed corpse
  # (B) proof of life that is not CPU, and it outranks CPU because it is not a single sample.
  if ($Activity -and $Activity.Matched -and $Activity.Worked) {
    $ageH = 9999
    if ($Activity.LastWrite -and $Now) { $ageH = (New-TimeSpan -Start $Activity.LastWrite -End $Now).TotalHours }
    if ($ageH -lt $script:LAB_STALE_HOURS) {
      $v.Action = 'spare'; $v.Reason = 'transcript'; $v.Busy = $true; return $v
    }
  }
  if (-not $CpuMeasured) { $v.Action = 'spare'; $v.Reason = 'unmeasured'; return $v }  # fail-open, never kill on an unknown
  if ($CpuMs -gt 0) {
    $n = $SpareCount + 1
    if ($n -gt $script:LAB_SPARE_MAX) { $v.Action = 'reap'; $v.Reason = 'stuck'; $v.Spare = $n; return $v }
    $v.Action = 'spare'; $v.Reason = 'cpu'; $v.Busy = $true; $v.Spare = $n; return $v
  }
  # (A) 0 CPU over one 5s sample is ONE OBSERVATION, not a state. Count it; kill only on a streak.
  $z = $ZombieCount + 1
  if ($z -ge $script:LAB_ZOMBIE_MAX) { $v.Action = 'reap'; $v.Reason = 'zombie'; $v.Zombie = $z; return $v }
  $v.Action = 'watch'; $v.Reason = 'zombie-suspect'; $v.Zombie = $z; return $v
}

function Invoke-LabReapPass {
  # Real branching. Killer is injectable so a test can watch what WOULD have been killed.
  param($Candidates, $Now, $State = $null, $Killer = $null, $Logger = $null)
  if ($null -eq $Killer) { $Killer = { param($p) Stop-Process -Id $p -Force -ErrorAction SilentlyContinue } }
  if ($null -eq $Logger) { $Logger = { param($m) Write-Log $m } }
  if ($null -eq $State)  { $State  = @{} }
  $out = @{ Reaped = 0; Spared = 0; Watched = 0; Busy = 0; State = @{} }
  foreach ($c in @($Candidates)) {
    $key = [string]$c.ShellPid
    $ps = 0; $pz = 0
    if ($State.ContainsKey($key)) { $ps = [int]$State[$key].Spare; $pz = [int]$State[$key].Zombie }
    $kids       = @($c.Kids)
    $claudeKids = @($kids | Where-Object { $_.Name -eq 'claude.exe' })
    $desc = ''; $cpuMs = 0; $unmeasured = 0; $act = $null
    foreach ($ck in $claudeKids) {
      if ($ck.CpuMeasured) {
        if ([int]$ck.CpuMs -gt $cpuMs) { $cpuMs = [int]$ck.CpuMs }
        $desc += ('claude pid={0} ws={1}MB cpu+{2}ms; ' -f $ck.Pid, $ck.WorkingSetMB, $ck.CpuMs)
      } else {
        $unmeasured++
        $desc += ('claude pid={0} ws={1}MB cpu=UNMEASURED; ' -f $ck.Pid, $ck.WorkingSetMB)
      }
      if ($ck.Activity -and $ck.Activity.Matched) {
        if ($null -eq $act -or $ck.Activity.LastWrite -gt $act.LastWrite) { $act = $ck.Activity }
      }
    }
    if ($act -and $act.Matched) { $desc += ('transcript span={0}s last={1}; ' -f $act.SpanSec, $act.LastWrite) }
    $v = Get-LabShellVerdict -HasClaudeChild ($claudeKids.Count -gt 0) `
                             -CpuMeasured ($claudeKids.Count -gt 0 -and $unmeasured -eq 0) `
                             -CpuMs $cpuMs -Activity $act -Now $Now -ZombieCount $pz -SpareCount $ps
    if ($v.Action -eq 'spare') {
      if ($v.Reason -eq 'transcript') {
        & $Logger ('lab: cmd pid {0} - transcript proves this window WORKED [{1}] - NOT reaping. presence is blind, the window is not dead' -f $c.ShellPid, $desc)
      } elseif ($v.Reason -eq 'unmeasured') {
        & $Logger ('lab: cmd pid {0} - CPU unmeasurable [{1}] - NOT reaping (never kill on an unknown)' -f $c.ShellPid, $desc)
      } else {
        & $Logger ('lab: cmd pid {0} has a WORKING claude.exe [{1}] - NOT reaping (spare {2}/{3})' -f $c.ShellPid, $desc, $v.Spare, $script:LAB_SPARE_MAX)
      }
      $out.Spared++
      if ($v.Busy) { $out.Busy++ }
      $out.State[$key] = @{ Spare = $v.Spare; Zombie = 0 }
    }
    elseif ($v.Action -eq 'watch') {
      & $Logger ('lab: cmd pid {0}: 0 CPU over 5s but that is one sample [{1}] - WATCHING {2}/{3}, not reaping' -f $c.ShellPid, $desc, $v.Zombie, $script:LAB_ZOMBIE_MAX)
      $out.Watched++
      $out.State[$key] = @{ Spare = 0; Zombie = $v.Zombie }
    }
    else {
      if ($v.Reason -eq 'corpse') {
        & $Logger ('lab: cmd pid {0}: children [{1}] - no claude.exe = confirmed corpse, reaping' -f $c.ShellPid, (($kids | ForEach-Object { $_.Name }) -join ','))
      } elseif ($v.Reason -eq 'stuck') {
        & $Logger ('lab: cmd pid {0} spared {1} passes in a row and presence never recovered [{2}] - treating it as stuck, reaping' -f $c.ShellPid, $v.Spare, $desc)
      } else {
        & $Logger ('lab: cmd pid {0}: {1} consecutive passes at 0 CPU and presence never recovered [{2}] - deaf zombie, reaping' -f $c.ShellPid, $v.Zombie, $desc)
      }
      foreach ($k in $kids) { & $Killer $k.Pid }
      & $Killer $c.ShellPid
      $out.Reaped++
    }
  }
  return $out
}

function Read-LabWatchState {
  # lines: "<shellpid> <spareCount> <zombieCount>"
  param($Path)
  $st = @{}
  if (-not $Path -or -not (Test-Path -LiteralPath $Path)) { return $st }
  try {
    foreach ($line in (Get-Content -LiteralPath $Path)) {
      $p = ($line.Trim() -split '\s+')
      if ($p.Count -ge 3) { $st[[string]$p[0]] = @{ Spare = [int]$p[1]; Zombie = [int]$p[2] } }
    }
  } catch {}
  return $st
}

function Write-LabWatchState {
  param($Path, $State)
  try {
    if ($null -eq $State -or $State.Keys.Count -eq 0) {
      if (Test-Path -LiteralPath $Path) { Remove-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue }
      return
    }
    $lines = @()
    foreach ($k in $State.Keys) { $lines += ('{0} {1} {2}' -f $k, [int]$State[$k].Spare, [int]$State[$k].Zombie) }
    Set-Content -LiteralPath $Path -Value $lines -Encoding ASCII
  } catch {}
}

function Get-LabPrewarmVerdict {
  # FAILED = the probe said so. ok = .credentials.json actually advanced (positive proof).
  # unverified = output but no refresh. unknown = nothing at all. Only FAILED/unverified are bad news,
  # and none of them block the spawn (fail-open).
  param([string]$Blob, $CredsBefore, $CredsAfter)
  if ($Blob -and ($Blob -match $script:LAB_PREWARM_FAIL)) { return 'FAILED' }
  if ($CredsAfter -and (-not $CredsBefore -or $CredsAfter -gt $CredsBefore)) { return 'ok' }
  if (-not $Blob -or $Blob.Trim().Length -eq 0) { return 'unknown' }
  return 'unverified'
}

function Format-LabPrewarmLog {
  param([string]$Verdict)
  if ($Verdict -eq 'FAILED') {
    return 'lab: AUTH PRE-WARM FAILED - probe rejected (see local\_lab_revive_probe.out). The revived window will die at the same wall.'
  } elseif ($Verdict -eq 'ok') {
    return 'lab: auth pre-warm ok (.claude\.credentials.json mtime advanced) - cold TUI should authenticate'
  } elseif ($Verdict -eq 'unverified') {
    return 'lab: AUTH PRE-WARM UNVERIFIED - probe answered but .claude\.credentials.json did not advance. Not calling that ok. Spawning anyway (fail-open).'
  }
  return 'lab: auth pre-warm returned nothing - treating as unknown, spawning anyway (fail-open)'
}

if ($env:LAB_REVIVE_LIB -eq '1') { return }   # library mode: functions only, no revival

# --- 1) Is the Lab alive? Single source of truth = presence.lab_alive (exit 0 alive / 3 dead). ---
$py = 'python'
& $py (Join-Path $root 'scripts\llm\presence.py') --check 2>$null | Out-Null
$labAlive = ($LASTEXITCODE -eq 0)
if ($labAlive) {
  Write-Log 'lab: ok (presence.lab_alive)'
  # presence recovered -> whatever we were sparing or watching is vindicated, reset the counters
  # (section 2.5). Both files: the old single-pid spare file and the per-pid watch file.
  try { Remove-Item -LiteralPath (Join-Path $root 'local\_lab_revive_spare.txt') -Force -ErrorAction SilentlyContinue } catch {}
  try { Remove-Item -LiteralPath (Join-Path $root 'local\_lab_revive_watch.txt') -Force -ErrorAction SilentlyContinue } catch {}
  exit 0
}

# --- 2) Double-open guard: a main waiter means a Lab window is already booting/armed. ---
$waiter = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
  $_.Name -eq 'python.exe' -and $_.CommandLine -match 'inbox_waiter' -and $_.CommandLine -match '--name\s+main(\s|$|")'
})
if ($waiter.Count -gt 0) {
  Write-Log ('lab: dead by presence but main waiter armed (pid {0}) - window booting, skip' -f $waiter[0].ProcessId)
  exit 0
}

# --- 2.5) Reap stale revival shells (2026-08-01, aegis-gl, C-027). ---
#   THE PILEUP BUG: the guards above only RATE-LIMIT spawns; nothing ever REAPED the failures.
#   A script-launched `claude` in this env does not become a live consumer (it never arms a
#   `inbox_waiter --name main`, so presence.py reports the Lab dead forever). So this script fired
#   every 20 min, each time leaving a `cmd /k -> claude.exe` corpse that never exits (cmd /k keeps
#   the window, claude sits as a ~35MB zombie). Measured 2026-08-01: 100 such corpses / ~4GB RAM.
#   Since we only reach here when the Lab is DEAD by presence AND no main waiter is armed, any
#   existing revival cmd window is a confirmed corpse (it never became the live Lab). Close them.
#   Age guard (> cooldown) makes it impossible to touch a window that is still booting this cycle.
#   *** 2026-08-13, aegis-gl: THE PREMISE ABOVE EXPIRED ON 2026-08-06 - AUTOPSY + GUARD ADDED ***
#   "any existing revival cmd window is a confirmed corpse (it never became the live Lab)" was
#   true only while a script-launched claude could not log in. The AUTH PRE-WARM fix in section
#   5.5 (2026-08-06) removed exactly that, so revived windows DO become the live Lab now - and
#   this block kept the old licence to kill. Measured on 2026-08-13 for the 08:42:07 reap:
#     - the Lab window spawned 04:02:09 (transcript 7dbacd77-...jsonl, first entry 04:02:10)
#     - its last assistant/tool line is 08:10:41, and it was STILL ALIVE at 08:31:01 (the
#       harness wrote a `queue-operation: enqueue` line at that second) = mid-turn, not dead
#     - presence still called it dead, because lab_alive() has degenerated to readiness-only:
#       the liveness pulse local/llm/lab_tool_pulse.txt has not moved since 2026-07-20 19:22
#       (23.9 days), so the "busy, ear paused" branch of presence.py can never fire. During a
#       long turn no `inbox_waiter --name main` exists either, so section 2's guard misses too.
#   => presence dead + no waiter + a BUSY claude.exe = this loop kills the living commander.
#   FIX (two parts, both here):
#     (a) AUTOPSY: log what the shell's children actually were. This line is written only when a
#         reap happens, so it can never become background noise.
#     (b) FRATRICIDE GUARD: measure CPU over 5s. A working claude.exe burns CPU; the deaf
#         zombies of 2026-08-01 (stuck on "your message seems cut off") burn none. Only reap
#         when claude.exe is absent or provably idle. If the measurement itself fails we SPARE
#         the window: a pileup is slow, visible and recoverable, killing the commander is
#         silent and is the accident this whole file exists to prevent.
$revCmds = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
  $_.Name -eq 'cmd.exe' -and
  $_.CommandLine -match '\.local\\bin\\claude\.exe' -and
  $_.CommandLine -match 'SougouStartFolder\\5SecMovieMaker'
})
#   Newest first.
#   *** 2026-08-22, aegis-gl: THE "OLDER = SUPERSEDED, REAP WITHOUT CEREMONY" RULE IS GONE ***
#   It used to reap every shell but the newest with no life check at all. With the streak
#   counter below that rule would have quietly defeated the whole fix: a window we chose not to
#   kill this pass becomes "an older duplicate" the moment we spawn the next one, and dies
#   anyway 10 minutes later. Every candidate now goes through the SAME verdict; a corpse still
#   dies, it just takes LAB_ZOMBIE_MAX passes instead of one. Pileup is bounded by that
#   (cooldown 15 min per spawn vs ~30 min to reap) and it is the direction we chose on purpose:
#   a pileup is slow, visible and recoverable - killing the commander is silent and is not.
$aged = @($revCmds | Where-Object {
  $null -ne $_.CreationDate -and ((Get-Date) - $_.CreationDate).TotalSeconds -ge $cooldownSec
} | Sort-Object CreationDate -Descending)
# One CPU snapshot pair for ALL claude.exe, so the 5s cost is paid once no matter how many
# shells are candidates (and zero times when there is nothing to reap).
$cpu1 = @{}; $cpu2 = @{}
if ($aged.Count -gt 0) {
  try {
    Get-CimInstance Win32_Process -Filter "Name='claude.exe'" -ErrorAction Stop | ForEach-Object {
      $cpu1[[string]$_.ProcessId] = [int64]$_.KernelModeTime + [int64]$_.UserModeTime
    }
    Start-Sleep -Seconds 5
    Get-CimInstance Win32_Process -Filter "Name='claude.exe'" -ErrorAction Stop | ForEach-Object {
      $cpu2[[string]$_.ProcessId] = [int64]$_.KernelModeTime + [int64]$_.UserModeTime
    }
  } catch {
    Write-Log ('lab: CPU probe failed ({0}) - sparing every candidate shell this pass' -f $_.Exception.Message)
    $cpu1 = $null
  }
}
#   Transcripts, for the non-CPU proof of life (B). One directory listing per pass, only when
#   there is something to judge (measured 2026-08-22: 907 files, 71 ms).
$transcripts = @()
if ($aged.Count -gt 0) {
  $projDir = Join-Path $env:USERPROFILE ('.claude\projects\' + ($root -replace '[^A-Za-z0-9]', '-'))
  try {
    $transcripts = @(Get-ChildItem -LiteralPath $projDir -Filter *.jsonl -ErrorAction Stop |
                     Select-Object CreationTime, LastWriteTime, Name)
  } catch { $transcripts = @() }   # unknown -> Get-LabWindowActivity returns Matched=$false
}
#   Build the candidates (facts only - no judgment here), then let the library judge and act.
$nowDt = Get-Date
$candidates = @()
foreach ($rc in $aged) {
  $kids = $null
  try {
    $kids = @(Get-CimInstance Win32_Process -Filter ("ParentProcessId={0}" -f $rc.ProcessId) -ErrorAction Stop)
  } catch {
    Write-Log ('lab: autopsy failed for cmd pid {0} ({1}) - sparing it' -f $rc.ProcessId, $_.Exception.Message)
    continue
  }
  $kidRows = @()
  foreach ($ck in $kids) {
    $k = [string]$ck.ProcessId
    $measured = ($null -ne $cpu1 -and $cpu1.ContainsKey($k) -and $cpu2.ContainsKey($k))
    $ms = 0
    if ($measured) { $ms = [int]((($cpu2[$k] - $cpu1[$k])) / 10000) }
    $act = $null
    if ($ck.Name -eq 'claude.exe') { $act = Get-LabWindowActivity -Files $transcripts -StartTime $ck.CreationDate }
    $kidRows += @{
      Pid = $ck.ProcessId; Name = $ck.Name
      WorkingSetMB = [int]($ck.WorkingSetSize / 1MB)
      CpuMs = $ms; CpuMeasured = $measured; Activity = $act
    }
  }
  $candidates += @{ ShellPid = $rc.ProcessId; Kids = $kidRows }
}
$watchStateFile = Join-Path $root 'local\_lab_revive_watch.txt'
$pass = Invoke-LabReapPass -Candidates $candidates -Now $nowDt -State (Read-LabWatchState $watchStateFile)
Write-LabWatchState -Path $watchStateFile -State $pass.State
$reaped = $pass.Reaped
$busyShells = $pass.Busy
if ($reaped -gt 0)       { Write-Log ('lab: reaped {0} stale revival shell(s) before spawn' -f $reaped) }
if ($pass.Spared -gt 0)  { Write-Log ('lab: spared {0} shell(s) that were still working or unmeasurable' -f $pass.Spared) }
if ($pass.Watched -gt 0) { Write-Log ('lab: watching {0} shell(s) at 0 CPU - one sample is not a death certificate' -f $pass.Watched) }
# The old single-pid spare file is retired by the per-pid watch file above; drop it if it lingers.
try { Remove-Item -LiteralPath (Join-Path $root 'local\_lab_revive_spare.txt') -Force -ErrorAction SilentlyContinue } catch {}
#   And do not stack a SECOND Lab on top of one we just proved is working: two commanders in
#   one inbox is the double-answer race this fleet has fought before. Only a POSITIVE CPU
#   measurement stops the spawn ($busyShells); an unmeasurable shell still allows revival, so a
#   broken probe can never leave the Lab unrevived.
if ($busyShells -gt 0) {
  Write-Log ('lab: {0} working Lab window(s) present - presence is blind, not the Lab dead. Skipping spawn.' -f $busyShells)
  exit 0
}

# --- 3) Cooldown: do not respawn faster than every 15 min. ---
$now = [int][double]::Parse((Get-Date -UFormat %s))
$last = 0
if (Test-Path -LiteralPath $stateFile) {
  [int]::TryParse((Get-Content -LiteralPath $stateFile -Raw).Trim(), [ref]$last) | Out-Null
  if (($now - $last) -lt $cooldownSec) {
    Write-Log ('lab: dead but within cooldown ({0}s since last spawn) - skip' -f ($now - $last))
    exit 0
  }
}

# --- 3.5) Window lifetime (2026-08-12, aegis-gl). Revival works, but nothing ever recorded HOW LONG
#   a window lived before dying, so "how often / why does the Lab window die" could only be
#   hand-counted out of this log (measured by hand 2026-08-12: 70 revivals on 08-07 vs 1 on 08-12).
#   Record it where the fact is known: seconds since the previous spawn = the dead window's
#   lifetime (upper bound - death happened somewhere between the last 'ok' line and now).
#   Log only; no behaviour change, so a bad number can never block a revival.
if ($last -gt 0) {
  Write-Log ('lab: previous window lifetime {0} min (last spawn epoch {1}) - dying window, respawning' -f [int](($now - $last) / 60), $last)
}

# --- 4) Build the self-contained boot prompt (python owns the Japanese text). ---
$claude = 'C:\Users\chami\.local\bin\claude.exe'
if (-not (Test-Path -LiteralPath $claude)) { Write-Log 'lab: claude.exe not found - cannot revive'; exit 1 }
$promptFile = Join-Path $root 'local\_lab_revive_prompt.txt'
$prompt = ''
try {
  & $py (Join-Path $root 'scripts\_daemons\lab_revive_prompt.py') $promptFile | Out-Null
  if (Test-Path -LiteralPath $promptFile) {
    $prompt = (Get-Content -LiteralPath $promptFile -Raw -Encoding UTF8).Trim()
  }
} catch { Write-Log ('lab: prompt build failed: {0}' -f $_.Exception.Message) }
if (-not $prompt) { Write-Log 'lab: empty boot prompt - cannot revive safely'; exit 1 }

# --- 4.5) PROMPT TRUNCATION FIX (2026-08-04, HQ). MEASURED SYMPTOM: every revived window
#   showed only the FIRST TOKEN of the prompt and answered "your message seems cut off",
#   so the window NEVER became the Lab - which is exactly why presence stayed dead, revive
#   re-fired every cycle, and cmd corpses piled up (DEF-hq-4bbc31797b).
#   CAUSE (two walls, both here): the prompt was appended to -ArgumentList RAW.
#     (a) unquoted -> cmd splits it on the FIRST SPACE, claude gets only that token as argv[1].
#     (b) multi-line -> a cmd command line ends at the first CR/LF, so the rest is dropped anyway.
#   FIX: flatten newlines to spaces (the prompt is ~1.9KB, far under cmd's 8191 limit) and pass
#   it as ONE explicitly double-quoted element. Any inner double quote is downgraded to a
#   single quote (inert to cmd) so python can never break the quoting from the outside.
$promptArg = '"' + (($prompt -replace '"', "'") -replace '\s*\r?\n\s*', ' ') + '"'

# --- 5) Auth: a script-launched claude is NOT logged in unless we inject the OAuth token
#        (host auth is not inherited by a cold CLI). Token lives in local/cli_auth_token.txt
#        (gitignored). Set it as an ENV VAR (inherited by the child), never on the command line. ---
$tokFile = Join-Path $root 'local\cli_auth_token.txt'
if (Test-Path -LiteralPath $tokFile) {
  $env:CLAUDE_CODE_OAUTH_TOKEN = (Get-Content -LiteralPath $tokFile -Raw).Trim()
} else {
  Write-Log 'lab: WARNING - local\cli_auth_token.txt missing. Revived session may not be logged in (deaf window). Run: claude setup-token'
}

# --- 5.5) AUTH PRE-WARM (2026-08-06, aegis-gl). MEASURED SYMPTOM: every revived window died with
#   "Please run /login - API Error: 401 OAuth access token has expired" while the 30 dept_daemons
#   kept working on --print, so "the key expired" looked true but was not.
#   MEASURED FACTS (2026-08-06 02:42 JST, all run by hand):
#     (a) local\cli_auth_token.txt is VALID - api.anthropic.com/v1/messages returns 200 with it
#         (a deliberately bogus token returns 401 on the same call), and it answers pong on its
#         own inside an isolated CLAUDE_CONFIG_DIR. The key is NOT the problem.
#     (b) The CLI PREFERS %USERPROFILE%\.claude\.credentials.json over CLAUDE_CODE_OAUTH_TOKEN:
#         a bogus env token still answered pong while those host creds were fresh. So section 5's
#         premise ("a cold CLI has no host auth, inject the token") no longer holds - the cold TUI
#         reads the same host creds, and when they are stale it stops at /login WITHOUT falling
#         back to our perfectly good env token.
#     (c) .credentials.json carries an ~8h expiresAt and is refreshed only when something calls
#         the API. Every failed revive on 08-06 (01:02 / 01:22 / 01:42 / 02:02 / 02:22) sat inside
#         such an expired window; the file was refreshed at 02:40 the instant a --print ran.
#   FIX: force that refresh ourselves right before spawning, so the cold TUI reads live creds.
#   fail-open: if the probe fails we still spawn (the visible window is Chami's manual path),
#   but the log says so plainly instead of leaving a silent corpse.
#   *** 2026-08-22, aegis-gl: THE VERDICT BELOW WAS A LIE (HQ msg 1540735472282767440) ***
#   The judgment was "did not match my 5 failure words AND output is not empty -> ok". The probe
#   has been answering `Credit balance is too low` - which matches none of them - so every
#   pre-warm line since 08-13 read `ok` while nothing was ever warmed, and 175 windows since
#   7/24 opened, said that one sentence and died. "Output is not empty" could not save it either:
#   local\_lab_revive_probe.out.err always carries harness warnings, so the blob is never empty.
#   FIX (C-048): `Credit balance` joins the failure words AND the success side now needs a
#   POSITIVE proof - .claude\.credentials.json must actually be newer after the probe than it was
#   before. Failure words that "have not been added yet" can no longer be reported as success.
$credsFile  = Join-Path $env:USERPROFILE '.claude\.credentials.json'
$credsBefore = $null
try { if (Test-Path -LiteralPath $credsFile) { $credsBefore = (Get-Item -LiteralPath $credsFile).LastWriteTimeUtc } } catch {}
$probeOut = Join-Path $root 'local\_lab_revive_probe.out'
$probeIn  = Join-Path $root 'local\_lab_revive_probe.in'
Set-Content -LiteralPath $probeIn -Value '' -Encoding ASCII
try {
  $probe = Start-Process -FilePath $claude `
    -ArgumentList @('--print', '--model', 'sonnet', 'ping') `
    -NoNewWindow -PassThru -WorkingDirectory $root `
    -RedirectStandardInput $probeIn -RedirectStandardOutput $probeOut -RedirectStandardError ($probeOut + '.err')
  if (-not $probe.WaitForExit(90000)) {
    try { $probe.Kill() } catch {}
    Write-Log 'lab: AUTH PRE-WARM timed out (90s) - spawning anyway (fail-open)'
  } else {
    # ExitCode is NULL on a Start-Process -PassThru object that used redirection (measured on
    # PS 5.1, 2026-08-06), so judging on it would log FAILED on every success - a guard that
    # always misfires is a dead guard. Judge on the probe's own output instead.
    $blob = ''
    foreach ($f in @($probeOut, ($probeOut + '.err'))) {
      if (Test-Path -LiteralPath $f) { $blob += (Get-Content -LiteralPath $f -Raw) }
    }
    $credsAfter = $null
    try { if (Test-Path -LiteralPath $credsFile) { $credsAfter = (Get-Item -LiteralPath $credsFile).LastWriteTimeUtc } } catch {}
    Write-Log (Format-LabPrewarmLog (Get-LabPrewarmVerdict -Blob $blob -CredsBefore $credsBefore -CredsAfter $credsAfter))
  }
} catch {
  Write-Log ('lab: AUTH PRE-WARM errored: {0} - spawning anyway (fail-open)' -f $_.Exception.Message)
}

# --- 6) Spawn a FRESH Lab (visible window on purpose: interactive TUI + last-resort manual input
#        path via remote desktop). No -r resume. Same shape as open_dept_window.ps1. ---
#   WITNESS WRAPPER (2026-08-13, aegis-gl): go through scripts\_daemons\lab_window.cmd so the
#   parent shell records claude's exit code the moment it dies (see that file for why a batch
#   file is the only place %errorlevel% survives). $claude stays ON the command line as arg 1,
#   so the corpse filter in section 2.5 still matches these windows - do not move it inside.
#   fail-open: if the wrapper is missing we spawn exactly the way we did before, and say so.
$wrapper = Join-Path $root 'scripts\_daemons\lab_window.cmd'
if (Test-Path -LiteralPath $wrapper) {
  Start-Process -FilePath 'cmd.exe' -ArgumentList @('/k', $wrapper, $claude, $promptArg) -WorkingDirectory $root
  Write-Log 'lab: revived FRESH (no resume) with boot prompt - spawned visible window via lab_window.cmd (exit code will be logged to local\_lab_claude_exit.log)'
} else {
  Write-Log 'lab: lab_window.cmd missing - falling back to direct spawn (no exit-code witness)'
  Start-Process -FilePath 'cmd.exe' -ArgumentList @('/k', 'cd', '/d', $root, '&&', $claude, $promptArg) -WorkingDirectory $root
  Write-Log 'lab: revived FRESH (no resume) with boot prompt - spawned visible window'
}
Set-Content -LiteralPath $stateFile -Value $now -Encoding ASCII
