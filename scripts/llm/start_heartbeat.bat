@echo off
rem go5 heartbeat (INC-091 countermeasure 1 - TTL heartbeat, no pause, resident)
cd /d "%~dp0..\.."
title go5-heartbeat
python scripts\llm\heartbeat.py >> local\llm\heartbeat.log 2>&1
echo heartbeat exited - see local\llm\heartbeat.log
