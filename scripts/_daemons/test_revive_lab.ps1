# test_revive_lab.ps1 - must-fail checks for the reaper judgment (2026-08-22, aegis-gl).
#   Spec: HQ msg 1540735472282767440 section 5.
#   HOW IT RUNS: dot-source revive_lab.ps1 in LIBRARY MODE (LAB_REVIVE_LIB=1) so the functions
#   load and NO revival happens. The judgment (Get-LabShellVerdict) and the branching
#   (Invoke-LabReapPass) are the REAL ones - only Stop-Process is replaced by a recorder, and
#   the CPU sample / presence / transcript facts are handed in as fixed inputs. Nothing here
#   greps the source: a check passes only if the code actually decided that way.
#   Run: powershell -NoProfile -File scripts\_daemons\test_revive_lab.ps1
# ASCII-only (same reason as revive_lab.ps1: PS 5.1 reads no-BOM files as the ANSI codepage).
$ErrorActionPreference = 'Stop'
$env:LAB_REVIVE_LIB = '1'
. (Join-Path $PSScriptRoot 'revive_lab.ps1')

$script:pass = 0
$script:fail = 0
function Check($name, $cond, $detail) {
  if ($cond) { $script:pass++; Write-Host ("  PASS  " + $name) }
  else { $script:fail++; Write-Host ("  FAIL  " + $name + "   <- " + $detail) -ForegroundColor Red }
}

# --- fakes: the only outward hands. Everything else runs for real. ---
$script:killed = @()
$script:logs   = @()
$fakeKiller = { param($p) $script:killed += [int]$p }
$fakeLogger = { param($m) $script:logs += [string]$m }
function Reset-Fakes { $script:killed = @(); $script:logs = @() }

function New-Kid {
  param([int]$Pid_, [string]$Name = 'claude.exe', [int]$CpuMs = 0, [bool]$Measured = $true, $Activity = $null)
  return @{ Pid = $Pid_; Name = $Name; WorkingSetMB = 219; CpuMs = $CpuMs; CpuMeasured = $Measured; Activity = $Activity }
}
function New-Act {
  param([int]$SpanSec, $LastWrite, [bool]$Matched = $true)
  return @{ Matched = $Matched; Worked = ($SpanSec -ge $script:LAB_WORKED_MIN_SEC); SpanSec = $SpanSec; LastWrite = $LastWrite }
}
function Run-Pass {
  param($Candidates, $State, $Now)
  Reset-Fakes
  return Invoke-LabReapPass -Candidates $Candidates -Now $Now -State $State -Killer $fakeKiller -Logger $fakeLogger
}

$now = [datetime]'2026-08-22 22:32:11'

Write-Host '[1] the accident of 2026-08-22 22:32 (session 0ebedfa2) must not happen again'
# Real numbers from local\_lab_revive.log and the transcript file:
#   cmd pid 28816 / claude pid 15776 ws=219MB cpu+0ms, transcript created 16:42:16 (span 19650s),
#   last write 22:09:46 (22 min before the reap). presence said dead. It was the live commander.
$real = @(@{ ShellPid = 28816; Kids = @(New-Kid 15776 'claude.exe' 0 $true (New-Act 19650 ([datetime]'2026-08-22 22:09:46'))) })
$r = Run-Pass $real @{} $now
Check '0ebedfa2 is NOT killed' ($script:killed.Count -eq 0) ("killed=" + ($script:killed -join ','))
Check 'and it is spared on the transcript proof, not by luck' (($script:logs -join ' ') -match 'transcript proves this window WORKED') ($script:logs -join ' | ')
Check 'and a proven-live window blocks a second spawn' ($r.Busy -eq 1) ("busy=" + $r.Busy)

Write-Host '[2] HQ spec 1: presence dead + claude alive + 0 CPU, FIRST time -> do not kill'
$z = @(@{ ShellPid = 100; Kids = @(New-Kid 200 'claude.exe' 0 $true (New-Act 4 ([datetime]'2026-08-22 22:31:00'))) })
$r1 = Run-Pass $z @{} $now
Check 'first 0-CPU pass does not kill' ($script:killed.Count -eq 0) ("killed=" + ($script:killed -join ','))
Check 'it is recorded as a watch, 1 of 3' ($r1.State['100'].Zombie -eq 1 -and $r1.Watched -eq 1) ("zombie=" + $r1.State['100'].Zombie)
Check 'the log says watching, and the old death sentence is not printed' ((($script:logs -join ' ') -match 'WATCHING 1/3') -and -not (($script:logs -join ' ') -match 'deaf zombie, reaping')) ($script:logs -join ' | ')

