# go5 backup to Google Drive (dated snapshot, create-only) - multi-source.
# Sources: go5-maker\local  AND  00_AI-HQ (added 2026-07-19, lab order: HQ left the
# backup path when HR moved there; local git protects history but not disk loss).
# Why dated snapshots instead of a mirror: a mirror propagates an accidental
# local deletion to the backup on the next run. Snapshots do not.
# ASCII-only on purpose (see memory: executable ps1 must stay ASCII).

$ErrorActionPreference = 'Stop'

$RepoRoot  = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$LogFile   = Join-Path $RepoRoot 'local\backup.log'
# Config lives under local/ (gitignored), NOT next to this script: the destination
# contains a strategy folder name, and scripts/ is tracked by a PUBLIC repo.
$DestFile  = Join-Path $RepoRoot 'local\backup_dest.txt'
# 3 per Chami (2026-07-17 kaizen ch): "14 days not needed, 3 is enough, delete the rest"
$KeepCount = 3
$MinFreeGB = 2

function Write-Log($msg) {
    $line = "{0} {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg
    Add-Content -Path $LogFile -Value $line -Encoding utf8
    Write-Output $line
}

# Resolve "My Drive" without hardcoding its localized name (it is Japanese here).
$driveRoot = Get-ChildItem 'G:\' -Directory -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $driveRoot) {
    Write-Log "ABORT: Google Drive (G:) not mounted or empty. Backup skipped."
    exit 1
}

# The destination lives in backup_dest.txt (UTF-8) rather than inline, because
# this file must stay ASCII: PS 5.1 reads a BOM-less .ps1 as ANSI (cp932 here)
# and would mangle the Japanese folder names into a path that does not exist.
if (-not (Test-Path $DestFile)) {
    Write-Log "ABORT: destination config missing: $DestFile"
    exit 1
}
$rel = (Get-Content $DestFile -Encoding UTF8 | Where-Object { $_.Trim() } | Select-Object -First 1).Trim()
if (-not $rel) {
    Write-Log "ABORT: destination config is empty: $DestFile"
    exit 1
}

# Validate the resolved drive root actually contains our destination path.
# QA 2026-07-17: if a Shared Drive ever appears first under G:\, blind "first dir"
# resolution would point retention's Remove-Item at the wrong tree.
if (-not (Test-Path (Join-Path $driveRoot.FullName $rel))) {
    Write-Log ("ABORT: resolved drive root '{0}' does not contain the expected destination. Backup skipped." -f $driveRoot.FullName)
    exit 1
}

$free = (Get-PSDrive -Name G).Free / 1GB
if ($free -lt $MinFreeGB) {
    Write-Log ("ABORT: only {0:N2} GB free on G:. Need {1} GB. Backup skipped." -f $free, $MinFreeGB)
    exit 1
}

# Config keeps its historical form (ends with '\local'). Derive the base so both
# sources land side by side: <base>\local\YYYY-MM-DD and <base>\00_AI-HQ\YYYY-MM-DD.
$destBase = Join-Path $driveRoot.FullName (Split-Path $rel -Parent)
$keepRoot = Join-Path $driveRoot.FullName 'go5-backup-keep'
$stamp    = Get-Date -Format 'yyyy-MM-dd'
$month    = Get-Date -Format 'yyyy-MM'

