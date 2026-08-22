# kaizen_round.ps1 - weekly PDCA round for the improvement dept (Chami 2026-07-28).
# Chami: "count how many times I asked the same thing, and run PDCA on it. autonomously"
# ASCII-only on purpose (PS 5.1 reads BOM-less ps1 as ANSI; Japanese here would corrupt).
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $root
$env:PYTHONIOENCODING = 'utf-8'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8   # python's UTF-8 stdout would be mangled otherwise
$log = Join-Path $root 'local\kaizen_round.log'
$body = 'D:\SougouStartFolder\00_AI-HQ\departments\kaizen\PDCA_ROUND.md'
# C-050 (2026-08-23): declare the audience. The PDCA round's output is read by Chami,
# so the reply must not be trimmed on the front channel.
$out = & python scripts/llm/dispatch.py --dept kaizen-analyst --direct --from "self (scheduled PDCA round)" --audience chami --body-file $body 2>&1
$stamp = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
Add-Content -Path $log -Value "===== $stamp =====" -Encoding UTF8
Add-Content -Path $log -Value $out -Encoding UTF8
