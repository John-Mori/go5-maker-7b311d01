@echo off
cd /d "%~dp0"
echo Registering "go5_sales_3h" (every 3h from 00:00, hidden)...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scriptsegister_sales_3h_task.ps1" -RepoRoot "%~dp0."
echo.
echo Done. (Hai-baisuu 3-hour auto-fetch registered. Stop with the stop .bat.)
pause
