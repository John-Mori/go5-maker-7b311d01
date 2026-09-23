# register_daemons_logon_task.ps1 - register a hidden auto-start/auto-recover task for the
# resident daemons (poller/watchdog/local_responder/gemini_responder). Same proven method as
# go5_sales_auto: Task Scheduler runs wscript on a hidden VBS, which runs supervise_daemons.ps1.
#   - starts at registration, repeats every 10 min (idempotent supervisor = no duplicates)
#   - StartWhenAvailable => resumes ASAP after a reboot (covers logon)
#   - zero visible windows anywhere in the chain
# No admin required (registered as the current user). ASCII-only (PS 5.1 codepage safety).
$ErrorActionPreference = 'Stop'
$TaskName = 'go5_daemons_hidden'
if ($PSScriptRoot) { $here = $PSScriptRoot } else { $here = Split-Path -Parent $MyInvocation.MyCommand.Definition }
$vbs = Join-Path $here 'daemons_hidden.vbs'
if (-not (Test-Path $vbs)) { Write-Error ("daemons_hidden.vbs not found: " + $vbs); exit 1 }

# every scheduled task goes through the gate so it can never pop a console window
# (aegis-gl 2026-08-30 / see scripts\_daemons\hidden_task.ps1)
$go5Here = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Definition }
. (Join-Path $go5Here 'hidden_task.ps1')
$action  = New-Go5HiddenAction -Execute 'wscript.exe' -Argument ('"' + $vbs + '"')
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 10) -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 5)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Description 'go5-maker: keep resident daemons running hidden and single-instance' -Force | Out-Null

Write-Host ("OK: registered '" + $TaskName + "' (hidden, every 10 min, auto-recover).") -ForegroundColor Green
try { Start-ScheduledTask -TaskName $TaskName; Write-Host "Started once now (cleans up + launches hidden)." } catch {}
