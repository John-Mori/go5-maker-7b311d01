' go5-maker: sales_poll.bat を「ウィンドウ非表示」で起動するランチャ。
' タスクスケジューラから wscript.exe 経由で呼ばれる（wscript 自体はコンソールを持たない）。
' WshShell.Run の第2引数 0 = 非表示ウィンドウ、第3引数 False = 完了を待たない。
' これにより15分ごとの実行で黒いターミナル窓が一切出なくなる。
Dim sh, fso, here
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
here = fso.GetParentFolderName(WScript.ScriptFullName)
sh.Run "cmd /c """ & here & "\sales_poll.bat""", 0, False
