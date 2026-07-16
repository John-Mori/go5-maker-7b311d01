# set_lab_session.ps1 - point revive_lab.ps1 at the CURRENT Lab session.
#
# WHY: revive_lab.ps1 hardcodes the Lab session UUID so a reboot can bring the Lab back.
#   That UUID changes every time the Lab is handed over to a new volume (Vol.8 -> Vol.9).
#   If nobody updates it, revival silently targets a dead/《wrong》 session — and nobody notices,
#   because revive only fires when NO claude process is alive (rare, and always while Chami is away).
#   That is exactly the bug found on 2026-07-16: the id was a cross-session "local_xxxx" value that
#   `claude -r` rejects outright. This script removes the manual step.
#
# WHAT: resolves the newest session .jsonl for this project (that is the live Lab, since the Lab is
#   the always-open session) and rewrites $labId in revive_lab.ps1. Verifies the id is a UUID.
#
# USAGE:
#   powershell -File set_lab_session.ps1                 # auto: newest session file
#   powershell -File set_lab_session.ps1 -SessionId <uuid>   # explicit (use right after a handover)
#
# NOTE: keep this file ASCII-only (PowerShell 5.1 reads a no-BOM file as the system ANSI codepage).
param(
  [string]$SessionId = ''
)
$ErrorActionPreference = 'SilentlyContinue'
$root     = 'D:\SougouStartFolder\go5-maker'
$projDir  = 'C:\Users\chami\.claude\projects\D--SougouStartFolder-go5-maker'
$revive   = Join-Path $root 'scripts\_daemons\revive_lab.ps1'
$log      = Join-Path $root 'local\_lab_revive.log'

function Write-Log($m) {
  $ts = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
  try { Add-Content -LiteralPath $log -Value "$ts $m" -Encoding UTF8 } catch {}
}

if (-not $SessionId) {
  $newest = Get-ChildItem -LiteralPath $projDir -Filter '*.jsonl' -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending | Select-Object -First 1
  if (-not $newest) { Write-Output 'NO_SESSION_FILE'; Write-Log 'set_lab: no session file'; exit 1 }
  $SessionId = [System.IO.Path]::GetFileNameWithoutExtension($newest.Name)
}

# Must be a real UUID. `claude -r` rejects anything else (this is the 2026-07-16 bug).
if ($SessionId -notmatch '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$') {
  Write-Output ('NOT_A_UUID: ' + $SessionId)
  Write-Log ('set_lab: refused non-uuid ' + $SessionId)
  exit 1
}
if (-not (Test-Path -LiteralPath (Join-Path $projDir ($SessionId + '.jsonl')))) {
  Write-Output ('NO_SUCH_SESSION: ' + $SessionId)
  Write-Log ('set_lab: no session file for ' + $SessionId)
  exit 1
}

$text = Get-Content -LiteralPath $revive -Raw
$new  = [regex]::Replace($text, "(?m)^\$labId\s*=\s*'[^']*'", ("`$labId = '" + $SessionId + "'"))
if ($new -eq $text) { Write-Output 'UNCHANGED'; exit 0 }
Set-Content -LiteralPath $revive -Value $new -Encoding UTF8
Write-Output ('SET: ' + $SessionId)
Write-Log ('set_lab: labId -> ' + $SessionId)
