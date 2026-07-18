# Re-register scheduled tasks for the folder rename (go5-maker -> 5SecMovieMaker).
# Ordered by 手順書_受信基盤切替_段階2.md §5 / 改名移行台本. ASCII-only on purpose
# (PS5.1 reads BOM-less ps1 as cp932; Japanese literals here would corrupt).
#
# What it does:
#   1. Finds every scheduled task whose Execute/Arguments/WorkingDirectory contains OldRoot
#      (matching is by CONTENT, not task name -> future tasks are caught automatically,
#       per the freeze-time-inventory principle).
#   2. Rewrites OldRoot -> NewRoot in all actions, re-registers the task in place,
#      preserving triggers/settings/principal.
#   3. Optionally fires tasks and verifies LastTaskResult=0 (registration alone proves
#      nothing - a task that never fired is an unverified safety net).
#
# Default is DRY-RUN. Nothing changes without -Apply.
#
# Usage:
#   powershell -File scripts\maintenance\reregister_tasks.ps1                       # dry-run
#   powershell -File scripts\maintenance\reregister_tasks.ps1 -Apply               # rewrite + register
#   powershell -File scripts\maintenance\reregister_tasks.ps1 -Apply -Fire go5_context_budget_weekly,go5_build_knowledge_daily
#   powershell -File scripts\maintenance\reregister_tasks.ps1 -Apply -FireAll      # fire every rewritten task (careful: daemons/sales too)

param(
    [string]$OldRoot = 'D:\SougouStartFolder\go5-maker',
    [string]$NewRoot = 'D:\SougouStartFolder\5SecMovieMaker',
    [switch]$Apply,
    [string[]]$Fire = @(),
    [switch]$FireAll
)

$ErrorActionPreference = 'Stop'

# When invoked via `powershell -File`, a comma-joined value arrives as ONE string
# ("a,b" is not parsed into string[]). Split defensively so both call styles work.
$Fire = @($Fire | ForEach-Object { $_ -split ',' } | Where-Object { $_ })

function Rewrite([string]$s) {
    if ($null -eq $s -or $s -eq '') { return $s }
    return $s.Replace($OldRoot, $NewRoot)
}

$hits = @()
foreach ($t in Get-ScheduledTask) {
    $match = $false
    foreach ($a in $t.Actions) {
        foreach ($v in @($a.Execute, $a.Arguments, $a.WorkingDirectory)) {
            if ($v -and $v.Contains($OldRoot)) { $match = $true }
        }
    }
    if ($match) { $hits += $t }
}

"Tasks referencing OldRoot: $($hits.Count)  (OldRoot=$OldRoot)"
if ($hits.Count -eq 0) { "Nothing to do."; exit 0 }

$results = @()
foreach ($t in $hits) {
    "-- $($t.TaskName)"
    $newActions = @()
    foreach ($a in $t.Actions) {
        $exe = Rewrite $a.Execute
        $arg = Rewrite $a.Arguments
        $wd  = Rewrite $a.WorkingDirectory
        foreach ($pair in @(@('Execute', $a.Execute, $exe), @('Arguments', $a.Arguments, $arg), @('WorkingDirectory', $a.WorkingDirectory, $wd))) {
            if ($pair[1] -ne $pair[2]) { "     {0}: {1}  ->  {2}" -f $pair[0], $pair[1], $pair[2] }
        }
        $params = @{ Execute = $exe }
        if ($arg) { $params['Argument'] = $arg }
        if ($wd)  { $params['WorkingDirectory'] = $wd }
        $newActions += New-ScheduledTaskAction @params
    }
    if ($Apply) {
        Register-ScheduledTask -TaskName $t.TaskName -TaskPath $t.TaskPath -Action $newActions `
            -Trigger $t.Triggers -Settings $t.Settings -Principal $t.Principal -Force | Out-Null
        "     registered OK"
        $results += $t.TaskName
    }
}

if (-not $Apply) { ""; "DRY-RUN: no changes made. Re-run with -Apply."; exit 0 }

# --- fire + verify ---
$toFire = @()
if ($FireAll) { $toFire = $results }
elseif ($Fire.Count -gt 0) { $toFire = $Fire }
if ($toFire.Count -eq 0) {
    ""
    "Registered $($results.Count) task(s). No fire-verify requested (-Fire name,... or -FireAll)."
    "Remember: a task that never fired is an unverified safety net."
    exit 0
}

""
"Fire-verify: $($toFire -join ', ')"
Start-Sleep -Seconds 3   # let the Task Scheduler service settle after bulk re-registration
                         # (firing immediately after Register raised transient 0x80070002 - observed 2026-07-18)
$failed = @()
foreach ($name in $toFire) {
    $started = $false
    foreach ($try in 1..3) {
        try { Start-ScheduledTask -TaskName $name -ErrorAction Stop; $started = $true; break }
        catch { Start-Sleep -Seconds 2 }
    }
    if (-not $started) {
        "  {0,-34} START FAILED after 3 tries" -f $name
        $failed += $name
        continue
    }
    $n = 0
    do { Start-Sleep -Seconds 2; $n++; $st = (Get-ScheduledTask -TaskName $name).State } while ($st -eq 'Running' -and $n -lt 60)
    $rc = (Get-ScheduledTaskInfo -TaskName $name).LastTaskResult
    "  {0,-34} LastTaskResult={1}" -f $name, $rc
    # 0 = success; 267009 = still running (long daemon tasks) - report but do not fail
    if ($rc -ne 0 -and $rc -ne 267009) { $failed += $name }
}
""
if ($failed.Count -gt 0) { "FAILED: $($failed -join ', ')"; exit 1 }
"All fired tasks verified (rc=0 or still-running)."
exit 0
