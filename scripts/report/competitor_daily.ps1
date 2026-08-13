# competitor_daily.ps1 - 08:00 JST trigger that runs the competitor daily ranking analysis
# and pushes the 5-line summary to the analysis room (shorts-analyst / Almond Eye).
# Requested by the analysis dept (msg 1537489528393171025); the unattended delivery is owned by
# platform-se because the analysis room cannot call persona_send itself (rule 4.7).
# All the Japanese body/delivery lives in competitor_daily_push.py (Python = UTF-8 safe);
# this wrapper stays ASCII-only on purpose (PS 5.1 reads a BOM-less ps1 as ANSI; Japanese here
# would corrupt the file). UTF-8 is forced for the child + the log (a log you cannot read is no log).
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $root
$env:PYTHONIOENCODING = 'utf-8'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$log = Join-Path $root 'local\competitor_daily.log'
$out = & python scripts/analysis/competitor_daily_push.py 2>&1
$stamp = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
Add-Content -Path $log -Value "===== $stamp =====" -Encoding UTF8
Add-Content -Path $log -Value $out -Encoding UTF8
