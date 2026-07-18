# open_dept_window.ps1 - go5-maker: open a department session window for Chami.
#
# WHY: Chami must otherwise paste a long boot prompt into a NEW Claude Code window by hand.
#   On 2026-07-16 he tried and the text arrived mangled (copied from a phone), and he pasted it
#   into Discord where it does nothing. Meanwhile the Lab was carrying 43 msgs/day alone
#   (67% of them other departments' work) because no department window was open.
#   This opens the window FOR him: one command, correct prompt, every time.
#
# WHAT: launches `claude "<boot prompt>"` in a visible terminal at the repo root.
#   Visible on purpose: claude is an interactive TUI and Chami must be able to type into it.
#
# USAGE:  powershell -File open_dept_window.ps1 -Dept system-engineer
#         powershell -File open_dept_window.ps1 -Dept hr-room
#   The Japanese boot text lives in dept_boot_prompt.py (this file stays ASCII-only:
#   PowerShell 5.1 reads a no-BOM file as the system ANSI codepage and would corrupt it).
param(
  [Parameter(Mandatory = $true)][string]$Dept
)
$ErrorActionPreference = 'SilentlyContinue'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$log  = Join-Path $root 'local\_dept_window.log'

function Write-Log($m) {
  $ts = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
  try { Add-Content -LiteralPath $log -Value "$ts $m" -Encoding UTF8 } catch {}
}

# Build the boot prompt (python owns the Japanese text and the dept->persona mapping)
$promptFile = Join-Path $root 'local\_boot_prompt.txt'
& python (Join-Path $root 'scripts\_daemons\dept_boot_prompt.py') $Dept $promptFile | Out-Null
if (-not (Test-Path -LiteralPath $promptFile)) { Write-Log "no prompt for $Dept"; exit 1 }
$prompt = (Get-Content -LiteralPath $promptFile -Raw -Encoding UTF8).Trim()
if (-not $prompt) { Write-Log "empty prompt for $Dept"; exit 1 }

$claude = 'C:\Users\chami\.local\bin\claude.exe'
if (-not (Test-Path -LiteralPath $claude)) { Write-Log 'claude.exe not found'; exit 1 }

# Already open? (a waiter for this dept means the window is alive) -> do not double-open
$alive = @(Get-CimInstance Win32_Process | Where-Object {
  $_.Name -eq 'python.exe' -and $_.CommandLine -match 'inbox_waiter' -and $_.CommandLine -match ("--name\s+" + [regex]::Escape($Dept))
})
if ($alive.Count -gt 0) { Write-Log ("$Dept : already open"); Write-Output 'ALREADY_OPEN'; exit 0 }

# Visible window on purpose (interactive TUI). Pass the prompt as the first argument.
Start-Process -FilePath 'cmd.exe' -ArgumentList @('/k', 'cd', '/d', $root, '&&', $claude, $prompt) -WorkingDirectory $root
Write-Log ("$Dept : opened")
Write-Output 'OPENED'
