# revive_lab.ps1 - go5-maker: revive the Lab (kenkyushitsu) Claude session after logon / crash.
#
# WHY: every other line (Discord chime, daemons) only DELIVERS. Something must ANSWER.
#   The Lab session is the single always-open catch-all. If the PC reboots (Windows Update,
#   power loss) or the session dies while Chami is away, nothing answers in-character until he
#   opens it by hand - which he cannot do remotely. This restores it automatically.
#   (Availability itself is already floored by claude_responder.py's unmanned 代打; this brings
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

# --- 3) Cooldown: do not respawn faster than every 15 min. ---
$now = [int][double]::Parse((Get-Date -UFormat %s))
if (Test-Path -LiteralPath $stateFile) {
  $last = 0
  [int]::TryParse((Get-Content -LiteralPath $stateFile -Raw).Trim(), [ref]$last) | Out-Null
  if (($now - $last) -lt $cooldownSec) {
    Write-Log ('lab: dead but within cooldown ({0}s since last spawn) - skip' -f ($now - $last))
    exit 0
  }
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

# --- 5) Auth: a script-launched claude is NOT logged in unless we inject the OAuth token
#        (host auth is not inherited by a cold CLI). Token lives in local/cli_auth_token.txt
#        (gitignored). Set it as an ENV VAR (inherited by the child), never on the command line. ---
$tokFile = Join-Path $root 'local\cli_auth_token.txt'
if (Test-Path -LiteralPath $tokFile) {
  $env:CLAUDE_CODE_OAUTH_TOKEN = (Get-Content -LiteralPath $tokFile -Raw).Trim()
} else {
  Write-Log 'lab: WARNING - local\cli_auth_token.txt missing. Revived session may not be logged in (deaf window). Run: claude setup-token'
}

# --- 6) Spawn a FRESH Lab (visible window on purpose: interactive TUI + last-resort manual input
#        path via remote desktop). No -r resume. Same shape as open_dept_window.ps1. ---
Start-Process -FilePath 'cmd.exe' -ArgumentList @('/k', 'cd', '/d', $root, '&&', $claude, $prompt) -WorkingDirectory $root
Set-Content -LiteralPath $stateFile -Value $now -Encoding ASCII
Write-Log 'lab: revived FRESH (no resume) with boot prompt - spawned visible window'
