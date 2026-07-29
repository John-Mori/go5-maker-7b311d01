' 5秒動画メーカー: comp_frames.bat を「ウィンドウ非表示」で起動するランチャ。
' タスクスケジューラから wscript.exe 経由で呼ばれる(wscript 自体はコンソールを持たない)。
' WshShell.Run 第2引数 0 = 非表示ウィンドウ、第3引数 False = 完了を待たない(morning_scan_hidden.vbs に倣う)。
Dim sh, fso, here
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
here = fso.GetParentFolderName(WScript.ScriptFullName)
sh.Run "cmd /c """ & here & "\comp_frames.bat""", 0, False
