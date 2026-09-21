# winupdate_watch.ps1 - go5-maker: notify Chami on Discord when Windows Update is pending.
#
# WHY: Windows Update's automatic reboot is the single biggest threat to remote operation.
#   On 2026-07-16 it rebooted the PC at 13:17 while Chami was asleep; the lock screen stopped
#   every daemon and the Lab session (scheduled tasks are LogonType=Interactive, so nothing
#   revives until he logs in). If he is away, everything stays dead until he comes home.
#   Chami's own countermeasure is the right one: apply updates BEFORE leaving, so no reboot
#   is pending while he is out. To do that he must KNOW an update is waiting -> this notifies.
#
# WHAT: checks pending updates (Windows Update COM API) + the reboot-required flag.
#   Posts to Discord as Otacon (report-notify room) only when the state CHANGES,
#   so it never nags. Defender signature updates are ignored (they land several times a
#   day and never force a reboot) unless a reboot is actually pending.
#
# NOTE: THIS FILE MUST STAY ASCII-ONLY. PowerShell 5.1 reads a no-BOM file as the system ANSI
#   codepage; non-ASCII here corrupts parsing. The Japanese message body lives in
#   winupdate_message.py (UTF-8), which builds the text file this script sends.
$ErrorActionPreference = 'SilentlyContinue'
$root  = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$state = Join-Path $root 'local\_winupdate_state.txt'
$body  = Join-Path $root 'local\_winupdate_body.txt'
$titlesFile = Join-Path $root 'local\_winupdate_titles.txt'
$log   = Join-Path $root 'local\_winupdate.log'

function Write-Log($m) {
  $ts = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
  try { Add-Content -LiteralPath $log -Value "$ts $m" -Encoding UTF8 } catch {}
}

# --- gather pending updates ---
$titles = @()
try {
  $searcher = (New-Object -ComObject Microsoft.Update.Session).CreateUpdateSearcher()
  $result = $searcher.Search("IsInstalled=0 AND IsHidden=0")
  foreach ($u in $result.Updates) { $titles += $u.Title }
} catch {
  Write-Log ("search failed: " + $_.Exception.Message)
  exit 1
}

# Reboot-required detection: watch BOTH the Windows Update flag AND the Component Based
# Servicing (CBS) flag. CBS\RebootPending often flips true minutes BEFORE the WU flag while
# an update is being staged, so watching only the WU key made the alert say "reboot not yet
# required" when a reboot was in fact already pending (observed 2026-09-21 12:09 -> 12:15).
# PendingFileRenameOperations is deliberately NOT included: it is dominated by benign temp/
# driver file renames (58 benign entries measured 2026-09-21) and is not a WU reboot signal.
$rebootRequired = (Test-Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired') -or (Test-Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending')

# Drop Defender signature updates: they arrive several times a day and never force a reboot.
# Without this filter the watcher would nag Chami constantly and become noise (see the
# absence_watchdog false-alarm lesson: a crying-wolf alert hides the real one).
$real = @($titles | Where-Object { $_ -notmatch 'Defender|Security Intelligence' })
$realCount = $real.Count

# --- only speak when the situation CHANGES ---
$key = "r=$rebootRequired;n=$realCount"
$prev = ''
if (Test-Path -LiteralPath $state) { $prev = (Get-Content -LiteralPath $state -Raw -ErrorAction SilentlyContinue).Trim() }
if ($key -eq $prev) { Write-Log ("no change (" + $key + ")"); exit 0 }

if ($realCount -eq 0 -and -not $rebootRequired) {
  Set-Content -LiteralPath $state -Value $key -Encoding UTF8
  Write-Log 'clear (nothing pending)'
  exit 0
}

# --- hand off to python: it builds the Japanese body AND sends it as Otacon ---
# (this file must stay ASCII, so both the message text and the persona name live in python)
Set-Content -LiteralPath $titlesFile -Value ($real -join "`n") -Encoding UTF8
$rebootArg = if ($rebootRequired) { '1' } else { '0' }
$notifier = Join-Path $root 'scripts\_daemons\winupdate_message.py'
& python $notifier $rebootArg $titlesFile 2>&1 | Out-Null
if ($LASTEXITCODE -eq 0) {
  Set-Content -LiteralPath $state -Value $key -Encoding UTF8
  Write-Log ("notified (" + $key + ")")
} else {
  Write-Log ("send failed (" + $key + ") - will retry next run")
}
