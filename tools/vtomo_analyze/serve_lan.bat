@echo off
setlocal
cd /d "%~dp0"
python fetch_own_videos.py
if errorlevel 1 exit /b 1
python build_data.py
if errorlevel 1 exit /b 1
echo VtomoAnalyze: http://PCのLAN-IP:8765/
echo 終了はこの画面で Ctrl+C
python -m http.server 8765 --bind 0.0.0.0
