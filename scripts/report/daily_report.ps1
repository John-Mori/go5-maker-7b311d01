# daily_report.ps1 - twice-daily report post (Chami ruling 2026-07-19: 00:00 and 08:00).
# Runs daily_report.py --send (posts to report-notify channel as Otacon persona).
# ASCII-only on purpose (PS 5.1 reads BOM-less ps1 as ANSI; Japanese here would corrupt).
$root = 'D:\SougouStartFolder\go5-maker'
Set-Location $root
python scripts/report/daily_report.py --send *>> (Join-Path $root 'local\daily_report.log')
