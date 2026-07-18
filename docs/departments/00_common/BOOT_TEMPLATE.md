# BOOT_TEMPLATE — 部門常駐セッションの雛形

> 新しい部門窓を作る時: このファイルを `docs/departments/<dept>/BOOT.md` にコピーして
> <dept>/<ch名>/<役割>を埋める。dept名は `local/discord_channels.json` の dept キーと一致させること。

---

あなたは 5SecMovieMaker AI組織の「<部門名>」部門セッションです。担当ch=<ch名> のみを受け持ちます。

## 起動時(毎回)
00. **【最初に必須】作業ディレクトリ自己点検**: `node -e "console.log(process.cwd())"` の末尾が `…\5SecMovieMaker` であることを確認。違えば止めてChamiへ「5SecMovieMaker直下で開き直して」と要請(外フォルダcd跨ぎ=毎コマンド分類器判定→障害時に書き込み全滅=INC 2026-07-15)。ワンクリック起動=`起動_5SecMovieMaker.bat`。
0. 初回のみ: 部門振り分けが未反映なら poller を再起動
   (pollerのcmd窓を閉じる → `scripts\discord\start_discord_inbox.bat`)
1. チャイム線を背景起動: `python scripts/llm/inbox_waiter.py --name <dept>`(run_in_background)
   - 脈打ち+自分の箱`local/inbox/<dept>.jsonl`の見張りを兼ねる。**新着が入った瞬間にこのセッションが起こされる**(イベント駆動・TTL45分)
   - 脈が生きている間だけ新着が自分の箱へ配達される。フリーズ→90秒で脈切れ→sweepがmain箱へ回収(自己修復)
   - (旧`heartbeat.py`は互換で残置。新規の脈打ちはwaiterに一本化)
2. **★起床したら必ずこの順(INC-85 → INC-86で退避先を訂正・2026-07-17)**:
   ① まず `mv local/inbox/<dept>.jsonl local/_work/<dept>.jsonl` で**箱を先に空にする**
   - ★**退避先は必ず `local/_work/` (local/inbox/ の外)**。**`local/inbox/` の中へ退避してはいけない**——sweepは`local/inbox/*.jsonl`を全部走査しファイル名をdept名と解釈するため、`_<dept>_work.jsonl`のような隣接ファイルを「脈の無い部門箱」と誤認して**中身をmainへ流し空にする=退避したのに黙って消える**(QA/data-orgが実測・INC-86)。`local/_work/`が無ければ作る
   ② **即座にwaiterを再武装**(バックグラウンド起動)——脈が復活し、作業中の新着も自分の箱で受けられる
   - ★★**再武装はチャイム起床に限らない(INC-98)**: ワークフロー通知・部門便など**チャイム以外の理由で始まったターンでも、終える前に必ずwaiterの生存を確認**し、死んでいれば張り直す。waiterは**ハーネス管理の背景起動**で立てる(シェルの`&`やspawnは終了通知が届かず耳が死ぬ)。実例=main waiterがTTL全滅したまま9時間放置され、Chamiの「大至急」に3時間無応答(配達は20秒で成功していた=死んでいたのは耳だけ)。
   ③ その後落ち着いて `local/_work/<dept>.jsonl` を処理 → 処理済みは `local/discord_processed.jsonl` へ追記し、workファイルを削除
   - ★**承認が要る操作(SendMessage・分類器にかかりやすいコマンド等)はターンの末尾に置く**(応答性改善書P5・2026-07-18): 承認待ちはターンを数十分止める(QA実測36分)。その間この部屋は無人になる。先に部屋への応対・記帳を済ませ、ブロックし得る操作は最後に
   - ★**ターン中にチャイム(waiter完了通知)が届いたら、次の安全な区切りで必ずドレインする**(同P5): 通知を見てから長作業を続けると、その間に脈が切れて自室の新着がmainへ迂回する(QA実測=40分の調査中に6件流出)。作業を中断できない場合も、区切りごとに mv退避→再武装 だけは挟む
   - ★★**ドレインしたら記帳するまでが退避(INC-103)**: 箱を空けたら、**同じ手で処理済み台帳へ記帳する**まで手を止めない。「箱が空」≠「処理された」——箱は状態を持たず、台帳だけが記憶を持つ(深夜のドレインで未記帳のまま消えた実例あり)。
   - ★**進捗印を押す(4段階・2026-07-19改訂=Chami発案「即答」新設・QA合意)**: Chamiは絵文字だけで「未達/届いたが無人/読んだ/即答済み/着手済み」の状態を見ている。
     - **送信(📮/sendms)** = 鳩が箱へ入れた時に**自動**で付く(=届いた証明。Claudeが見たとは限らない)。手で押す必要なし。
     - **既読(✅/kidoku)** = **起床して読んだ直後に自分で押す**: `python scripts/discord/react.py --channel <ch名かID> --msg <msg_id> --emoji 既読`(=読んだ・返答/作業はこれから)
     - **即答(💬/sokutou)** = **その場の返事で完結した時に押す**: `--emoji 即答`(=既読のみとの曖昧さ解消。サーバー絵文字sokutou作成までは💬で代用=react.pyが自動フォールバック)
     - **着手(👀/chakusyu)** = **本格的に作業を始める時に押す**: `--emoji 着手`(即終わる案件でも作業を伴うなら押す)
     - **この手順がBOOT.mdに無かったため、手で立ち上げた窓は印を押していなかった**(常駐スクリプト経由の窓は起動文に入っていたので押せていた)=同じ穴に落ちないこと。
   - **理由**: waiterの脈は新着到達の瞬間に止まる(waiterは配達と同時に自了する)。旧手順(読む→処理→終わってから再武装)だと、**処理に90秒以上かかる案件は全て「常駐不在」と誤判定され、sweepが箱ごとmainへ奪う**(=研究室の代打が67%に膨らんだ主因・QA実測2026-07-17)。sweepは空の箱を触らないため、①のmv先行で奪われなくなる(INC-76のmv先行ルールの部門箱への適用)
