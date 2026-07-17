# go5 local/ backup to Google Drive (dated snapshot, create-only)
# Why dated snapshots instead of a mirror: a mirror propagates an accidental
# local deletion to the backup on the next run. Snapshots do not.
# ASCII-only on purpose (see memory: executable ps1 must stay ASCII).

$ErrorActionPreference = 'Stop'

$Src       = 'D:\SougouStartFolder\go5-maker\local'
$LogFile   = 'D:\SougouStartFolder\go5-maker\local\backup.log'
# Config lives under local/ (gitignored), NOT next to this script: the destination
# contains a strategy folder name, and scripts/ is tracked by a PUBLIC repo.
# It was pushed once (QA found it 2026-07-17); the original design already said local/.
$DestFile  = 'D:\SougouStartFolder\go5-maker\local\backup_dest.txt'
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
# resolution would point retention's Remove-Item at the wrong tree. Property-based
# check (no hardcoded Japanese folder name; this file must stay ASCII).
if (-not (Test-Path (Join-Path $driveRoot.FullName $rel))) {
    Write-Log ("ABORT: resolved drive root '{0}' does not contain the expected destination. Backup skipped." -f $driveRoot.FullName)
    exit 1
}
$BackupRoot = Join-Path $driveRoot.FullName $rel
$stamp = Get-Date -Format 'yyyy-MM-dd'
$dest  = Join-Path $BackupRoot $stamp

$free = (Get-PSDrive -Name G).Free / 1GB
if ($free -lt $MinFreeGB) {
    Write-Log ("ABORT: only {0:N2} GB free on G:. Need {1} GB. Backup skipped." -f $free, $MinFreeGB)
    exit 1
}

New-Item -ItemType Directory -Path $dest -Force | Out-Null

# /E recurse incl. empty dirs, /R:2 /W:5 keep retries short, /NP no per-file progress.
# Deliberately NOT /MIR: never delete anything at the destination.
$null = robocopy $Src $dest /E /R:2 /W:5 /NP /NDL /NFL /NJH /NJS
$rc = $LASTEXITCODE
if ($rc -ge 8) {
    Write-Log "FAIL: robocopy exit $rc"
    exit 1
}

$files = @(Get-ChildItem $dest -Recurse -File -ErrorAction SilentlyContinue)
$sizeMB = [math]::Round((($files | Measure-Object Length -Sum).Sum / 1MB), 1)
Write-Log ("OK: {0} -> {1} ({2} files, {3} MB, robocopy rc={4})" -f $Src, $dest, $files.Count, $sizeMB, $rc)

# --- Sensitive dirs: monthly PERMANENT snapshot (never touched by retention) ---
# Why (dream-care design P1-5, Chami approved 2026-07-17): retention was cut 14 -> 3 days.
# With create-only dated snapshots, a file deleted locally silently vanishes from every
# surviving snapshot after 3 days. For dreams/past/health that means Chami's own history
# is gone with no way back. These are a few KB, so a monthly keeper costs effectively zero.
# Kept OUTSIDE $BackupRoot so the retention block above can never reach it.
$SensitiveDirs = @('dreams', 'past', 'health')
$keepRoot = Join-Path $driveRoot.FullName 'go5-backup-keep'
$month    = Get-Date -Format 'yyyy-MM'
foreach ($d in $SensitiveDirs) {
    $srcDir = Join-Path $Src $d
    if (-not (Test-Path -LiteralPath $srcDir)) { continue }
    $dstDir = Join-Path (Join-Path $keepRoot $month) $d
    if (Test-Path -LiteralPath $dstDir) { continue }   # already kept this month = idempotent
    New-Item -ItemType Directory -Path $dstDir -Force | Out-Null
    $null = robocopy $srcDir $dstDir /E /R:2 /W:5 /NP /NDL /NFL /NJH /NJS
    if ($LASTEXITCODE -ge 8) { Write-Log ("WARN: monthly keep failed for {0} (rc={1})" -f $d, $LASTEXITCODE) }
    else { Write-Log ("keep: monthly permanent snapshot {0}/{1}" -f $month, $d) }
}

# --- Deletion detector: report files that vanished from the SOURCE ---
# Compares file NAMES only against the previous snapshot. Contents are never read
# (these dirs are sensitive). Runs BEFORE retention so the last copy still exists when
# the alert goes out. Alert only - this script never restores or deletes anything.
$prev = @(Get-ChildItem $BackupRoot -Directory -ErrorAction SilentlyContinue |
          Where-Object { $_.Name -match '^\d{4}-\d{2}-\d{2}$' -and $_.FullName -ne $dest } |
          Sort-Object Name -Descending | Select-Object -First 1)
if ($prev.Count -gt 0) {
    $prevRoot = $prev[0].FullName
    $prevRel = @(Get-ChildItem $prevRoot -Recurse -File -ErrorAction SilentlyContinue |
                 ForEach-Object { $_.FullName.Substring($prevRoot.Length).TrimStart('\') })
    $curRel  = @(Get-ChildItem $dest -Recurse -File -ErrorAction SilentlyContinue |
                 ForEach-Object { $_.FullName.Substring($dest.Length).TrimStart('\') })
    $curSet = @{}; foreach ($p in $curRel) { $curSet[$p] = $true }
    $gone = @($prevRel | Where-Object { -not $curSet.ContainsKey($_) })
    if ($gone.Count -gt 0) {
        Write-Log ("DETECT: {0} file(s) disappeared from source since {1}" -f $gone.Count, $prev[0].Name)
        $list = ($gone | Select-Object -First 20) -join "`n"
        $more = if ($gone.Count -gt 20) { "`n(and {0} more)" -f ($gone.Count - 20) } else { '' }
        $body = "(auto) Backup detected {0} file(s) removed from local/ since {1}. Names only, contents not read. If unintended, the copy still exists in the latest snapshot - restore before it ages out (retention keeps {2}).`n{3}{4}" -f $gone.Count, $prev[0].Name, $KeepCount, $list, $more
        $tmp = Join-Path $env:TEMP ("go5_backup_gone_{0}.txt" -f (Get-Date -Format 'yyyyMMddHHmmss'))
        Set-Content -LiteralPath $tmp -Value $body -Encoding utf8
        # Persona name is Japanese ("Metal Gear Mk.II"). This file must stay ASCII-only
        # (PS 5.1 reads a no-BOM file as the system ANSI codepage; non-ASCII here corrupts
        # parsing), so pass it as an escaped literal instead of writing the glyphs.
        $persona = [regex]::Unescape('\u30E1\u30BF\u30EB\u30AE\u30A2Mk.II')
        try {
            & python 'D:\SougouStartFolder\go5-maker\scripts\discord\persona_send.py' `
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

# robocopy rc 1-7 means success (files copied). Without this the caller sees
# robocopy's rc as our exit code and reads a good run as a failure.
exit 0
