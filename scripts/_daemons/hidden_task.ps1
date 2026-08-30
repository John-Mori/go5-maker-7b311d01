# hidden_task.ps1 - go5-maker (aegis-gl / 2026-08-30).
#
# WHY THIS FILE EXISTS
#   Chami (msg 1543598413340475462, 2026-08-30 21:29):
#     "the black windows that pop up periodically in Task Scheduler - is that this project?
#      please don't show them on screen"
#   HQ measured 19 of 31 go5_* tasks were launching python.exe / powershell.exe DIRECTLY,
#   which owns a console => a black window is drawn in the interactive session.
#   -WindowStyle Hidden does NOT help: the window is created first and then hidden, so it
#   flashes. HQ converted all 19 live tasks to wscript.exe + run_hidden.vbs.
#
#   THAT FIXED THE TASKS, NOT THE HOLE. The registration scripts under scripts\ still write
#   "-Execute python.exe" by hand, so re-running ANY of them silently reopens the window.
#   This file is the entry gate: every register_*.ps1 builds its action through here.
#
# USAGE (dot-source, then call):
#     . (Join-Path $PSScriptRoot 'hidden_task.ps1')
#     $action = New-Go5HiddenAction -Execute $python -Argument ('"' + $script + '"') -WorkingDirectory $root
#
#   Returns a normal object from New-ScheduledTaskAction, so callers keep passing it to
#   Register-ScheduledTask unchanged. Only the Execute/Argument pair is rewritten.
#
# WHAT IT DOES
#   console-owning exe (python / py / powershell / pwsh / cmd / cscript / node)
#       -> wscript.exe "<run_hidden.vbs>" <original exe> <original args>
#   already safe (wscript.exe / pythonw.exe)
#       -> passed through untouched (do not double-wrap)
#
#   run_hidden.vbs waits for the child and exits with its code, so LastTaskResult still
#   reports the script rather than the launcher (quota_guard.ps1 reads that value).
#
# NOTE: keep this file ASCII-only (PowerShell 5.1 reads a no-BOM file as the ANSI codepage).

# NOTE: deliberately NO Set-StrictMode here. This file is dot-sourced, so it runs in the
# CALLER's scope - turning StrictMode on would change how 16 existing register_*.ps1 behave.
# A gate that breaks its callers gets removed instead of used.

# exes that allocate a console => a window is drawn.
# ONE SOURCE: console_window_policy.json is read by this gate AND by the unattended watchdog
# (console_task_watch.py). Writing the list twice guarantees one copy goes stale.
$script:Go5PolicyPath = Join-Path $PSScriptRoot 'console_window_policy.json'
$script:Go5ConsoleExes = (Get-Content -Raw -Encoding UTF8 $script:Go5PolicyPath |
                          ConvertFrom-Json).console_exes

function Test-Go5ConsoleExe {
    <#
      .SYNOPSIS
        Does this Execute value own a console (= draws a black window)?
      .NOTES
        Compares on the file name only, so a full path and a bare name behave the same.
        This is the SAME verdict the watchdog uses; keep the list in one place.
    #>
    param([string]$Execute)
    if ([string]::IsNullOrWhiteSpace($Execute)) { return $false }
    $leaf = (Split-Path -Leaf $Execute.Trim('"')).ToLowerInvariant()
    return ($script:Go5ConsoleExes -contains $leaf)
}

function Get-Go5HiddenLauncher {
    param()
    return (Join-Path $PSScriptRoot 'run_hidden.vbs')
}

function New-Go5HiddenAction {
    <#
      .SYNOPSIS
        New-ScheduledTaskAction that can never pop a console window.
      .PARAMETER Execute
        The program you actually want to run (python.exe, powershell.exe, ...).
      .PARAMETER Argument
        Its arguments, exactly as you would have passed them to New-ScheduledTaskAction.
      .PARAMETER WorkingDirectory
        Unchanged - the child inherits it through wscript.
      .PARAMETER Force
        Wrap even an already-safe exe. Off by default (do not double-wrap wscript).
    #>
    param(
        [Parameter(Mandatory = $true)][string]$Execute,
        [string]$Argument = '',
        [string]$WorkingDirectory = '',
        [switch]$Force
    )
    $vbs = Get-Go5HiddenLauncher
    if (-not (Test-Path $vbs)) { throw "run_hidden.vbs not found: $vbs" }

    $exe = $Execute
    $arg = $Argument
    if ($Force -or (Test-Go5ConsoleExe -Execute $Execute)) {
        # quote the inner exe only when it needs it (run_hidden.vbs re-quotes on spaces too,
        # but doing it here keeps the registered Argument readable in the Task Scheduler UI)
        $inner = $Execute
        if ($inner -match '\s' -and $inner -notmatch '^".*"$') { $inner = '"' + $inner + '"' }
        $exe = 'wscript.exe'
        $arg = ('"' + $vbs + '" ' + $inner + ' ' + $Argument).Trim()
    }

    $params = @{ Execute = $exe }
    if ($arg) { $params['Argument'] = $arg }
    if ($WorkingDirectory) { $params['WorkingDirectory'] = $WorkingDirectory }
    return (New-ScheduledTaskAction @params)
}
