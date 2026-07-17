@echo off
rem go5 inbox_waiter (chime line - event-driven wake, replaces heartbeat).
rem   usage: start_inbox_waiter.bat            -> watch main box (local\discord_inbox.jsonl)
rem          start_inbox_waiter.bat research-room -> watch dept box (local\inbox\<name>.jsonl)
rem 通常はClaudeセッションが run_in_background で起動する。手動/常駐確認用にこのbatを使う。
cd /d D:\SougouStartFolder\go5-maker
set NAME=%1
if "%NAME%"=="" set NAME=main
title go5-inbox-waiter-%NAME%
python scripts\llm\inbox_waiter.py --name %NAME% >> local\llm\inbox_waiter_%NAME%.log 2>&1
echo inbox_waiter exited - see local\llm\inbox_waiter_%NAME%.log
