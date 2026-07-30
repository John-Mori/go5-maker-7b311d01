# daily_reflection.ps1 - 00:00 JST trigger that wakes future-room (現在と未来) to write one
# self-reflection about Chami. Runs daily_reflection_trigger.py, which enqueues one便 to the
# live future-room daemon; the room's persistent session generates + saves + replies (auto-posts).
# ASCII-only on purpose (PS 5.1 reads BOM-less ps1 as ANSI; Japanese here would corrupt).
# UTF-8 forced for the child process and the log, same lesson as daily_report.ps1
# (a log you cannot read is the same as no record).
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $root
$env:PYTHONIOENCODING = 'utf-8'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$log = Join-Path $root 'local\daily_reflection.log'
$out = & python scripts/llm/daily_reflection_trigger.py 2>&1
$stamp = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
Add-Content -Path $log -Value "===== $stamp =====" -Encoding UTF8
Add-Content -Path $log -Value $out -Encoding UTF8
