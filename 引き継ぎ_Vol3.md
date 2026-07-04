# 引き継ぎ — Vol.3 キックオフ（go5-maker）

> **新しいチャット(Vol.3)を始めたら、まずこのファイルを読む。**
> 一次情報は `CLAUDE.md`。インシデント台帳は `インシデント.md`（巻をまたぐ通し番号）。
> このファイルは「Vol.2 の到達点」と「Vol.3 への持ち越し」を1枚にまとめた俯瞰図。食い違いは実コード＋`CLAUDE.md` が優先。

最終更新: 2026-07-04 ／ 巻の切り替え: **Vol.2 → Vol.3**

---

## 0. 現在の到達点（このファイル作成時点）

| 項目 | 状態 |
|---|---|
| 公開バージョン(live) | **`?v=192`**（`https://john-mori.github.io/go5-maker-7b311d01/`） |
| GAS_VERSION | **`2026-07-05G`**（`?ping=1` で照合可） |
| ブランチ / 作業ツリー | `main` / **クリーン（未コミットなし）** |
| 直近コミット | `8b48279 投稿画像/Bluesky画像: 画像貼り付け＋Twitter候補の作品変換 (v192)` |
| デプロイ | GitHub Pages（`.nojekyll` でJekyll無効化済＝INC-66）。反映確認は `curl .../index.html?cb=<ts> \| grep 'candidates.js?v='` |

**機密ファイル（絶対にコミットしない）**：`scripts/scrape_config.json` / `scripts/gas_deploy_config.json`（adminSecret/sharedSecret/execUrl）は `.gitignore` 済。追跡されているのは `*.example.json` のみ。

---

## 1. Vol.2 でやったこと（v88 → v192 の要約）

一次の詳細は各コミットメッセージと `インシデント.md`（INC-49〜66）。大きな塊は5つ：

1. **💡候補タブ（新設〜拡張）**：サークル作品一覧／URL正規化(v168)、レビュー件数=売れ行き目安・ジャンル/作品状態バッジ・並べ替え(v169-172)、**実売本数=販売数**表示(v174)、タブ名だけの独立候補タブ(v177)、単体候補もサークルと同操作性＋画像モーダル(v178)、販売数のプレーン化＋Bluesky添付画像＋貼り付けボタン(v180)、**Twitter(X)のURLだけでも候補追加**(v191)、投稿画像/Bluesky画像に**画像貼り付け＋Twitter候補→作品変換**(v192)。

2. **販売数取得パイプライン（端末非依存）**：PC(日本IP)→KV→worker→フロント で実売本数を配信(v174)。**15分自動実行＋スマホから「▶今すぐ取得」リモートトリガー**(v176)。PC側スクリプト＝`scripts/fetch_sales.mjs`・`sales_poll.bat`・`register_sales_task.ps1`。`.bat`はCRLF＋UTF-8(BOM無)、日本語`.ps1`はUTF-8 BOM（INC-58）。

3. **投稿履歴タブ／ランキング／サーバー自動記録**：再生数・クリックをGASで**サーバー自動記録**＋各投稿に今日/昨日/週の増加表示(v152)、経過時間バケット別ランキング(v151)、最大瞬間風速ランキング(v153)。

4. **GAS自動反映（clasp）**：手動コピペ・手動再デプロイを全廃。ローカル `node scripts/deploy_gas.mjs` で反映（**`GAS_VERSION` を上げてから**実行）。設計＝`docs/設計・調査/GAS自動反映_設計書.md`。

5. **アカウント帰属の恒久対策（最重要・INC-62〜65）**：月詠み(acc1)/宵桜(acc2)の投稿履歴混在を根治。**所属はデータ(post_uriのDID)で確定**(v184)、クラウド同期の再汚染を止める(P0/v185)、手動移動＋GAS `move_row`、YouTubeチャンネルID自動分類＋無人予約のch別資格(v186)、誤移動の修正＝検出と適用を分離・台帳検証・アンドゥ(v187)、**シートから投稿履歴を復元**(v188-190)、YouTube URL履歴の復元(v181)。設計＝`設計_投稿履歴アカウント混在の恒久対策.md`。

その他：FANZA Books(`book.dmm.com`)対応(v165/179)、作者名自動入力(v155)、API未収録作品のワンクリック補完(v179)、`.nojekyll`でデプロイ恒久修正(INC-66)。

---

## 2. Vol.3 への持ち越しタスク（未着手）

