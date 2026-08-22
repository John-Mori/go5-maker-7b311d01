# se_daily_review.ps1 - daily 08:00 retrospective for the alpha repair dept (Chami 2026-07-29).
# Chami: "look back 24h every morning at 8, and reduce the number of times I have to ask."
# ASCII-only on purpose (PS 5.1 reads BOM-less ps1 as ANSI; Japanese here would corrupt).
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $root
$env:PYTHONIOENCODING = 'utf-8'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$log = Join-Path $root 'local\se_daily_review.log'
$body = 'D:\SougouStartFolder\00_AI-HQ\departments\se\DAILY_REVIEW.md'
# C-050 (2026-08-23): declare the audience. The review this asks for is read by Chami,
# so the reply must not be trimmed on the front channel.
$out = & python scripts/llm/dispatch.py --dept system-engineer --direct --from "self (scheduled daily review)" --audience chami --body-file $body 2>&1
$stamp = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
Add-Content -Path $log -Value "===== $stamp =====" -Encoding UTF8
Add-Content -Path $log -Value $out -Encoding UTF8
