# sla_nightly.ps1 - nightly per-room response-latency report (P6, approved 2026-07-18).
# Runs sla_report.py --send (posts to the QA channel as Metal Gear Mk.II).
# ASCII-only on purpose (PS 5.1 reads BOM-less ps1 as ANSI; Japanese here would corrupt).
$root = 'D:\SougouStartFolder\go5-maker'
Set-Location $root
python scripts/kaizen/sla_report.py --send *>> (Join-Path $root 'local\sla_nightly.log')
