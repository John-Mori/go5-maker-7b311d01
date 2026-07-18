@echo off
rem go5 Discord absence watchdog (Phase DB) - resident
cd /d "%~dp0..\.."
title go5-discord-watchdog
python scripts\discord\absence_watchdog.py >> local\discord_watchdog.log 2>&1
echo watchdog exited - see local\discord_watchdog.log
pause
