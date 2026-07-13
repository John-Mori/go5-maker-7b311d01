' go5-maker: sales_fetch_3h.bat を「ウィンドウ非表示」で起動するランチャ。
' タスクスケジューラから wscript.exe 経由で呼ばれる（wscript 自体はコンソールを持たない）。
' WshShell.Run の第2引数 0 = 非表示ウィンドウ、第3引数 False = 完了を待たない。
' これで3時間ごとの実行時に黒いターミナル窓が一切出ない（Chami指定=画面に映さない）。
Dim sh, fso, here
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
here = fso.GetParentFolderName(WScript.ScriptFullName)
sh.Run "cmd /c """ & here & "\sales_fetch_3h.bat""", 0, False
