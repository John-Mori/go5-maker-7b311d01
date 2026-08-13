@echo off
rem lab_window.cmd - witness wrapper for the Lab (kenkyushitsu) window. 2026-08-13, aegis-gl.
rem
rem WHY: nothing has ever recorded WHY the Lab's claude.exe stops. Windows records nothing
rem   either - measured 2026-08-13: zero Application-log events mentioning claude.exe for the
rem   whole day (4 deaths), and Security 4689 (process termination auditing) is not enabled
rem   (count today = 0). An exit code can ONLY be read at the moment of death, so "look for
rem   traces afterwards" can never work. The parent `cmd /k` is already present at every death
rem   (measured: `reaped 1 stale revival shell` on all 4 respawns of 2026-08-13, i.e. the shell
rem   outlives its claude.exe), so the cheapest witness is the shell itself.
rem   No daemon, no admin rights, no WMI subscription, no new reload path (C-042): a batch file
rem   is re-read on every spawn.
rem
rem WHY A BATCH FILE AND NOT `cmd /k a && echo %errorlevel%`: on a command LINE, %errorlevel%
rem   is expanded once at parse time = always 0. Inside a batch file each line is expanded as it
rem   runs, so it holds claude's real exit code. Delayed expansion (`cmd /v:on` + !errorlevel!)
rem   is deliberately NOT used because it would eat any `!` inside the boot prompt.
rem
rem ASCII-only on purpose: PowerShell 5.1 / cmd read a no-BOM file as the system ANSI codepage.
rem   Japanese notes belong in docs, not here (same rule as revive_lab.ps1).
rem
rem ARGS: %1 = full path to claude.exe   %2 = the already-flattened boot prompt (one argument)
rem NOTE: revive_lab.ps1 section 2.5 finds dead windows by matching `.local\bin\claude.exe` in
rem   the cmd command line. That path is passed as %1 and therefore STAYS on the command line.
rem   Do not move it inside this file, or every future corpse becomes invisible to the reaper
rem   (that is how 100 corpses / ~4GB piled up on 2026-08-01).
cd /d "%~dp0..\.."
"%~1" "%~2"
set LAB_RC=%errorlevel%
rem Redirection goes FIRST on purpose. `echo ... exit=%LAB_RC%>> file` expands to
rem `echo ... exit=1>> file`, and cmd reads that trailing `1>>` as "redirect stream 1" - the
rem code is swallowed and the log line ends at `exit=`. Measured here on 2026-08-13 before the
rem fix. Putting `>>` in front removes the digit-adjacency entirely.
>> local\_lab_claude_exit.log echo %date% %time% claude exit=%LAB_RC%
echo.
echo ==== claude.exe exited with code %LAB_RC% - window kept open on purpose ====
echo ==== last screen above is the only record of a fatal message. exit code logged to ====
echo ==== local\_lab_claude_exit.log ====
