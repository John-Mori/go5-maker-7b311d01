@echo off
rem go5 Discord inbox test - one polling pass
cd /d "%~dp0..\.."
python scripts\discord\inbox_poller.py --once
pause
