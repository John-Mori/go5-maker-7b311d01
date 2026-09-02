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
# 2026-09-02 Chami "swap" directive (msg 1544486499653910629): the 08:00 push content is
# switched from the competitor *video* daily (upstream GAS frozen since 8/18 = same message every
# morning) to the competitor *community-post* brief (fresh via --fresh scrape, symbol-free JP).
# Only the invoked analysis changes; the 08:00 trigger/registration (platform-se) is untouched.
$log = Join-Path $root 'local\competitor_daily.log'
$out = & python scripts/analysis/community_daily_push.py 2>&1
$stamp = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
Add-Content -Path $log -Value "===== $stamp =====" -Encoding UTF8
Add-Content -Path $log -Value $out -Encoding UTF8
# 2026-09-02 HQ-0230 (DISPATCH-shorts-analyst-1788307335393): the swap above silenced the only
# daily口 that warned the upstream GAS is frozen (8/18). Re-arm a freeze watch that rings ONCE to
# 研究室HQ (AI便) on first detection, then every 7 days while frozen (never the daily-same spam Chami
# rejected), and once on recovery. Runs in the analysis dept's own lane (C-027); it re-runs
# competitor_daily.py --emit just to read the "上流スナップが ... で停止" line (rc is 0 even when frozen).
$out2 = & python scripts/analysis/gas_freeze_watch.py 2>&1
Add-Content -Path $log -Value "----- gas_freeze_watch -----" -Encoding UTF8
Add-Content -Path $log -Value $out2 -Encoding UTF8
