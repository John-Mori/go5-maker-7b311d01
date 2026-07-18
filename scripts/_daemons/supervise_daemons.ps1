# supervise_daemons.ps1 - go5-maker: keep resident daemons hidden & single-instance (idempotent).
# Ensures exactly ONE hidden instance of each of: inbox_poller / absence_watchdog /
# local_responder / gemini_responder. Kills duplicates; (re)starts only what is missing.
# Hidden launch: WScript.Shell.Run(cmd, 0, False)  -> 0 = hidden window (same as sales_poll_hidden.vbs).
# NOTE: keep this file ASCII-only. PowerShell 5.1 reads a no-BOM file as the system ANSI
#       codepage; non-ASCII here corrupts parsing. Japanese notes live in README.md (not executed).
$ErrorActionPreference = 'SilentlyContinue'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$suplog = Join-Path $root 'local\_daemons_supervisor.log'

function Write-SupLog($m) {
  $ts = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
  try { Add-Content -LiteralPath $suplog -Value "$ts $m" -Encoding UTF8 } catch {}
}

$daemons = @(
  @{ Name='inbox_poller';     File='inbox_poller.py';     Rel='scripts\discord\inbox_poller.py';     LogRel='local\discord_poller.log' },
  @{ Name='absence_watchdog'; File='absence_watchdog.py'; Rel='scripts\discord\absence_watchdog.py'; LogRel='local\discord_watchdog.log' },
  @{ Name='local_responder';  File='local_responder.py';  Rel='scripts\llm\local_responder.py';      LogRel='local\llm\responder_console.log' },
  @{ Name='gemini_responder'; File='gemini_responder.py'; Rel='scripts\llm\gemini_responder.py';     LogRel='local\llm\gemini_responder_console.log' },
  @{ Name='office_daily';     File='office_daily.py';     Rel='scripts\office\office_daily.py';      LogRel='local\office\_daily.log' },
  # claude_responder (2026-07-17): while the Lab session is dead, process the main box with
  #   `claude --print` so Discord still gets replies when every session is down (root fix for
  #   INC-98). Stays silent when the Lab is alive (lab_alive guard). Needs local\cli_auth_token.txt.
  @{ Name='claude_responder'; File='claude_responder.py'; Rel='scripts\llm\claude_responder.py';     LogRel='local\llm\claude_responder_console.log' },
  # daemon_keeper (2026-07-18, R0): keeps per-department character daemons (dept_daemon.py) alive
  #   with exponential backoff + circuit breaker. Departments never go unmanned (Chami directive).
  #   Two layers: keeper restarts daemons in seconds; this supervisor restarts the keeper in <=10min.
  @{ Name='daemon_keeper';    File='daemon_keeper.py';    Rel='scripts\_daemons\daemon_keeper.py';   LogRel='local\_daemon_keeper.log' }
)

$sh = New-Object -ComObject WScript.Shell
$allPy = @(Get-CimInstance Win32_Process -Filter "Name='python.exe'")

foreach ($d in $daemons) {
  $procs = @($allPy | Where-Object { $_.CommandLine -and ($_.CommandLine -like ('*' + $d.File + '*')) })
  if ($procs.Count -eq 1) {
    Write-SupLog ("{0}: ok (1 running, pid {1})" -f $d.Name, $procs[0].ProcessId)
    continue
  }
  if ($procs.Count -gt 1) {
    foreach ($p in $procs) { Stop-Process -Id $p.ProcessId -Force }
    Write-SupLog ("{0}: deduped ({1} instances -> restart 1)" -f $d.Name, $procs.Count)
  }
  $logAbs = $root + '\' + $d.LogRel
  $cmd = 'cmd /c cd /d "' + $root + '" && python "' + $d.Rel + '" >> "' + $logAbs + '" 2>&1'
  $sh.Run($cmd, 0, $false) | Out-Null
  Write-SupLog ("{0}: started hidden" -f $d.Name)
}
Write-SupLog "supervise pass done"