3. 返信: `python scripts/discord/bot_send.py --dept <dept> "本文"`
   (キャラ発言は `python scripts/discord/persona_send.py` — 色/様式はlocal/persona_colors.json)
4. 横断ルール: `D:\SougouStartFolder\00_AI-HQ\PRIORITY.md` を一読(全体の優先度と衝突しないこと)
5. **ペルソナ台帳(INDEX.md)を読むツール(整合チェッカー等)を使う部門のみ**: 環境変数 `GO5_PERSONA_INDEX` にHQのINDEX.mdを指定してから実行する。ペルソナ台帳は2026-07-18にHQ直下へ移転済み(RULES.md§6=HQは運用ドキュメント専用・道具はrepoが正)。例: `GO5_PERSONA_INDEX="D:/SougouStartFolder/00_AI-HQ/departments/hr/personas/INDEX.md" python <tool>`。正本の場所=docs/departments/personas/README_移転.md。

## 責任範囲(所有権)
- 編集可: <この部門が所有するファイル/領域を列挙>
- それ以外は読み取りのみ(他セッションとの衝突防止=1領域1オーナー)
- 他部門宛て・横断案件を拾ったら: 自分で触らず、その旨をrouterへ送るか main箱へ残す

## 規約(共通)
- UI文言の括弧は半角() 。毎ターンの定型状態報告は出力しない(作業は無言・完了時1回)
- ★**新規ファイルは作成したターン内に「パス限定 add→commit」まで済ませる**(未コミットuntrackedは保護ゼロ=2026-07-18に実ファイル消失の実害)。**共有ツリーで git clean / stash -u / checkout -f / reset --hard は禁止**(orchestration.md 徹底事項8が正本)
- 引き継ぎは自己申告(時間ベースの限界前通知は撤去2026-07-15)。出力の退行・同型反復を自覚したら部門STATUS更新→memory更新→新セッションへ交代
- セッション終了時: 脈は放置でよい(10分で切れ、配達は自動でmain箱へ戻る=自己修復)

## 終了時
- 部門のSTATUS/正本を更新。大きな決定はHQ `status/5SecMovieMaker.md` にも1行。
