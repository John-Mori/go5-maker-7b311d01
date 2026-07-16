# revive_lab.ps1 - go5-maker: revive the Lab (研究室) Claude session after logon / crash.
#
# WHY: every other line (Discord chime, daemons) only DELIVERS. Something must ANSWER.
#   The Lab session is the single always-open catch-all. If the PC reboots (Windows Update,
#   power loss) or the session dies while Chami is away (Fukuoka trip), nothing answers until
#   he opens it by hand - which he cannot do remotely. This restores it automatically.
#
# WHAT: if no Claude process is alive, open ONE terminal running `claude -r <LAB_SESSION_ID>`
#   in the repo root. Deliberately VISIBLE: `claude` is an interactive TUI; a hidden window
#   cannot be typed into, and Chami needs that window as the last-resort input path
#   (via remote desktop). Every other daemon stays hidden - this one window is the exception.
#
# IDEMPOTENT: does nothing when a Claude session is already running (checked by process name),
#   so the 10-minute scheduled task never spawns a second one.
#
# NOTE: keep this file ASCII-only. PowerShell 5.1 reads a no-BOM file as the system ANSI
#       codepage; non-ASCII here corrupts parsing. Japanese notes live in README.md.
$ErrorActionPreference = 'SilentlyContinue'
$root = 'D:\SougouStartFolder\go5-maker'
$log  = Join-Path $root 'local\_lab_revive.log'
# Lab session id. MUST be the real session UUID (the .jsonl filename under
#   C:\Users\chami\.claude\projects\D--SougouStartFolder-go5-maker\ ), NOT the cross-session
#   "local_xxxx" identifier. Those are two different id systems and mixing them silently breaks
#   revival: 2026-07-16 this held 'local_94702660-...' and `claude -r` rejected it with
#   "is not a UUID and does not match any session title" — i.e. the Lab would NOT have come back
#   after a reboot while Chami was away. It was never caught because revive only fires when no
#   claude process is alive, which had not happened since the task was registered.
# When the Lab session is handed over (new volume), update this to the new UUID: see
#   scripts/_daemons/set_lab_session.ps1 which resolves the newest session file and rewrites it.
$labId = '46c7212b-68e9-48d1-ac5e-c671d356db02'

function Write-Log($m) {
  $ts = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
  try { Add-Content -LiteralPath $log -Value "$ts $m" -Encoding UTF8 } catch {}
}

# Is any Claude session alive? claude.exe is the CLI; node.exe running claude is the fallback shape.
$alive = @(Get-Process -Name 'claude' -ErrorAction SilentlyContinue)
if ($alive.Count -gt 0) {
  Write-Log ("lab: ok ({0} claude process(es) alive)" -f $alive.Count)
  exit 0
}

$claude = 'C:\Users\chami\.local\bin\claude.exe'
if (-not (Test-Path -LiteralPath $claude)) {
  Write-Log "lab: claude.exe not found - cannot revive"
  exit 1
}

# Visible window on purpose (interactive TUI + last-resort manual input path).
$cmd = 'cd /d "' + $root + '" && "' + $claude + '" -r ' + $labId
Start-Process -FilePath 'cmd.exe' -ArgumentList ('/k ' + $cmd) -WorkingDirectory $root
Write-Log ("lab: revived (claude -r {0})" -f $labId)
