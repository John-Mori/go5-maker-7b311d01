@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === 販売数の「3時間ごと自動取得」をこのPCに設定します ===
echo （0時から3時間おき=0/3/6/9/12/15/18/21時に、裏で自動取得します）
echo （画面には黒い窓は出ません。以後この.batを押す必要はありません）
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scriptsegister_sales_3h_task.ps1" -RepoRoot "%~dp0."
echo.
pause
