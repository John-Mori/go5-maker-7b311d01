# 改名移行台本: go5-maker → 5SecMovieMaker

> **正はデータ整理部門とChamiの合意(2026-07-16 16:46 Chami承認)**。研究室が当初書いた別案(夜にリポジトリ名だけ実行)は**撤回**した。
> 撤回理由: ①**公開URLはリポジトリ名を変えても変わらない**(Pages URLは既に別名`go5-maker-7b311d01`に紐づく=データ整理の調査)。夜にやる価値が薄い ②Chamiは既に一度説明を受けて判断済み——**二重の計画を出すと同じ判断を二度させる**(INC-85で同種の失敗)。
> **計画を立て直してChamiへ再提示しないこと。** 変更が要る時はまずデータ整理部門と合議する。

## 合意した順序
1. **整理**(データ整理部門・安全な分は実施済)
2. **下準備=スクリプトの絶対パス依存を排除**(`%~dp0` / `$PSScriptRoot` 化) ← **研究室が担当**
3. **朝、Chamiが起きている時に一気に**: 改名 + タスク7件の住所書き換え + 事務所(常駐・全窓)の再起動

## なぜ「寝てる間に完了まで」をやらないか(データ整理の説明・Chami納得済み)
- 絶対パス**21ファイル**+タスク**6件**+スタートアップ**1件**が壊れる。しかも**全て静かに壊れる**(気づけない)。
- **改名を実行するセッション自身が家を失う**。自動復活(revive_lab)も旧パスを見ているため**復旧不能**。
- したがって**人が見ている時間帯にやる**のが唯一安全。

## ② 下準備の中身(研究室担当・着手前に改修セッションと調整)
- 対象: `scripts/discord/start_*.bat` / `scripts/llm/*.bat` / `scripts/_daemons/*.ps1`(revive_lab・set_lab_session・supervise_daemons・open_dept_window・winupdate_watch)/ `scripts/maintenance/*`
- 方針: ハードコードした `D:\SougouStartFolder\go5-maker` を**スクリプト自身の位置からの相対解決**へ置換(`%~dp0..\..` / `$PSScriptRoot`)。Pythonは既に `os.path.dirname(__file__)` 基準で解決済み(改修不要)。
- **注意**: 対象ファイルは改修α/βが実装中に触る領域と重なる。**着手前に改修セッションへ調整**(Chami明示16:59「システム改修とか実行中とかを避けながら進めて」)。
- 完了後: 下準備だけでは動作は変わらない(旧パスのままでも相対解決で同じ場所を指す)=**安全に先行実施できる**。検証=常駐4種を再起動して脈/配達が正常なこと。

## ③ 当日(朝・Chami在席)の手順
1. Chamiが**開いている全Claude窓を閉じる**(閉じないと旧cwdのまま倒れる)
2. 常駐4種を停止・スケジュールタスク7件を無効化
3. フォルダ改名
4. タスク7件を新パスで再登録(下準備が済んでいればスクリプト内の書き換えは不要)
5. **メモリの引っ越し**: `C:\Users\chami\.claude\projects\D--SougouStartFolder-go5-maker\memory\` → 新スラッグdirへコピー
6. 常駐起動→検証(下記)→全部門の窓を立て直し(研究室が新パス版の起動文を配布)
7. AI-HQ(PORTFOLIO/status)のパス表記更新
- ロールバック: フォルダ名を戻す→タスク再登録

## 検証チェックリスト(③の後に全行)
- [ ] 公開URLで200(**改名しても変わらない**が念のため実機確認)
- [ ] git push/pull疎通
- [ ] 鳩の脈<60秒・main waiter稼働・部門箱への直配
- [ ] persona_send疎通(研究室chへテスト1通)
- [ ] スケジュールタスク7件=Ready・直近実行成功
- [ ] revive_labのlabIdが実在セッションUUID(`set_lab_session.ps1`実行)
- [ ] 常駐4種(鳩/ローカル/ホイミン/watchdog)稼働

## リポジトリ名(②の枠外・任意)
- 変えても**公開URLは変わらない**(難読サフィックス付きの別名に紐づくため)。やるなら `gh repo rename` + `git remote set-url` のみ。急がない。

## 凍結時の再実測(3分・データ整理が整備2026-07-18・手順書_受信基盤切替_段階2 §5から参照)

> 棚卸しの数字は生き物(2026-07-18実測: タスク6→**11本**・実行系ファイル約22)。**計画停止の凍結直後にこの2本を流し、その結果を最終版とする。** 事前の数字は目安に過ぎない。

絶対パスを焼き込んだファイル(bash・repo直下で):
```bash
grep -rlI "SougouStartFolder" --exclude-dir=local --exclude-dir=node_modules \
  --exclude-dir=.git --exclude-dir=.obsidian --exclude-dir=.wrangler . | sort
```
※ `.claude/worktrees/` 配下が出たら**先に `git worktree remove`**(worktreeのgitdirは絶対パス相互参照=改名で両方向に壊れる。残すなら改名後に `git worktree repair`)。

パスを参照するスケジュールタスク(PowerShell):
```powershell
Get-ScheduledTask | Where-Object { $_.Actions | Where-Object {
  ($_.Execute -like '*go5-maker*') -or ($_.Arguments -like '*go5-maker*') -or ($_.WorkingDirectory -like '*go5-maker*') } } |
  Select-Object TaskName | Sort-Object TaskName
```

タスクの一括再登録+発火検証(改名後・データ整理製):
```powershell
powershell -File scripts\maintenance\reregister_tasks.ps1              # dry-run(何が変わるか確認)
powershell -File scripts\maintenance\reregister_tasks.ps1 -Apply       # 書き換え+再登録
powershell -File scripts\maintenance\reregister_tasks.ps1 -Apply -Fire go5_context_budget_weekly,go5_build_knowledge_daily,go5_learning_report_weekly,go5_backup_local_daily
# 常駐系(daemons_hidden/lab_revive/sales系)は再開フェーズで各自の手順に従い起動(むやみにFireAllしない)
```
- 検出は**タスク名でなく中身**(Execute/Arguments/WorkingDirectory)で行うため、今後増えたタスクも自動で拾う。
- python系タスクは絶対パス登録が前提(PATH解決は黙って死ぬ・2026-07-17実測)。reregister_tasksは既存定義を書き換えるだけなので、正しく登録されていれば絶対パスは維持される。
