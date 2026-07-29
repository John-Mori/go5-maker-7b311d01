@echo off
rem 5秒動画メーカー: 競合Shorts代表フレームの日次自動収集(改修部門α・Chami依頼2026-07-29)
rem comp_frame_pending を毎日処理: proの無料枠で読めるだけ読み、尽きたら打ち切り→残りは翌日へ繰り越し(冪等)。
rem --limit は「1日に取りに行くpendingの上限」。実際の打ち切りはpro無料枠が尽きた時点(comp_frames.py側)。
chcp 65001 >nul
cd /d "%~dp0.."
python scripts\comp_frames.py --limit 50 >> "%TEMP%\go5-comp-frames.log" 2>&1
