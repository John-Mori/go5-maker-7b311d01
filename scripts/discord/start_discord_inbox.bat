@echo off
rem go5 Discord inbox poller (Phase DB) - resident
cd /d "%~dp0..\.."
title go5-discord-inbox
python scripts\discord\inbox_poller.py >> local\discord_poller.log 2>&1
echo poller exited - see local\discord_poller.log
pause
