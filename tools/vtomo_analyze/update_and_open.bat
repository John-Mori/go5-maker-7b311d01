@echo off
setlocal
cd /d "%~dp0"
python fetch_own_videos.py
if errorlevel 1 exit /b 1
python build_data.py
if errorlevel 1 exit /b 1
start "" "%~dp0index.html"
