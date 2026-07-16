' go5-maker: revive_lab.ps1 を「窓を一切出さず」実行するランチャ。
' タスクスケジューラ(10分ごと)から wscript 経由で呼ぶ。
' WScript.Shell.Run の第2引数 0 = 非表示ウィンドウ、第3引数 False = 完了を待たない。
' これで判定役の PowerShell の窓は一切出ない(10分ごとの一瞬の光りも無い)。
' ※研究室セッション本体(claude -r)だけは意図的に可視で開く。対話TUIであり、
'   Discordが死んだ時の最終手段としてChamiが直接打ち込む窓でもあるため。
Dim sh, fso, here
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
here = fso.GetParentFolderName(WScript.ScriptFullName)
sh.Run "powershell -NoProfile -ExecutionPolicy Bypass -File """ & here & "\revive_lab.ps1""", 0, False
