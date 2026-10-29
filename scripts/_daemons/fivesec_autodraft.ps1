# fivesec_autodraft.ps1 - launcher for the morning unattended draft run (beta-5c, system-engineer 2026-10-29).
# Requested by 5S dept (Klopp via Modric). Body = fivesec_autodraft.py: reads today's
# LocalData\fivesec\daily_pick_YYYYMMDD.json and makes one draft per item in the dedicated Chrome profile.
# Called every 30 min 06:30-09:00; the ledger makes repeated calls a no-op once all items are done.
# --allow-no-sync was removed 2026-10-29: the sync fields are set in the dedicated profile
# (probe 19:41 configured=true), so cloud:false counts as a failure and unset sync stops the run.
# ASCII-only (PS 5.1 codepage safety).
$ErrorActionPreference = 'Stop'
$env:PYTHONIOENCODING = 'utf-8'
if ($PSScriptRoot) { $here = $PSScriptRoot } else { $here = Split-Path -Parent $MyInvocation.MyCommand.Definition }
Set-Location 'D:\SougouStartFolder\5SecMovieMaker'
& py -3.12 (Join-Path $here 'fivesec_autodraft.py') --notify
exit $LASTEXITCODE
