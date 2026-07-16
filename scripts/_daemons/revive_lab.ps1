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
# Lab session: "5秒動画メーカー 研究室 Vol.8 アロンソ/アメス" (kept across reboots so history survives)
$labId = 'local_94702660-bf3d-44ea-a8a7-b918998bb9c2'

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
