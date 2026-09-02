# longjob.ps1 — 長時間ジョブの置き場(セッション寿命からの切り離し)

所有: platform-se(一ノ瀬怜)/ HQ裁定 DISPATCH-aegis-gl-1788377143893・部門長aegis-gl割り振り。
所有権トピック: `長時間ジョブの置き場(セッション寿命からの切り離し)`(ownership.py claim 済)。

## これは「器」だけ
`longjob.ps1` は**汎用の走らせ切る器**。ollama pull / 画風LoRA学習 / 大規模スクレイプ、どれも同じ穴に落ちる。
- **中身**(どのモデルを引くか・落ちた物が使えるか)= 学習/ローカルLLM教育部門・各業務部門の持ち場。器はそこへ踏み込まない。
- 器がやること = **対話セッションが死んでもジョブを生かす** + **完走を機械で確認し、死んでいたら再開する**。

## なぜ要るか(実測された穴)
対話セッションがジョブを起動して閉じると、ジョブごと落ちる。HQ実測(2026-09-03): ollama pull の16並列チャンクが**そろって ~50.6% で停止** — 回線断ではなく**クライアント側プロセスの死**で、サーバがpullをキャンセルした。

## 設計
- ジョブ = **コマンド + 作業ディレクトリ + ログ + 完了述語**。
  - 完了述語(`-Done`)= コマンド行。**exit 0 = 完走(リトライ停止)**。
    - ollama: `ollama list | findstr <model>`(モデル名が一覧に載る)
    - スクレイプ: `if exist cursor.done (exit 0) else (exit 1)`
    - LoRA: トレーナが目標stepのcheckpointを書いたら 0 を返す物
- **デタッチ** = `WScript.Shell.Run(cmd,0,$false)`。supervise_daemons.ps1 が8常駐で使う実証済みの隠し+非待機起動。起動元(とそのセッション)が死んでも別プロセスツリーとして生き残る。
- **C-041**: 「40分生きた」の1観測は証明ではない。だから器はデタッチを**信用しない** — resume便が「完了述語が通る前に死んだジョブ」を無条件で再起動する。再開には**再開可能なジョブ**が要る(pullは-partialから/トレーナはcheckpointから/スクレイプはcursorから)。再開不能なコマンドはゼロからやり直すだけ。
- **生存判定** = ラッパー `.run.cmd` のパスがプロセスのCommandLineに残っているか(supervise の Match と同じ)。**マーカーファイルでは判定しない**(殺されたジョブはマーカーを残す=「生きてる」と誤読する。HQが踏んだ -partial JSON の罠と同型)。
- **完了判定** = 完了述語だけ(実物チェック)。**ファイルサイズでは判定しない**(-partial は全長で事前確保=スパースの嘘)。

## 使い方
```
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\_daemons\longjob.ps1 start ^
  -Id <id> -Cmd "<コマンド>" -Done "<完了述語>" [-WorkDir <dir>] [-Log <path>] [-MaxAttempts 20]
powershell ... longjob.ps1 status [-Id <id>]     # DONE / RUNNING / STALLED を実物判定で表示
powershell ... longjob.ps1 resume -Id <id>       # 死んでいて未完なら1件だけ再起動
powershell ... longjob.ps1 resume-all            # 巡回: 完了を確定・停止1件を再起動(1巡回1件まで)
powershell ... longjob.ps1 list
```
- 台帳 = `local\_work\longjobs\<id>.json`(id/cmd/done_cmd/workdir/log/attempts/max_attempts/status)。巡回ログ = `local\_work\longjobs\_patrol.log`。
- **C-058**: `resume-all` は1巡回で**最大1件**しか再起動しない(デスクトップに雪崩れさせない)。`MaxAttempts` 到達で `failed` にして止める。

## 0歩目の実測(2026-09-03 05:14, test_0thstep.ps1)
1. start(デタッチ): 起動元 powershell = 消滅(count0)なのに counter は前進 → セッションから切り離せている。
2. 途中でジョブツリーを意図的にKILL: counter=10 で凍結・status=STALLED を正しく判定。
3. resume: **0でなく 10→16 で継続**(再開可能ジョブの続き) attempts=2。
4. 完走: counter=20・done.flag 成立 → 完了述語で **DONE**(機械確認)。
再現ハーネス = `local\_work\longjobs\test_0thstep.ps1` + `hbtest_work\job_body.ps1`。

## 未決(go/no-go 要・本番設定に触れる)
`resume-all` を自動で回す線がまだ無い。**新規スケジュールタスクは作らない**方針。
既存の10分巡回 `supervise_daemons.ps1` の末尾に1行足して合流させるのが最小(新タスク不要・再起動生存も継承)。
→ 部門長(aegis-gl)へ go/no-go を1行で確認してから入れる。逆操作は該当1行の削除。
それまで resume は**手動 or セッションから明示呼び出し**で使う(器としては完成・自動巡回だけ保留)。

## C-042 について
`longjob.ps1` は常駐pythonが import する自作モジュールではない(毎回 fresh に起動されるps1)ので、`daemon_keeper.WATCH_FILES` へ入れる対象ではない。supervise から呼ぶ形にしても、supervise は毎巡回 fresh に実行するので常に最新の longjob.ps1 を読む(コード版ズレは起きない)。
