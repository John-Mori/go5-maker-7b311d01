@echo off
rem go5 local LLM responder (24h reception when Claude session is off)
cd /d "%~dp0..\.."
title go5-local-responder
python scripts\llm\local_responder.py >> local\llm\responder_console.log 2>&1
echo responder exited - see local\llm\responder_console.log
pause
