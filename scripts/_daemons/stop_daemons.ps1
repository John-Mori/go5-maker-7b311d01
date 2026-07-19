# stop_daemons.ps1 - DEPRECATED shim (2026-07-20, O1). The old version only stopped 4 of the
#   daemons and left gateway/keeper/9 dept_daemon/claude_responder running = name did not match
#   reality (改善書 P0-3). It now delegates to panic_stop.ps1, the complete + tested full-stop.
# ASCII-only (PS 5.1 codepage safety).
$ErrorActionPreference = 'SilentlyContinue'
$here = $PSScriptRoot
Write-Host "stop_daemons.ps1 -> delegating to panic_stop.ps1 (full fleet stop)"
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $here 'panic_stop.ps1') @args
Write-Host "(to also kill Claude '--print' workers: panic_stop.ps1 -IncludeWorkers ; to resume: resume_daemons.ps1)"
