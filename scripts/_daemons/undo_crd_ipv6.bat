@echo off
rem ---------------------------------------------------------------------
rem  Undo fix_crd_ipv6.bat. Restores IPv6 temporary addresses and removes
rem  the go5_crd_restart trigger task. Self-elevates.
rem  ASCII only on purpose (see fix_crd_ipv6.bat).
rem ---------------------------------------------------------------------
setlocal

net session >nul 2>&1
if %errorlevel% neq 0 (
  echo Requesting administrator rights...
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)

chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0..\.."
python "scripts\_daemons\crd_ipv6_fix.py" --rollback
pause
