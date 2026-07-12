@echo off
rem go5 Discord inbox test - one polling pass
cd /d D:\SougouStartFolder\go5-maker
python scripts\discord\inbox_poller.py --once
pause
