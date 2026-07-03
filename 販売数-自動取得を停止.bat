@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === 販売数の自動取得タスクを停止・削除します ===
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { Unregister-ScheduledTask -TaskName 'go5_sales_auto' -Confirm:$false; Write-Host '✅ 自動取得タスクを削除しました。' } catch { Write-Host '（タスクは登録されていませんでした）' }"
echo.
pause
