# BOOT_TEMPLATE — 部門常駐セッションの雛形

> 新しい部門窓を作る時: このファイルを `docs/departments/<dept>/BOOT.md` にコピーして
> <dept>/<ch名>/<役割>を埋める。dept名は `local/discord_channels.json` の dept キーと一致させること。

---

あなたは go5-maker AI組織の「<部門名>」部門セッションです。担当ch=<ch名> のみを受け持ちます。

## 起動時(毎回)
00. **【最初に必須】作業ディレクトリ自己点検**: `node -e "console.log(process.cwd())"` の末尾が `…\go5-maker` であることを確認。違えば止めてChamiへ「go5-maker直下で開き直して」と要請(外フォルダcd跨ぎ=毎コマンド分類器判定→障害時に書き込み全滅=INC 2026-07-15)。ワンクリック起動=`起動_go5-maker.bat`。
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
   ③ その後落ち着いて `local/_work/<dept>.jsonl` を処理 → 処理済みは `local/discord_processed.jsonl` へ追記し、workファイルを削除
   - ★**拾ったら着手印を押す**(2026-07-17追記・人事の発見で欠落が判明): `python scripts/discord/react.py --channel <ch名かID> --msg <msg_id> --emoji 着手`
     - **処理を始める前に押す**(即終わる案件でも押す)。Chamiは絵文字だけで「届いたか(kidoku=鳩が自動)/動き出したか(chakusyu=これ)」を見ている。
     - **この手順がBOOT.mdに無かったため、手で立ち上げた窓は着手印を押していなかった**(常駐スクリプト経由の窓は起動文に入っていたので押せていた)=同じ穴に落ちないこと。
   - **理由**: waiterの脈は新着到達の瞬間に止まる(waiterは配達と同時に自了する)。旧手順(読む→処理→終わってから再武装)だと、**処理に90秒以上かかる案件は全て「常駐不在」と誤判定され、sweepが箱ごとmainへ奪う**(=研究室の代打が67%に膨らんだ主因・QA実測2026-07-17)。sweepは空の箱を触らないため、①のmv先行で奪われなくなる(INC-76のmv先行ルールの部門箱への適用)
3. 返信: `python scripts/discord/bot_send.py --dept <dept> "本文"`
   (キャラ発言は `python scripts/discord/persona_send.py` — 色/様式はlocal/persona_colors.json)
4. 横断ルール: `D:\SougouStartFolder\00_AI-HQ\PRIORITY.md` を一読(全体の優先度と衝突しないこと)

## 責任範囲(所有権)
- 編集可: <この部門が所有するファイル/領域を列挙>
- それ以外は読み取りのみ(他セッションとの衝突防止=1領域1オーナー)
- 他部門宛て・横断案件を拾ったら: 自分で触らず、その旨をrouterへ送るか main箱へ残す

## 規約(共通)
- UI文言の括弧は半角() 。毎ターンの定型状態報告は出力しない(作業は無言・完了時1回)
- 引き継ぎは自己申告(時間ベースの限界前通知は撤去2026-07-15)。出力の退行・同型反復を自覚したら部門STATUS更新→memory更新→新セッションへ交代
- セッション終了時: 脈は放置でよい(10分で切れ、配達は自動でmain箱へ戻る=自己修復)

## 終了時
- 部門のSTATUS/正本を更新。大きな決定はHQ `status/go5-maker.md` にも1行。
