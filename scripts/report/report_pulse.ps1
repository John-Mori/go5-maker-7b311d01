# report_pulse.ps1 - fire the progress-pulse post (HQ dispatch / Chami 2026-08-01: no autonomous reporting).
# Runs report_pulse.py --send: pushes the UNREPORTED change_log entries since the last marker
# as a <=5-line digest to the report-notify channel (Otacon). Silent when nothing new (not a nag).
# ASCII-only on purpose (PS 5.1 reads BOM-less ps1 as ANSI; Japanese here would corrupt the file).
# UTF-8 is forced for the child + the log so the Japanese body/log stay readable (same fix as daily_report.ps1).
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $root
$env:PYTHONIOENCODING = 'utf-8'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$log = Join-Path $root 'local\report_pulse.log'
$out = & python scripts/report/report_pulse.py --send 2>&1
$stamp = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
Add-Content -Path $log -Value "===== $stamp =====" -Encoding UTF8
Add-Content -Path $log -Value $out -Encoding UTF8