Write-Host '[3] HQ spec 2: same pid, N consecutive 0-CPU passes -> it does die'
$r2 = Run-Pass $z $r1.State $now
Check 'second pass still spares' ($script:killed.Count -eq 0) ("killed=" + ($script:killed -join ','))
$r3 = Run-Pass $z $r2.State $now
Check 'third pass reaps the shell and its child' (($script:killed -contains 100) -and ($script:killed -contains 200)) ("killed=" + ($script:killed -join ','))
Check 'and says why (3 consecutive passes)' (($script:logs -join ' ') -match '3 consecutive passes at 0 CPU') ($script:logs -join ' | ')

Write-Host '[4] the streak must be CONSECUTIVE (one live sample clears it)'
$busy = @(@{ ShellPid = 100; Kids = @(New-Kid 200 'claude.exe' 31 $true (New-Act 4 ([datetime]'2026-08-22 22:31:00'))) })
$rb = Run-Pass $busy $r2.State $now      # 2 strikes on the books, then cpu+31ms like 22:52 did
Check 'a CPU-burning pass resets the zombie count' ($rb.State['100'].Zombie -eq 0) ("zombie=" + $rb.State['100'].Zombie)
$rc = Run-Pass $z $rb.State $now
Check 'so the next 0-CPU pass starts over at 1 and does not kill' (($rc.State['100'].Zombie -eq 1) -and ($script:killed.Count -eq 0)) ("zombie=" + $rc.State['100'].Zombie + " killed=" + ($script:killed -join ','))

Write-Host '[5] the corpses still die (we did not just disable the reaper)'
$corpse = @(@{ ShellPid = 300; Kids = @(New-Kid 301 'conhost.exe' 0 $true $null) })
$r = Run-Pass $corpse @{} $now
Check 'a shell with no claude.exe is reaped on the FIRST pass' (($script:killed -contains 300) -and $r.Reaped -eq 1) ("killed=" + ($script:killed -join ','))
$stuck = @(@{ ShellPid = 400; Kids = @(New-Kid 401 'claude.exe' 5 $true $null) })
$r = Run-Pass $stuck @{ '400' = @{ Spare = 18; Zombie = 0 } } $now
Check 'a shell spared past SPARE_MAX is still reaped' ($script:killed -contains 400) ("killed=" + ($script:killed -join ','))
$boot = @(@{ ShellPid = 500; Kids = @(New-Kid 501 'claude.exe' 0 $true (New-Act 3 ([datetime]'2026-08-22 22:17:00'))) })
$r = Run-Pass $boot @{ '500' = @{ Spare = 0; Zombie = 2 } } $now
Check 'a window that only ever wrote its boot burst is NOT protected by the transcript' ($script:killed -contains 500) ("killed=" + ($script:killed -join ','))

Write-Host '[6] never kill on an unknown (fail-open)'
$unk = @(@{ ShellPid = 600; Kids = @(New-Kid 601 'claude.exe' 0 $false $null) })
$r = Run-Pass $unk @{ '600' = @{ Spare = 0; Zombie = 99 } } $now
Check 'CPU unmeasurable -> spared even with a long streak on the books' (($script:killed.Count -eq 0) -and $r.Spared -eq 1) ("killed=" + ($script:killed -join ','))
Check 'but unmeasurable does NOT block a spawn' ($r.Busy -eq 0) ("busy=" + $r.Busy)
$stale = @(@{ ShellPid = 700; Kids = @(New-Kid 701 'claude.exe' 0 $true (New-Act 19650 ([datetime]'2026-08-22 09:00:00'))) })
$r = Run-Pass $stale @{} $now
Check 'a worked window silent 13h no longer counts as proof (it gets watched, not spared)' ($r.Watched -eq 1 -and $script:killed.Count -eq 0) ("watched=" + $r.Watched)

Write-Host '[7] transcript pairing (Get-LabWindowActivity) picks the window own transcript'
$files = @(
  [pscustomobject]@{ Name = 'other.jsonl';    CreationTime = [datetime]'2026-08-22 12:00:00'; LastWriteTime = [datetime]'2026-08-22 22:30:00' },
  [pscustomobject]@{ Name = '0ebedfa2.jsonl'; CreationTime = [datetime]'2026-08-22 16:42:16'; LastWriteTime = [datetime]'2026-08-22 22:09:46' }
)
$a = Get-LabWindowActivity -Files $files -StartTime ([datetime]'2026-08-22 16:42:13')
Check 'matched the transcript created 3s after the process' ($a.Matched -and $a.SpanSec -eq 19650) ("matched=" + $a.Matched + " span=" + $a.SpanSec)
$a2 = Get-LabWindowActivity -Files $files -StartTime ([datetime]'2026-08-22 20:00:00')
Check 'no transcript within the window -> Matched=false (unknown is not a verdict)' (-not $a2.Matched) ("matched=" + $a2.Matched)
$a3 = Get-LabWindowActivity -Files @() -StartTime ([datetime]'2026-08-22 16:42:13')
Check 'unreadable transcript dir -> Matched=false' (-not $a3.Matched) 'empty file list'

