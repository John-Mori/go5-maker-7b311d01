# resume_daemons.ps1 - undo panic_stop.ps1 (2026-07-20, O1).
# Re-enables the 3 auto-restart tasks and runs ONE supervise pass so the fleet comes back now
# (instead of waiting up to 10 minutes for the next scheduled pass).
# ASCII-only (PS 5.1 codepage safety).
$ErrorActionPreference = 'SilentlyContinue'
$here = $PSScriptRoot
$root = Split-Path -Parent (Split-Path -Parent $here)
$suplog = Join-Path $root 'local\_daemons_supervisor.log'
function Write-SupLog($m){ $ts=Get-Date -Format 'yyyy-MM-dd HH:mm:ss'; try{Add-Content -LiteralPath $suplog -Value "$ts $m" -Encoding UTF8}catch{} }

$restartTasks = @('go5_daemons_hidden','go5_lab_revive','go5_deadman_check')
foreach ($t in $restartTasks) {
  $st = Get-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue
  if ($null -eq $st) { Write-Host ("  task {0}: not found (skip)" -f $t); continue }
  Enable-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue | Out-Null
  Write-Host ("  task {0}: enabled" -f $t)
  Write-SupLog ("resume_daemons: enabled task {0}" -f $t)
}

# bring the fleet back immediately with one supervise pass
$sup = Join-Path $here 'supervise_daemons.ps1'
if (Test-Path -LiteralPath $sup) {
  Write-Host "  running one supervise pass to restart the fleet now..."
  & powershell -NoProfile -ExecutionPolicy Bypass -File $sup | Out-Null
  Write-Host "  supervise pass done."
} else {
  Write-Host "  supervise_daemons.ps1 not found; the scheduled task will rebuild within ~10min."
}
Write-Host "resume_daemons: DONE. Fleet re-enabled."