### 2-1. 🦋 バズタブ（このセッションで巻き戻し済＝要再実装）
親候補タブの左端に「🦋 バズ」タブを設け、**月詠み/宵桜がフォローしているBlueskyアカウントの投稿をエンゲージメント順に並べる**機能。Vol.2末に着手したが未完成（`renderBuzz()`未実装＝押すとJSエラー）のため **巻き戻し済（v192＝クリーン）**。Vol.3で腰を据えて実装する。

実装メモ（Bluesky公開API・認証不要・CORS可 `public.api.bsky.app/xrpc/`）：
- `resolveHandle` で acc1/acc2 のDID取得（`bsky_did__acc1/acc2` に既存）。
- `app.bsky.graph.getFollows?actor=<did>&limit=100&cursor=` をページング取得 → **DIDでunion＋重複削除**（両方がフォローするアカウントの二重表示を防ぐ）。
- 各フォロー先の `app.bsky.feed.getAuthorFeed?actor=<did>` で最近の投稿取得。
- **エンゲージメント = likes+reposts+replies+quotes** の降順で並べる。※**Blueskyはインプレッション(表示回数)を公開していない**ため、エンゲージメントが唯一の代理指標。UIでもその旨を明示する。
- TTLキャッシュ＋🔁更新。**API呼び出し数に上限・並列数制限**を必ず入れる（フォロー数×フィードで膨らむ）。
- 触るのは `candidates.js`（タブボタン `data-ct="buzz"`、render dispatch、`reorderable()` からbuzz除外、`renderBuzz()`本体）＋ `style.css`。巻き戻したので**タブボタン等も再度追加が必要**。

### 2-2. アプリ外Bluesky投稿の自動取り込み（要否をChamiに確認してから）
「各アカウントがBlueskyに投稿したらURLを取得・登録しクリック監視」について：
- **アプリ経由の投稿は既に完成**＝投稿時に post_uri/URL を登録し、計測用短縮リンク(r2/da.gd)でクリック監視、いいね/RT/返信も取得（📋投稿履歴タブ）。
- **未対応＝Blueskyアプリ等から直接した投稿**。`getAuthorFeed` で取り込み→履歴登録＋エンゲージメント表示は可能。ただし**クリック数は計測リンクが本文に入っている投稿のみ**（Blueskyは生リンクのクリックを公開しない）。
- → やるかどうかは Vol.3 冒頭で確認する（Chamiは 2-1 のバズタブを優先指定）。

---

## 3. 反映・運用のルール（Vol.3でも厳守）

- **フロント変更後は `index.html` の `?v=N` を必ず上げる**（48箇所一括。PowerShellで UTF-8 no-BOM の ReadAllText→replace→WriteAllText）。次の変更から **`?v=193`**。
- **GAS変更後は `GAS_VERSION` を上げてから** `node scripts/deploy_gas.mjs`。反映確認は `?ping=1`。clasp の `.gs`/`.js` 取り違えに注意（過去のハマり）。
- **デプロイ確認は必ずlive照合**：`curl .../index.html?cb=<ts>`。GitHub Pagesは稀に一時失敗（"Deployment failed, try again later"）→ `gh run rerun <databaseId>`。`.nojekyll` は消さない。
- **実装完了後は `git commit && git push` まで**やる。コミット末尾に `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`。
- **配色ルール**：よくあるClaude風の紫UI（#5b3f8e系）は禁止。アカウントテーマ配色（acc1=宵藍系 / acc2=葡萄梅系）に合わせる。
- **Python は `py -3.12`**（bare `python` は 3.14 を呼ぶ）。
- **不変条件**：比率座標系（W=1080/H=1920）、drive-worker非破壊、link-worker `u:<code>`不変、GASの`SHARED_SECRET`未設定、秘密はSecrets/Propertiesのみ。

---

## 4. 一次情報・参照先

| 目的 | ファイル |
|---|---|
| 公式コンテキスト（最新仕様） | `CLAUDE.md` |
| ミス台帳（巻またぎ・INC通し番号） | `インシデント.md`（Vol.2＝INC-49〜66） |
| アカウント混在の恒久対策 設計 | `設計_投稿履歴アカウント混在の恒久対策.md` |
| GAS自動反映 設計 | `docs/設計・調査/GAS自動反映_設計書.md` |
| 全体アーキ俯瞰（やや古い・v48基準） | `プロジェクト全体設計書_AI引き継ぎ用.md` |
| Phase A 期の作業ログ（〜v87で停止） | `STATUS.md` |
