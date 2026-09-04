@echo off
rem 5秒動画メーカー: 競合_日次スナップのPC側収集(改修部門α・方向2・モドリッチ依頼2026-09-04)
rem GAS urlfetch枠の枯渇で04:00の競合ジョブが凍結する問題を回避=yt-dlp(APIキー不要)で取ってGASのSpreadsheetApp口へ書き戻す。
rem 04:00のGAS試行の後・08:00の朝ブリーフ(凍結監視)の前に走らせる=pc_writeback行が末尾today行=緑/同朝に復旧が見える。
chcp 65001 >nul
cd /d "%~dp0.."
python scripts\comp_daily.py --max 800 >> "%TEMP%\go5-comp-daily.log" 2>&1
