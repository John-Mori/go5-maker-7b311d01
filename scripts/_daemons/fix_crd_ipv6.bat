@echo off
rem ---------------------------------------------------------------------
rem  CRD (Chrome Remote Desktop) drops every few minutes -> permanent fix.
rem  Right-click this file and choose "Kanrisha to shite jikkou"
rem  (Run as administrator). It self-elevates too, so a plain double-click
rem  will raise the UAC prompt by itself.
rem
rem  ASCII only on purpose: .bat is read with the ANSI codepage, so any
rem  Japanese written here would be mojibake. The reasoning in Japanese
rem  lives in crd_ipv6_fix.py (utf-8).
rem
rem  What it does (see crd_ipv6_fix.py header for why):
rem    1. backs up the current IPv6 / service state under local\_work\
rem    2. netsh interface ipv6 set privacy state=disabled store=persistent
rem    3. registers task go5_crd_restart (SYSTEM, highest) so chromoting
rem       can be restarted later WITHOUT elevation:
rem         schtasks /run /tn go5_crd_restart
rem
rem  Undo: undo_crd_ipv6.bat
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
python "scripts\_daemons\crd_ipv6_fix.py" --apply
echo.
echo ---------------------------------------------------------------
echo Done applying. This is "applied", NOT yet "fixed".
echo To prove it, run (no admin needed):
echo   python scripts\_daemons\crd_ipv6_fix.py --watch 30 --minutes 20
echo ---------------------------------------------------------------
pause
