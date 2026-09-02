# longjob.ps1 - go5-maker: run a long job DETACHED from the interactive session, resume until done.
#
# ASCII-ONLY. PowerShell 5.1 reads a no-BOM file as the system ANSI codepage; a single non-ASCII
# byte corrupts parsing. Japanese notes live in longjob.README.md (not executed).
#
# WHY THIS FILE EXISTS
#   An interactive session that starts a long job (ollama pull, style-LoRA train, big scrape) and
#   then closes takes the job down with it. Measured by HQ (2026-09-03): an ollama pull's 16
#   parallel chunks all stopped together at ~50.6% - not a network drop but the client process
#   dying, so the server cancelled the pull. This is the generic "run to completion" VESSEL.
#   It is the vessel ONLY: WHAT to run, which model, and whether the result is usable belong to
#   the owning business / learning dept. This file just keeps the job alive across session death.
#
#   NOT ollama-specific. A job = a command + a working dir + a log + a DONE predicate.
#     DONE predicate = a command line; exit code 0 means "finished, stop retrying".
#     ollama : "ollama list | findstr <model>"      (the model name appears in the list)
#     scrape : cmd /c if exist cursor.done exit 0    (a sentinel file)
#     LoRA   : whatever the trainer writes when a checkpoint reaches the target step
#
# DETACHMENT
#   WScript.Shell.Run(cmd, 0, $false) - the SAME hidden ("0"), non-waiting ("$false"), fully
#   detached launch that supervise_daemons.ps1 uses for the 8 residents. The launched cmd becomes
#   its own process tree, so the caller (and the caller's session) can die without taking it down.
#   C-041: one 40-min survival observation is NOT proof. The vessel therefore does not TRUST
#   detachment - a resume pass relaunches any job that died before its DONE predicate passed.
#   RESUME NEEDS A RESUMABLE JOB: the vessel supplies the retry loop; the job must pick up where
#   it left off (ollama pull resumes from -partial; a trainer from its last checkpoint; a scrape
#   from its cursor). A non-resumable command will simply restart from zero.
#
# LIVENESS
#   Matched on the wrapper .cmd path in the process CommandLine (same idea as supervise's Match),
#   never on a marker file: a killed job leaves its marker behind, and reading that as "alive"
#   is exactly how you end up staring at a job that is actually dead (the -partial JSON trap HQ hit).
#   Completion is judged ONLY by the DONE predicate (a real check: e.g. the model is in the list),
#   never by a file size (a -partial file is pre-allocated at full size = a sparse-file lie).
#
# USAGE
#   powershell -NoProfile -ExecutionPolicy Bypass -File longjob.ps1 start  -Id <id> -Cmd "<command>" -Done "<predicate>" [-WorkDir <dir>] [-Log <path>] [-MaxAttempts 20]
#   powershell -NoProfile -ExecutionPolicy Bypass -File longjob.ps1 status [-Id <id>]
#   powershell -NoProfile -ExecutionPolicy Bypass -File longjob.ps1 resume [-Id <id>]     # relaunch one if dead & not done
#   powershell -NoProfile -ExecutionPolicy Bypass -File longjob.ps1 resume-all            # patrol: at most 1 relaunch per pass
#   powershell -NoProfile -ExecutionPolicy Bypass -File longjob.ps1 list

