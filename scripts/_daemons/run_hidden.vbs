' go5-maker: generic hidden launcher for Task Scheduler.
' Purpose: a task registered as "powershell.exe ..." or "python.exe ..." pops a
' black console window in the interactive session. wscript.exe itself has no
' console, and WshShell.Run with window style 0 creates the child process with
' SW_HIDE, so nothing is drawn on screen at all (not even a flash).
'
' Usage in Task Scheduler:
'   Program : wscript.exe
'   Argument: "D:\SougouStartFolder\5SecMovieMaker\scripts\_daemons\run_hidden.vbs" <exe> <arg1> <arg2> ...
'   Start in: (keep the original working directory - the child inherits it)
'
' Notes:
'   - arg 2 = 0    : hidden window
'   - arg 3 = True : WAIT for the child and exit with its exit code, so the task's
'                    LastTaskResult keeps reporting the script (not the launcher).
'   - arguments that contain a space are re-quoted before being joined back.
Option Explicit
Dim sh, args, cmd, i, a
Set sh = CreateObject("WScript.Shell")
Set args = WScript.Arguments
cmd = ""
For i = 0 To args.Count - 1
  a = args(i)
  If InStr(a, " ") > 0 Then a = """" & a & """"
  If cmd = "" Then
    cmd = a
  Else
    cmd = cmd & " " & a
  End If
Next
If cmd = "" Then
  WScript.Quit 2
End If
WScript.Quit sh.Run(cmd, 0, True)
