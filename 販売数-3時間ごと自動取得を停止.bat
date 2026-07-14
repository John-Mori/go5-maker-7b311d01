@echo off
echo Stopping "go5_sales_3h"...
schtasks /Delete /TN "go5_sales_3h" /F
echo.
echo Stopped. (Re-run the setup .bat to enable again.)
pause
