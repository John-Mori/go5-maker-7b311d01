# quota_guard.ps1 - one-command, reversible flip for the morning scheduled-task peak.
#
# WHY (2026-08-23, order from kenkyujo-HQ msg 1540938360464474273):
#   The weekly plan quota is burning at ~2.25x the wall-clock pace. HQ asked aegis-gl to make
#   the 08:00 cluster "thin-able / shift-able with one command, tonight".
#   This script is that switch. It NEVER deletes a task (C-003): it only disables/enables and
#   moves StartBoundary, and it writes the original state to a JSON file BEFORE the first change
#   so that -Action restore puts everything back byte-for-byte.
#
# WHAT IT IS NOT:
#   Measurement (see the report attached to the same order) says the cron cluster is NOT the
#   main burner: on 08/22 the identical triggers produced 3 enqueued items / 60 API calls
#   (0.8% of the week). Keep that in mind before expecting a big saving from -Action thin.
#
# USAGE (run from anywhere; paths are absolute):
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\_daemons\quota_guard.ps1 -Action status
#   ... -Action stagger      # spread the 08:00 cluster over 08:00 / 08:30 / 09:00 / 09:30 / 10:00 / 10:30
#   ... -Action thin         # disable the whole morning cluster (one day off; restore puts it back)
#   ... -Action restore      # undo everything this script ever changed
#
# ASCII-only on purpose: PowerShell files launched by Task Scheduler have bitten us on encoding.

param(
    [ValidateSet('status','stagger','thin','restore')]
    [string]$Action = 'status'
)

$ErrorActionPreference = 'Stop'
$Root      = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$StatePath = Join-Path $Root 'local\_quota_guard_state.json'

# The managed set. Order matters for 'stagger' (index -> offset).
$Managed = @(
    'go5_daily_reflection_0500',
    'go5_comp_frames_daily',
    'go5_competitor_daily_0800',
    'go5_daily_report_0800',
    'go5_product_daily_pick_0800',
    'go5_reaction_watch_0800',
    'go5_se_daily_review_0800',
    'go5_kaizen_daily_0810'
)
# Only these get moved by 'stagger' (the 08:00 pile-up). 05:00 and 06:40 are already alone.
$StaggerPlan = [ordered]@{
    'go5_competitor_daily_0800'   = '08:00:00'
    'go5_daily_report_0800'       = '08:30:00'
    'go5_product_daily_pick_0800' = '09:00:00'
    'go5_reaction_watch_0800'     = '09:30:00'
    'go5_se_daily_review_0800'    = '10:00:00'
    'go5_kaizen_daily_0810'       = '10:30:00'
}

function Get-Snapshot($name) {
    $t = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
    if (-not $t) { return $null }
    $bounds = @()
    foreach ($tr in $t.Triggers) { if ($tr.StartBoundary) { $bounds += [string]$tr.StartBoundary } }
    return [pscustomobject]@{ name = $name; state = [string]$t.State; startBoundaries = $bounds }
}

# Save the pre-change state exactly once. Later flips must not overwrite it with an already-flipped
# state -- that is how a "restore" silently restores the broken state.
function Save-OriginalOnce {
    if (Test-Path $StatePath) { return }
    $snap = @()
    foreach ($n in $Managed) { $s = Get-Snapshot $n; if ($s) { $snap += $s } }
    $doc = [pscustomobject]@{
        savedAt = (Get-Date).ToString('yyyy-MM-ddTHH:mm:ssK')
        by      = 'aegis-gl / quota_guard.ps1'
        tasks   = $snap
    }
    $doc | ConvertTo-Json -Depth 6 | Set-Content -Path $StatePath -Encoding UTF8
    Write-Host ("saved original state -> {0}" -f $StatePath)
}