Write-Host '[8] HQ spec 3: the pre-warm must stop reporting ok when it failed'
$blob = "Credit balance is too low`n"
$v = Get-LabPrewarmVerdict -Blob $blob -CredsBefore ([datetime]'2026-08-22 20:00:00') -CredsAfter ([datetime]'2026-08-22 20:00:00')
$line = Format-LabPrewarmLog $v
Check '"Credit balance is too low" -> FAILED' ($v -eq 'FAILED') ("verdict=" + $v)
Check 'and the log line says FAILED, not ok' (($line -match 'FAILED') -and -not ($line -match 'pre-warm ok')) $line
$v2 = Get-LabPrewarmVerdict -Blob 'pong' -CredsBefore ([datetime]'2026-08-22 20:00:00') -CredsAfter ([datetime]'2026-08-22 20:00:00')
Check 'output but creds did not advance -> unverified, not ok' ($v2 -eq 'unverified') ("verdict=" + $v2)
Check 'and that line refuses to call it ok' ((Format-LabPrewarmLog $v2) -match 'UNVERIFIED') (Format-LabPrewarmLog $v2)
$v3 = Get-LabPrewarmVerdict -Blob 'pong' -CredsBefore ([datetime]'2026-08-22 20:00:00') -CredsAfter ([datetime]'2026-08-22 20:05:00')
Check 'creds mtime advanced -> ok (positive proof)' ($v3 -eq 'ok') ("verdict=" + $v3)
$v4 = Get-LabPrewarmVerdict -Blob 'API Error: 401' -CredsBefore $null -CredsAfter ([datetime]'2026-08-22 20:05:00')
Check 'an explicit rejection outranks a refreshed file' ($v4 -eq 'FAILED') ("verdict=" + $v4)

Write-Host '[9] mutation: swing the real constants and watch the guards fall'
$origZ = $script:LAB_ZOMBIE_MAX
try {
  $script:LAB_ZOMBIE_MAX = 1
  $r = Run-Pass $z @{} $now
  Check 'HQ spec 4: with ZOMBIE_MAX=1 the first 0-CPU pass kills again (check [2] is load-bearing)' ($script:killed -contains 100) ("killed=" + ($script:killed -join ','))
} finally { $script:LAB_ZOMBIE_MAX = $origZ }
$r = Run-Pass $z @{} $now
Check 'and it is restored' ($script:killed.Count -eq 0) ("killed=" + ($script:killed -join ','))

$origW = $script:LAB_PREWARM_FAIL
try {
  $script:LAB_PREWARM_FAIL = 'Please run /login|Not logged in|401|Invalid API key|authentication_error'
  $vm = Get-LabPrewarmVerdict -Blob $blob -CredsBefore ([datetime]'2026-08-22 20:00:00') -CredsAfter ([datetime]'2026-08-22 20:05:00')
  Check 'HQ spec 5: drop "Credit balance" from the failure words and check [8] falls' ($vm -ne 'FAILED') ("verdict=" + $vm)
} finally { $script:LAB_PREWARM_FAIL = $origW }
$origSpan = $script:LAB_WORKED_MIN_SEC
try {
  $script:LAB_WORKED_MIN_SEC = 999999
  # rebuild the activity AFTER the swing - Worked is decided when the transcript is read
  $realM = @(@{ ShellPid = 28816; Kids = @(New-Kid 15776 'claude.exe' 0 $true (New-Act 19650 ([datetime]'2026-08-22 22:09:46'))) })
  $rm = Run-Pass $realM @{ '28816' = @{ Spare = 0; Zombie = 2 } } $now
  Check 'mutation: raise the worked-span bar and 0ebedfa2 loses its protection' ($script:killed -contains 28816) ("killed=" + ($script:killed -join ','))
} finally { $script:LAB_WORKED_MIN_SEC = $origSpan }
$origStale = $script:LAB_STALE_HOURS
try {
  $script:LAB_STALE_HOURS = 0.1
  $rs = Run-Pass $real @{ '28816' = @{ Spare = 0; Zombie = 2 } } $now
  Check 'mutation: shrink the staleness grace and the same window dies (check [1] rides on it)' ($script:killed -contains 28816) ("killed=" + ($script:killed -join ','))
} finally { $script:LAB_STALE_HOURS = $origStale }
$rz = Run-Pass $real @{ '28816' = @{ Spare = 0; Zombie = 2 } } $now
Check 'both restored: 0ebedfa2 survives even with 2 strikes on the books' ($script:killed.Count -eq 0) ("killed=" + ($script:killed -join ','))

Write-Host ''
Write-Host ("PASS=" + $script:pass + " FAIL=" + $script:fail)
if ($script:fail -gt 0) { exit 1 }
exit 0
