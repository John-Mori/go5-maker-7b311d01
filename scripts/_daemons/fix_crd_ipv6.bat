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
rem  *** 2026-08-15: DO NOT RUN. The premise behind this fix was refuted by
rem  *** measurement (same host IPv6 used by every session incl. the 41-min
rem  *** clean one, still alive 13.5h later; RA every 40s vs 300s lifetime =
rem  *** 7.5 misses of margin). crd_ipv6_fix.py --apply now stops by itself.
rem  *** Read the "2026-08-15 no hansho" block at the top of crd_ipv6_fix.py.
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
if %errorlevel% equ 3 (
  echo.
  echo ---------------------------------------------------------------
  echo NOTHING WAS CHANGED. The premise was refuted - see above.
  echo Measure instead (no admin needed):
  echo   python scripts\_daemons\ra_lifetime_watch.py --minutes 40
  echo ---------------------------------------------------------------
  pause
  exit /b 3
)
echo.
echo ---------------------------------------------------------------
echo Done applying. This is "applied", NOT yet "fixed".
echo To prove it, run (no admin needed):
echo   python scripts\_daemons\ra_lifetime_watch.py --minutes 40
echo ---------------------------------------------------------------
pause
