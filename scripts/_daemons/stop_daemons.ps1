# stop_daemons.ps1 - stop all 4 resident daemons and disable the auto-start task
# (so they stay down). Re-enable by running register_daemons_logon_task.ps1 again.
# ASCII-only (PS 5.1 codepage safety).
$ErrorActionPreference = 'SilentlyContinue'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$suplog = Join-Path $root 'local\_daemons_supervisor.log'
function Write-SupLog($m){ $ts=Get-Date -Format 'yyyy-MM-dd HH:mm:ss'; try{Add-Content -LiteralPath $suplog -Value "$ts $m" -Encoding UTF8}catch{} }

try { Disable-ScheduledTask -TaskName 'go5_daemons_hidden' -ErrorAction Stop | Out-Null; Write-SupLog "task go5_daemons_hidden disabled (stop_daemons)" } catch { Write-SupLog "task disable skipped" }

$pat = 'inbox_poller\.py|absence_watchdog\.py|local_responder\.py|gemini_responder\.py'
$procs = @(Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -and ($_.CommandLine -match $pat) })
foreach ($p in $procs) { Stop-Process -Id $p.ProcessId -Force }
Write-SupLog ("stopped {0} daemon process(es) (stop_daemons)" -f $procs.Count)
Write-Host ("stopped {0} daemon(s) and disabled auto-start." -f $procs.Count)
