# 改名移行台本: go5-maker → 5SecMovieMaker

> 2026-07-16 Chami発意「go5-makerはAIが勝手に付けた名前で分かりにくい。整理を兼ねて5SecMovieMakerへ」。
> 研究室が采配(Chami承認済み): **(A)呼び名の統一=即日 / ②リポジトリ名=Chami就寝中に実行 / ①フォルダ改名=データ整理が一段落した後の専用枠**。
> 実測済みの影響: 絶対パス焼き込み25ファイル・スケジュールタスク6本・全セッションcwd・メモリdir。

## (A) 呼び名の統一(実施中・リスクゼロ)
- ドキュメント・会話・UIでの呼称を「**5SecMovieMaker**(旧称go5-maker)」とする。実体パス・リポジトリ名は本台本の②①で追従。
- UIタイトル等のアプリ内表記は改修部門の通常改修で(②と同時が効率的)。

## ② リポジトリ名の改名(今夜・Chami就寝中に研究室が実行)
**影響が軽い理由**: Workerの許可判定はオリジン(`https://john-mori.github.io`)基準=パス無関係で無傷。短縮リンクはbsky.app宛て=無傷。GAS無関係。**唯一の実害=旧Pages URLが死ぬ(Pagesはリダイレクトされない)→Chamiのブックマーク張り替えのみ**。

手順:
1. 新名の決定: `5SecMovieMaker-7b311d01`(**難読サフィックスは維持を既定とする**——公開URLの推測困難性は現名の設計意図。外したければChami判断)
2. `gh repo rename` (または GitHub Web) → ローカルの `git remote set-url origin <新URL>`
3. push疎通確認(`git fetch`)・Pagesビルド完了確認(新URLで200)
4. 旧URL(404化)の確認
5. **朝の報告**: 新URLをコードブロック単独メッセージでDiscordへ(ブックマーク張り替え用)。MacBook側cloneのremote更新手順も添える
6. ロールバック: renameを元に戻すだけ(GitHubは旧名を一定期間予約=他人に取られない)

## ① フォルダ改名(D:\SougouStartFolder\go5-maker → 5SecMovieMaker)(後日・専用枠1時間級)
**前提条件**: Chamiが**開いている全Claude窓を閉じる**(13窓・旧cwdのまま倒れるため)。動画作業なしの時間帯。

手順(実行時に最新のgrepで棚卸しし直すこと):
1. 停止: スケジュールタスク6本(go5_daemons_hidden/go5_lab_revive/go5_sales_3h/go5_sales_auto/go5_winupdate_watch/go5_backup_local_daily)を無効化 → 常駐4種を停止
2. フォルダ改名(エクスプローラかRename-Item)
3. パス書き換え(実測25ファイル+タスク定義6本): `grep -rl "SougouStartFolder.\{0,3\}go5-maker"` の全ヒットを新パスへ。対象例=scripts/**/*.bat・*.ps1(revive_lab/set_lab_session/supervise_daemons/open_dept_window/winupdate_watch/backup_local_to_drive)・scheduled task XML(再登録が確実)
4. **メモリの引っ越し**: `C:\Users\chami\.claude\projects\D--SougouStartFolder-go5-maker\memory\` → 新スラッグdirへコピー(研究室の記憶はフォルダパスに紐づく)。`.claude/settings.local.json`は相対なので無傷
5. タスク再登録(register系ps1を新パスで実行)→常駐起動→検証: 鳩の脈/waiter/persona_send疎通/revive_labのlabId(=①後の新セッションIDへset_lab_session)
6. 全部門セッションの立て直し: Chamiが起動文を貼り直す(研究室が新パス版の起動文を9+α通で再配布)
7. AI-HQ(PORTFOLIO/status)のパス表記更新・グローバルCLAUDE.mdは言及なし(確認済み)
- ロールバック: フォルダ名を戻す→タスク再登録のみ(書き換えはgit管理分はrevert可・管理外はバックアップを先に取る)

## 検証チェックリスト(①②共通・実行後に全行)
- [ ] 公開URLで200(スマホ実機)
- [ ] git push/pull疎通
- [ ] 鳩の脈<30秒・main waiter稼働
- [ ] persona_send疎通(研究室chへテスト1通)
- [ ] スケジュールタスク6本=Ready・直近実行成功
- [ ] revive_labのlabIdが実在セッションUUID(set_lab_session実行)