# --- One tree = snapshot + monthly sensitive keep + deletion detect + retention ---
# $SensitiveRel: dirs (relative to $Src) copied once a month to a PERMANENT area the
# retention below can never reach. Rationale (P1-5, Chami approved 2026-07-17):
# retention is 3 days; a locally deleted file silently vanishes from every surviving
# snapshot. For irreplaceable personal/character history that is unacceptable.
# $KeepSub: '' for local (historical layout, keeps existing July keeps idempotent),
# source name for others (avoids leaf-name collisions between sources).
function Backup-Tree([string]$Label, [string]$Src, [string]$BackupRoot,
                     [string[]]$SensitiveRel, [string]$KeepSub) {
    if (-not (Test-Path -LiteralPath $Src)) {
        Write-Log ("WARN: source missing, skipped: {0}" -f $Src)
        return
    }
    $dest = Join-Path $BackupRoot $stamp
    New-Item -ItemType Directory -Path $dest -Force | Out-Null

    # /E recurse incl. empty dirs. Deliberately NOT /MIR: never delete at destination.
    $null = robocopy $Src $dest /E /R:2 /W:5 /NP /NDL /NFL /NJH /NJS
    $rc = $LASTEXITCODE
    if ($rc -ge 8) {
        Write-Log ("FAIL: robocopy exit {0} for {1}" -f $rc, $Label)
        return
    }
    $files = @(Get-ChildItem $dest -Recurse -File -Force -ErrorAction SilentlyContinue)
    $sizeMB = [math]::Round((($files | Measure-Object Length -Sum).Sum / 1MB), 1)
    Write-Log ("OK: {0} -> {1} ({2} files, {3} MB, robocopy rc={4})" -f $Src, $dest, $files.Count, $sizeMB, $rc)

    # Monthly permanent snapshot for sensitive dirs (idempotent per month).
    foreach ($d in $SensitiveRel) {
        $srcDir = Join-Path $Src $d
        if (-not (Test-Path -LiteralPath $srcDir)) { continue }
        $leaf = Split-Path $d -Leaf
        $dstDir = Join-Path $keepRoot $month
        if ($KeepSub) { $dstDir = Join-Path $dstDir $KeepSub }
        $dstDir = Join-Path $dstDir $leaf
        if (Test-Path -LiteralPath $dstDir) { continue }
        New-Item -ItemType Directory -Path $dstDir -Force | Out-Null
        $null = robocopy $srcDir $dstDir /E /R:2 /W:5 /NP /NDL /NFL /NJH /NJS
        if ($LASTEXITCODE -ge 8) { Write-Log ("WARN: monthly keep failed for {0}/{1} (rc={2})" -f $Label, $leaf, $LASTEXITCODE) }
        else { Write-Log ("keep: monthly permanent snapshot {0}/{1}/{2}" -f $month, $Label, $leaf) }
    }

    # Deletion detector: names only, contents never read. Alert only, before retention,
    # so the last copy still exists when the alert goes out.
    $prev = @(Get-ChildItem $BackupRoot -Directory -ErrorAction SilentlyContinue |
              Where-Object { $_.Name -match '^\d{4}-\d{2}-\d{2}$' -and $_.FullName -ne $dest } |
              Sort-Object Name -Descending | Select-Object -First 1)
    if ($prev.Count -gt 0) {
        $prevRoot = $prev[0].FullName
        $prevRel = @(Get-ChildItem $prevRoot -Recurse -File -Force -ErrorAction SilentlyContinue |
                     ForEach-Object { $_.FullName.Substring($prevRoot.Length).TrimStart('\') })
        $curRel  = @(Get-ChildItem $dest -Recurse -File -Force -ErrorAction SilentlyContinue |
                     ForEach-Object { $_.FullName.Substring($dest.Length).TrimStart('\') })
        $curSet = @{}; foreach ($p in $curRel) { $curSet[$p] = $true }
        $gone = @($prevRel | Where-Object { -not $curSet.ContainsKey($_) })
        if ($gone.Count -gt 0) {
            Write-Log ("DETECT: {0} file(s) disappeared from {1} since {2}" -f $gone.Count, $Label, $prev[0].Name)
            $list = ($gone | Select-Object -First 20) -join "`n"
            $more = if ($gone.Count -gt 20) { "`n(and {0} more)" -f ($gone.Count - 20) } else { '' }
            $body = "(auto) Backup detected {0} file(s) removed from {1} since {2}. Names only, contents not read. If unintended, the copy still exists in the latest snapshot - restore before it ages out (retention keeps {3}).`n{4}{5}" -f $gone.Count, $Label, $prev[0].Name, $KeepCount, $list, $more
            $tmp = Join-Path $env:TEMP ("go5_backup_gone_{0}.txt" -f (Get-Date -Format 'yyyyMMddHHmmss'))
            Set-Content -LiteralPath $tmp -Value $body -Encoding utf8
            # Persona name is Japanese ("Metal Gear Mk.II"); escaped so this file stays ASCII
            # (PS 5.1 reads a no-BOM file as the system ANSI codepage; glyphs here would corrupt).
            $persona = [regex]::Unescape('\u30E1\u30BF\u30EB\u30AE\u30A2Mk.II')
            try {
                & python (Join-Path $RepoRoot 'scripts\discord\persona_send.py') `
                    --channel 'incident' --persona $persona --body-file $tmp | Out-Null
                Write-Log "DETECT: notified incident channel"
            } catch { Write-Log ("WARN: notify failed: {0}" -f $_.Exception.Message) }
            Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
        }
    }

    # Retention: keep the newest $KeepCount snapshots, drop older ones.
    $snaps = @(Get-ChildItem $BackupRoot -Directory -ErrorAction SilentlyContinue |
               Where-Object { $_.Name -match '^\d{4}-\d{2}-\d{2}$' } |
               Sort-Object Name -Descending)
    if ($snaps.Count -gt $KeepCount) {
        foreach ($old in $snaps[$KeepCount..($snaps.Count - 1)]) {
            Remove-Item $old.FullName -Recurse -Force -Confirm:$false
            Write-Log ("retention: removed old snapshot {0}" -f $old.Name)
        }
    }
}

# Source 1: go5-maker local/ (historical layout: BackupRoot comes straight from config,
# monthly keeps live directly under go5-backup-keep\YYYY-MM\<dir> as before).
Backup-Tree -Label 'local' -Src (Join-Path $RepoRoot 'local') `
    -BackupRoot (Join-Path $driveRoot.FullName $rel) `
    -SensitiveRel @('dreams', 'past', 'health') -KeepSub ''

# Source 2: 00_AI-HQ (HR personas/characters/memory = irreplaceable character context,
# so they join the monthly permanent frame; namespaced under 00_AI-HQ to avoid collisions).
# .git is included on purpose: it carries the history protection the lab set up.
Backup-Tree -Label '00_AI-HQ' -Src 'D:\SougouStartFolder\00_AI-HQ' `
    -BackupRoot (Join-Path $destBase '00_AI-HQ') `
    -SensitiveRel @('departments\hr\personas', 'departments\hr\characters', 'departments\hr\memory') `
    -KeepSub '00_AI-HQ'

# robocopy rc 1-7 means success. Task-scheduler health must read rc=0.
exit 0
