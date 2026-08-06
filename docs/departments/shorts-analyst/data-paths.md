# data-paths.md — 数字の引き方(shorts-analyst・正本)

> 全経路2026-07-18に疎通[実測済み](多角調査ワークフロー)。正本ポインタ: actionの正=gas/コード.gs doGet:111-188・exec URLの正=docs/departments/qa-reviewer/STATUS.md §3-2(本書へは転記しない=二重管理回避)。
> **秘匿値(SHORT_SHARED_SECRET/ADMIN_SECRET/APIキー)の実値を本書・レポート・Discordへ書き出さない。**

## 経路1: GAS Web App(無認証・可搬)

- 疎通: `curl -sL "<exec>?ping=1"` → GAS_VERSION一致を確認してから使う。
- **deltas**(増分・JSONP): `curl -sL "<exec>?action=deltas&callback=cb"` → `cb(...)`を剥がす。フィールドの意味=metric-definitions.md M-01〜M-04。
  - ★戻り値は `{deltas, peaks, timepoints}` の**3ブロック**。`.deltas`(wv=週再生増)だけ見て `.timepoints`/`.peaks` を見落とすな(2026-08-06にこの見落としで「投稿後初速は取れない」と誤答した実例あり)。
  - **`.timepoints`=投稿後の経過時間別スナップ(初速の正体)**: `{ videoId: { b30,b60,b120,b360,b1440,b4320: {v(再生),c(クリック),age(実経過分)} } }`。バケット=投稿後 30分/1時間/2時間/6時間/24時間/72時間。GAS10分トリガーが `captureTimepoints_` で境界+0〜9分に記録=**アプリ未起動でもサーバー側で貯まる**(computeTimepoints_・コード.gs:1817)。**wvと違い年齢正規化済み**(全動画を投稿後同経過時間で比較できる=減衰交絡が無い)。UIは🏆ランキングタブの「30分/1時間/…/72時間」がこれ(client `captureSnaps_`(snap)と `rank-core.js pickBucketRec` で合成)。
  - **`.peaks`=最大瞬間風速**(computePeaks_)。
- **history**(投稿履歴・JSONP): `curl -sL "<exec>?action=history&channel=acc1&limit=10&callback=cb"`(acc2も)。postUri/title/postedAt/shortUrl/videoId等。クリック数・いいね・カテゴリは**含まれない**。
- **stats_tail**(視聴履歴末尾): `curl -sL "<exec>?action=stats_tail&n=20"`(plain JSON)。n≤20固定・totalRows付き。
- **競合**(plain JSON・callback不要): `?action=comp_digest`(週次サマリ)・`?action=comp_titles&days=30&top=50`(速度順タイトルコーパス)。
- JSONP剥がしワンライナー例: `curl -sL "<exec>?action=deltas&callback=cb" | python -c "import sys,json;s=sys.stdin.read();print(json.dumps(json.loads(s[s.index('(')+1:s.rindex(')')]),ensure_ascii=False))"`

## 経路2: D1直SQL(家PC認証依存・読み取りのみ)

- `npx wrangler d1 execute go5_kaizen --remote --json --command "SELECT ..." --config D:\SougouStartFolder\go5-maker\fanza-worker\wrangler.toml`
- go5_fanzaはdatabase名の差し替えのみ(works表: cid/title/sales_n/sales_at)。手本=scripts/kaizen/summarize_user_events.py(subprocessで呼び`[`以降をJSONパース)。
- **SELECTのみ**(D1書き込みは研究室所掌)。MacBook等では要再認証(可搬でない)。

## 経路3: link-worker クリック実数

- `curl -s "https://r2.trustsignalbot.workers.dev/api/stats?code=<code>&secret=<実値は書かない>"` → {ok,code,exists,clicks}。
- code=historyのshortUrl末尾。secretの参照先=gas/コード.gs shortSecret_()。旧ホストgo5-short.…も有効。

## 経路4: Bluesky公開API(無認証・可搬)

- `curl -s "https://public.api.bsky.app/xrpc/app.bsky.feed.getPosts?uris=<at://...>&uris=..."`(最大25件/回) → likeCount/repostCount/replyCount/quoteCount。
- URL組み立て/パースの純粋関数=リポジトリ直下verify-core.jsのbuildGetPostsUrl/parseEngagement。

## 罠5点(知らないと数字を誤読する)

1. deltas/historyは**JSONP専用**(callback必須・cb()剥がしが要る)。
2. deltasは**channelを見ない=全ch混在**。videoIdのacc1-/acc2-接頭辞で自力分離。
3. stats_tailは**n≤20固定**。時系列全量(564行超)は現状引けない。
4. historyの**postUri空行はYouTube主体投稿で正常**(エンゲージメント分析の対象行は限られる)。
5. wrangler経路は**家PCのCloudflare認証依存**。可搬なのはGASとBluesky。

## 取れない数字と対処

| 数字 | 理由 | 対処 |
|---|---|---|
| 記録シート全行(いいね・カテゴリ列込み) | 読み出しactionが無い | GASへrecords/stats_range追加を提案予定(**GAS無認証delete是正の完了まで凍結**=STATUS.md) |
| 視聴履歴の**30分毎**時系列全量(564行超) | stats_tail n≤20 | 同上 |
| ~~投稿後の経過時間別再生/クリック(初速)~~ | ~~取れない(と誤認)~~ | **★取れる**=`deltas` の `.timepoints`(上記経路1)。2026-08-06訂正。基盤凍結の対象外 |
| FANZA成約(verify_fanza)・カレンダー状態(sch_state_v1) | 端末localStorage閉じ込め(同期許可リスト外) | 成約は観測不可が確定=追わない |
| 任意videoIdの即時再生数 | YT_API_KEYはGAS側のみ | GAS間接値(deltas/stats_tail)で代替 |
