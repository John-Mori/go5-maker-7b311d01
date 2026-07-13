@echo off
chcp 65001 >nul
echo === 販売数の「3時間ごと自動取得」を停止します ===
schtasks /Delete /TN "go5_sales_3h" /F
echo.
echo 停止しました。（再開したいときは「販売数-3時間ごと自動取得を設定.bat」を押してください）
echo.
pause
