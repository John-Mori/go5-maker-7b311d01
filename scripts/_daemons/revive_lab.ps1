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

# --- 1) Is the Lab alive? Single source of truth = presence.lab_alive (exit 0 alive / 3 dead). ---
$py = 'python'
& $py (Join-Path $root 'scripts\llm\presence.py') --check 2>$null | Out-Null
$labAlive = ($LASTEXITCODE -eq 0)
if ($labAlive) {
  Write-Log 'lab: ok (presence.lab_alive)'
  # presence recovered -> whatever we were sparing is vindicated, reset the counter (section 2.5)
  try { Remove-Item -LiteralPath (Join-Path $root 'local\_lab_revive_spare.txt') -Force -ErrorAction SilentlyContinue } catch {}
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
#   Newest first. Only ONE window can be the Lab, and it is always the most recently spawned
#   one (a hand-opened Lab does not carry claude.exe on the cmd command line, so it is not even
#   in this set). Everything older than the newest is therefore superseded and is reaped without
#   the working-check - that is what keeps the 2026-08-01 pileup from coming back through the
#   guard below.
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
#   AND bound the sparing. An idle-but-live TUI burns about the same trickle of CPU as a wedged
#   one (measured 2026-08-13 on the live Lab while it sat at an armed waiter: +16ms over 5s), so
#   "burning CPU" cannot by itself tell a working Lab from the deaf zombies of 2026-08-01. If the
#   SAME shell is spared pass after pass without presence ever going ok again, it is not working,
#   it is stuck - and sparing forever would leave the Lab unrevived, which is the accident on the
#   other side. Count consecutive spares per pid and give up after SPARE_MAX passes (~3 hours at
#   10 min/pass). Every spare is logged, so this trips only after ~18 visible warnings.
$spareStateFile = Join-Path $root 'local\_lab_revive_spare.txt'
$SPARE_MAX = 18
$sparePrevPid = ''
$sparePrevCount = 0
if (Test-Path -LiteralPath $spareStateFile) {
  $parts = ((Get-Content -LiteralPath $spareStateFile -Raw).Trim() -split '\s+')
  if ($parts.Count -ge 2) { $sparePrevPid = $parts[0]; [int]::TryParse($parts[1], [ref]$sparePrevCount) | Out-Null }
}
$spareNewPid = ''
$spareNewCount = 0

$reaped = 0
$spared = 0
$busyShells = 0   # positively measured as still working (not just "unmeasurable")
$idx = -1
foreach ($rc in $aged) {
  $idx++
  if ($idx -gt 0) {
    # superseded window: cannot be the current Lab, reap without ceremony
    Write-Log ('lab: cmd pid {0} is an older duplicate revival shell (newest is pid {1}) - reaping' -f $rc.ProcessId, $aged[0].ProcessId)
    Get-CimInstance Win32_Process -Filter ("ParentProcessId={0}" -f $rc.ProcessId) -ErrorAction SilentlyContinue | ForEach-Object {
      Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
    Stop-Process -Id $rc.ProcessId -Force -ErrorAction SilentlyContinue
    $reaped++
    continue
  }
  if ($null -eq $cpu1) { $spared++; continue }   # probe failed -> never kill on an unknown
  $kids = $null
  try {
    $kids = @(Get-CimInstance Win32_Process -Filter ("ParentProcessId={0}" -f $rc.ProcessId) -ErrorAction Stop)
  } catch {
    Write-Log ('lab: autopsy failed for cmd pid {0} ({1}) - sparing it' -f $rc.ProcessId, $_.Exception.Message)
    $spared++
    continue
  }
  $claudeKids = @($kids | Where-Object { $_.Name -eq 'claude.exe' })
  if ($claudeKids.Count -eq 0) {
    Write-Log ('lab: cmd pid {0}: children [{1}] - no claude.exe = confirmed corpse, reaping' -f `
      $rc.ProcessId, (($kids | ForEach-Object { $_.Name }) -join ','))
  } else {
    $working = $false
    $busy = $false
    $desc = ''
    foreach ($ck in $claudeKids) {
      $k = [string]$ck.ProcessId
      $ws = [int]($ck.WorkingSetSize / 1MB)
      if ($cpu1.ContainsKey($k) -and $cpu2.ContainsKey($k)) {
        $cpuMs = [int]((($cpu2[$k] - $cpu1[$k])) / 10000)
        $desc += ('claude pid={0} ws={1}MB cpu+{2}ms; ' -f $k, $ws, $cpuMs)
        if ($cpuMs -gt 0) { $working = $true; $busy = $true }
      } else {
        $desc += ('claude pid={0} ws={1}MB cpu=UNMEASURED; ' -f $k, $ws)
        $working = $true   # cannot prove it is idle -> treat as alive (fail-open, do not kill)
      }
    }
    if ($working) {
      $n = 1
      if ($sparePrevPid -eq [string]$rc.ProcessId) { $n = $sparePrevCount + 1 }
      if ($n -gt $SPARE_MAX) {
        Write-Log ('lab: cmd pid {0} spared {1} passes in a row and presence never recovered [{2}] - treating it as stuck, reaping' -f $rc.ProcessId, $sparePrevCount, $desc)
      } else {
        Write-Log ('lab: cmd pid {0} has a WORKING claude.exe [{1}] - NOT reaping (spare {2}/{3}). presence says dead but the process is busy = the ear (waiter/liveness pulse) is what died, not the Lab' -f $rc.ProcessId, $desc, $n, $SPARE_MAX)
        $spareNewPid = [string]$rc.ProcessId
        $spareNewCount = $n
        $spared++
        if ($busy) { $busyShells++ }
        continue
      }
    } else {
      Write-Log ('lab: cmd pid {0}: claude.exe alive but 0 CPU over 5s [{1}] - deaf zombie, reaping' -f $rc.ProcessId, $desc)
    }
  }
  foreach ($k in $kids) { Stop-Process -Id $k.ProcessId -Force -ErrorAction SilentlyContinue }
  Stop-Process -Id $rc.ProcessId -Force -ErrorAction SilentlyContinue
  $reaped++
}
if ($reaped -gt 0) { Write-Log ('lab: reaped {0} stale revival shell(s) before spawn (dead+no-waiter = corpses)' -f $reaped) }
if ($spared -gt 0) { Write-Log ('lab: spared {0} shell(s) that were still working or unmeasurable' -f $spared) }
# Persist the consecutive-spare counter (or clear it the moment we stop sparing that pid).
try {
  if ($spareNewPid) { Set-Content -LiteralPath $spareStateFile -Value ('{0} {1}' -f $spareNewPid, $spareNewCount) -Encoding ASCII }
  elseif (Test-Path -LiteralPath $spareStateFile) { Remove-Item -LiteralPath $spareStateFile -Force -ErrorAction SilentlyContinue }
} catch {}
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
    if ($blob -match 'Please run /login|Not logged in|401|Invalid API key|authentication_error') {
      Write-Log 'lab: AUTH PRE-WARM FAILED - host creds could not be refreshed. The revived window will show /login. See local\_lab_revive_probe.out'
    } elseif ($blob.Trim().Length -gt 0) {
      Write-Log 'lab: auth pre-warm ok (.claude\.credentials.json refreshed) - cold TUI should authenticate'
    } else {
      Write-Log 'lab: auth pre-warm returned nothing - treating as unknown, spawning anyway (fail-open)'
    }
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
