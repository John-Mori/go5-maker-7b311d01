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
$KeepCount = 14
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
