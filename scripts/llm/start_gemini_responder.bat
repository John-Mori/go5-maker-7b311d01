@echo off
rem go5 Gemini responder (dept=="gemini" room, always-on even while Claude session active)
cd /d D:\SougouStartFolder\go5-maker
title go5-gemini-responder
python scripts\llm\gemini_responder.py >> local\llm\gemini_responder_console.log 2>&1
echo responder exited - see local\llm\gemini_responder_console.log
pause
