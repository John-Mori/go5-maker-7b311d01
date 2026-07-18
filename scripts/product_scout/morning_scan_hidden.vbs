' go5-maker: morning_scan.bat を「ウィンドウ非表示」で起動するランチャ。
' タスクスケジューラから wscript.exe 経由で呼ばれる(wscript 自体はコンソールを持たない)。
' WshShell.Run の第2引数 0 = 非表示ウィンドウ、第3引数 False = 完了を待たない。
' 毎朝06:10の採算速報タスクでも黒いターミナル窓を出さない(sales_fetch_3h_hidden.vbs に倣う)。
Dim sh, fso, here
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
here = fso.GetParentFolderName(WScript.ScriptFullName)
sh.Run "cmd /c """ & here & "\morning_scan.bat""", 0, False
