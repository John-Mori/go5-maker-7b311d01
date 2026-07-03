@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === 販売数の自動取得をこのPCに設定します ===
echo （15分ごとに動く常駐タスクを登録します。以後この.batを押す必要はありません）
echo （スマホ等から「▶今すぐ取得」を押すと、数分以内にこのPCが取得します）
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\register_sales_task.ps1" -RepoRoot "%~dp0."
echo.
pause
