# register_lab_revive_task.ps1 - register a hidden auto-recover task for the Lab (研究室)
# Claude session. Same proven method as go5_daemons_hidden: Task Scheduler runs wscript on a
# hidden VBS, which runs revive_lab.ps1 (idempotent: no-op while a Claude session is alive).
#   - starts at registration, repeats every 10 min
#   - StartWhenAvailable => resumes ASAP after a reboot (covers logon without needing admin;
#     an -AtLogOn trigger requires elevation, so we deliberately avoid it)
#   - the checker chain is fully hidden (no 10-minute window flash). Only the Lab session
#     window itself is visible, on purpose (interactive TUI + last-resort input path).
# No admin required (registered as the current user). ASCII-only (PS 5.1 codepage safety).
$ErrorActionPreference = 'Stop'
$TaskName = 'go5_lab_revive'
if ($PSScriptRoot) { $here = $PSScriptRoot } else { $here = Split-Path -Parent $MyInvocation.MyCommand.Definition }
$vbs = Join-Path $here 'lab_revive_hidden.vbs'
if (-not (Test-Path $vbs)) { Write-Error ("lab_revive_hidden.vbs not found: " + $vbs); exit 1 }

$action  = New-ScheduledTaskAction -Execute 'wscript.exe' -Argument ('"' + $vbs + '"')
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 10) -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 5)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Description 'go5-maker: revive the Lab Claude session when none is alive' -Force | Out-Null

Write-Host ("OK: registered '" + $TaskName + "' (hidden checker, every 10 min, auto-recover).") -ForegroundColor Green
try { Start-ScheduledTask -TaskName $TaskName; Write-Host "Started once now (no-op if a session is already alive)." } catch {}