function Set-StartTime($name, $hhmmss) {
    $t = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
    if (-not $t) { Write-Host ("  MISSING {0}" -f $name); return }
    $changed = $false
    foreach ($tr in $t.Triggers) {
        if (-not $tr.StartBoundary) { continue }
        $old = [string]$tr.StartBoundary
        # StartBoundary looks like 2026-08-23T08:00:00+09:00 ; replace only the time part.
        $new = [regex]::Replace($old, 'T\d{2}:\d{2}:\d{2}', ('T' + $hhmmss))
        if ($new -ne $old) { $tr.StartBoundary = $new; $changed = $true }
    }
    if ($changed) {
        Set-ScheduledTask -TaskName $t.TaskName -TaskPath $t.TaskPath -Trigger $t.Triggers | Out-Null
        Write-Host ("  moved  {0} -> {1}" -f $name, $hhmmss)
    } else {
        Write-Host ("  same   {0} already {1}" -f $name, $hhmmss)
    }
}

function Show-Status {
    Write-Host "== quota_guard status =="
    foreach ($n in $Managed) {
        $t = Get-ScheduledTask -TaskName $n -ErrorAction SilentlyContinue
        if (-not $t) { Write-Host ("  {0,-30} MISSING" -f $n); continue }
        $i = Get-ScheduledTaskInfo -TaskName $t.TaskName -TaskPath $t.TaskPath -ErrorAction SilentlyContinue
        $tm = ($t.Triggers | ForEach-Object { if ($_.StartBoundary) { ($_.StartBoundary -split 'T')[1] } }) -join ','
        Write-Host ("  {0,-30} {1,-8} start={2,-16} next={3}" -f $n, $t.State, $tm, $i.NextRunTime)
    }
    if (Test-Path $StatePath) {
        Write-Host ("  [state file present] {0}  -> -Action restore will undo" -f $StatePath)
    } else {
        Write-Host "  [no state file] nothing has been flipped by this script"
    }
}

switch ($Action) {

    'status' { Show-Status }

    'stagger' {
        Save-OriginalOnce
        Write-Host "== stagger: spread the 08:00 cluster =="
        foreach ($k in $StaggerPlan.Keys) { Set-StartTime $k $StaggerPlan[$k] }
        Show-Status
    }

    'thin' {
        Save-OriginalOnce
        Write-Host "== thin: disable the morning cluster (reversible; task is NOT deleted) =="
        foreach ($n in $Managed) {
            $t = Get-ScheduledTask -TaskName $n -ErrorAction SilentlyContinue
            if (-not $t) { Write-Host ("  MISSING {0}" -f $n); continue }
            Disable-ScheduledTask -TaskName $t.TaskName -TaskPath $t.TaskPath | Out-Null
            Write-Host ("  disabled {0}" -f $n)
        }
        Show-Status
    }

    'restore' {
        if (-not (Test-Path $StatePath)) { Write-Host "no state file: nothing to restore"; Show-Status; break }
        $doc = Get-Content -Path $StatePath -Raw -Encoding UTF8 | ConvertFrom-Json
        Write-Host ("== restore from {0} (saved {1}) ==" -f $StatePath, $doc.savedAt)
        foreach ($s in $doc.tasks) {
            $t = Get-ScheduledTask -TaskName $s.name -ErrorAction SilentlyContinue
            if (-not $t) { Write-Host ("  MISSING {0}" -f $s.name); continue }
            if ($s.startBoundaries -and $s.startBoundaries.Count -gt 0) {
                $i = 0
                foreach ($tr in $t.Triggers) {
                    if ($tr.StartBoundary -and $i -lt $s.startBoundaries.Count) {
                        $tr.StartBoundary = [string]$s.startBoundaries[$i]; $i++
                    }
                }
                Set-ScheduledTask -TaskName $t.TaskName -TaskPath $t.TaskPath -Trigger $t.Triggers | Out-Null
            }
            if ($s.state -eq 'Disabled') {
                Disable-ScheduledTask -TaskName $t.TaskName -TaskPath $t.TaskPath | Out-Null
            } else {
                Enable-ScheduledTask -TaskName $t.TaskName -TaskPath $t.TaskPath | Out-Null
            }
            Write-Host ("  restored {0} -> {1} {2}" -f $s.name, $s.state, ($s.startBoundaries -join ','))
        }
        # Keep the file as a .bak so a bad restore is still traceable, then clear the live one.
        Move-Item -Path $StatePath -Destination ($StatePath + '.bak_' + (Get-Date).ToString('yyyyMMdd_HHmmss')) -Force
        Show-Status
    }
}