param(
  [Parameter(Position = 0)][string]$Action = 'list',
  [string]$Id,
  [string]$Cmd,
  [string]$Done,
  [string]$WorkDir,
  [string]$Log,
  [int]$MaxAttempts = 20
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$jobDir = Join-Path $root 'local\_work\longjobs'
if (-not (Test-Path -LiteralPath $jobDir)) { New-Item -ItemType Directory -Path $jobDir -Force | Out-Null }
$patrolLog = Join-Path $jobDir '_patrol.log'

function Write-JobLog($m) {
  $ts = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
  try { Add-Content -LiteralPath $patrolLog -Value "$ts $m" -Encoding UTF8 } catch {}
}

function Get-ManifestPath($jid) { return (Join-Path $jobDir ($jid + '.json')) }
function Get-WrapperPath($jid)  { return (Join-Path $jobDir ($jid + '.run.cmd')) }
function Get-ExitPath($jid)     { return (Join-Path $jobDir ($jid + '.exit')) }

function Load-Job($jid) {
  $p = Get-ManifestPath $jid
  if (-not (Test-Path -LiteralPath $p)) { return $null }
  return (Get-Content -LiteralPath $p -Raw -Encoding UTF8 | ConvertFrom-Json)
}

function Save-Job($job) {
  $p = Get-ManifestPath $job.id
  ($job | ConvertTo-Json -Depth 6) | Set-Content -LiteralPath $p -Encoding UTF8
}

function All-Jobs {
  return @(Get-ChildItem -LiteralPath $jobDir -Filter '*.json' -ErrorAction SilentlyContinue |
    ForEach-Object { Get-Content -LiteralPath $_.FullName -Raw -Encoding UTF8 | ConvertFrom-Json })
}

# Alive = a process whose CommandLine still references this job's wrapper .cmd.
function Test-JobAlive($job) {
  $wrap = Get-WrapperPath $job.id
  $leaf = Split-Path -Leaf $wrap
  $procs = @(Get-CimInstance Win32_Process -Filter "Name='cmd.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -and ($_.CommandLine -like ('*' + $leaf + '*')) })
  return ($procs.Count -ge 1)
}

# Done = the caller's predicate returns exit 0. A REAL check, run every time (never cached,
# never a file-size guess). Empty predicate = the vessel cannot confirm completion -> never "done".
function Test-JobDone($job) {
  if ([string]::IsNullOrWhiteSpace($job.done_cmd)) { return $false }
  cmd /c $job.done_cmd 1>$null 2>$null
  return ($LASTEXITCODE -eq 0)
}

# Launch (or relaunch) the job detached + hidden. Regenerates the wrapper each time so an edited
# command takes effect on resume. Records attempts so a job that keeps dying stops eventually.
function Launch-Job($job) {
  $wrap = Get-WrapperPath $job.id
  $exit = Get-ExitPath $job.id
  if (Test-Path -LiteralPath $exit) { Remove-Item -LiteralPath $exit -Force -ErrorAction SilentlyContinue }
  $wd = $job.workdir; if ([string]::IsNullOrWhiteSpace($wd)) { $wd = $root }
  $lg = $job.log;     if ([string]::IsNullOrWhiteSpace($lg)) { $lg = Join-Path $jobDir ($job.id + '.out.log') }
  $lgDir = Split-Path -Parent $lg
  if ($lgDir -and -not (Test-Path -LiteralPath $lgDir)) { New-Item -ItemType Directory -Path $lgDir -Force | Out-Null }

  # Wrapper .cmd: cd, run the command with output appended to the log, then record the real exit
  # code ON ITS OWN LINE (a one-liner would expand %ERRORLEVEL% at parse time = always 0).
  $lines = @(
    '@echo off',
    ('set GO5_LONGJOB=' + $job.id),
    ('cd /d "' + $wd + '"'),
    ('(' + $job.cmd + ') >> "' + $lg + '" 2>&1'),
    ('echo %ERRORLEVEL%> "' + $exit + '"')
  )
  Set-Content -LiteralPath $wrap -Value $lines -Encoding ASCII

  $sh = New-Object -ComObject WScript.Shell
  $sh.Run(('cmd /c "' + $wrap + '"'), 0, $false) | Out-Null

  $job.attempts   = [int]$job.attempts + 1
  $job.status     = 'running'
  $job.last_launch_utc = (Get-Date).ToUniversalTime().ToString('o')
  Save-Job $job

  # Verify a resident process actually appeared (do not record a launch we cannot see).
  Start-Sleep -Milliseconds 2000
  $ok = Test-JobAlive $job
  Write-JobLog ("{0}: launch attempt {1} -> alive={2}" -f $job.id, $job.attempts, $ok)
  return $ok
}

function Show-One($job) {
  $done  = Test-JobDone $job
  $alive = Test-JobAlive $job
  $state = if ($done) { 'DONE' } elseif ($alive) { 'RUNNING' } else { 'STALLED' }
  $ex = ''
  $exf = Get-ExitPath $job.id
  if ((-not $alive) -and (Test-Path -LiteralPath $exf)) {
    # Exit file can be momentarily 0 bytes (job wrote its DONE sentinel and broke, wrapper has not
    # yet echoed the code). Get-Content -Raw returns $null for an empty file - guard before .Trim().
    $raw = Get-Content -LiteralPath $exf -Raw
    if ($raw) { $ex = ' last_exit=' + $raw.Trim() }
  }
  '{0,-9} {1,-24} attempts={2}/{3}{4}' -f $state, $job.id, $job.attempts, $job.max_attempts, $ex
}

switch ($Action) {

  'start' {
    if ([string]::IsNullOrWhiteSpace($Id))  { throw 'start needs -Id' }
    if ([string]::IsNullOrWhiteSpace($Cmd)) { throw 'start needs -Cmd' }
    $existing = Load-Job $Id
    if ($existing) {
      if (Test-JobDone $existing) { Write-Output ("already done: " + $Id); break }
      if (Test-JobAlive $existing) { Write-Output ("already running: " + $Id); break }
    }
    $job = [pscustomobject]@{
      id           = $Id
      cmd          = $Cmd
      done_cmd     = $Done
      workdir      = $WorkDir
      log          = $Log
      max_attempts = $MaxAttempts
      attempts     = 0
      status       = 'new'
      started_utc  = (Get-Date).ToUniversalTime().ToString('o')
      last_launch_utc = ''
    }
    Save-Job $job
    $ok = Launch-Job $job
    Write-Output ((Show-One (Load-Job $Id)))
  }

  'status' {
    if ($Id) { $job = Load-Job $Id; if (-not $job) { throw ('no such job: ' + $Id) }; Write-Output (Show-One $job) }
    else { foreach ($j in (All-Jobs)) { Write-Output (Show-One $j) } }
  }

  'list' {
    foreach ($j in (All-Jobs)) { Write-Output (Show-One $j) }
  }

  'resume' {
    if ([string]::IsNullOrWhiteSpace($Id)) { throw 'resume needs -Id (use resume-all for the patrol)' }
    $job = Load-Job $Id; if (-not $job) { throw ('no such job: ' + $Id) }
    if (Test-JobDone $job) { $job.status = 'done'; Save-Job $job; Write-Output ('done: ' + $Id); break }
    if (Test-JobAlive $job) { Write-Output ('still running: ' + $Id); break }
    if ([int]$job.attempts -ge [int]$job.max_attempts) { $job.status = 'failed'; Save-Job $job; Write-Output ('max attempts reached: ' + $Id); break }
    $ok = Launch-Job $job
    Write-Output (Show-One (Load-Job $Id))
  }

  # Patrol: mark finished jobs done, relaunch at most ONE stalled job per pass (C-058: never a
  # thundering herd on the desktop). Meant to be called from the existing 10-min supervisor pass.
  'resume-all' {
    $relaunched = 0
    foreach ($job in (All-Jobs)) {
      if ($job.status -eq 'done' -or $job.status -eq 'failed') { continue }
      if (Test-JobDone $job)  { $job.status = 'done'; Save-Job $job; Write-JobLog ($job.id + ': DONE'); continue }
      if (Test-JobAlive $job) { continue }
      if ([int]$job.attempts -ge [int]$job.max_attempts) { $job.status = 'failed'; Save-Job $job; Write-JobLog ($job.id + ': FAILED (max attempts)'); continue }
      if ($relaunched -ge 1) { Write-JobLog ($job.id + ': stalled, deferred to next pass (1/pass cap)'); continue }
      $ok = Launch-Job $job
      if ($ok) { $relaunched++ }
    }
    Write-JobLog ("resume-all pass done (relaunched {0})" -f $relaunched)
  }

  default { throw ('unknown action: ' + $Action) }
}
