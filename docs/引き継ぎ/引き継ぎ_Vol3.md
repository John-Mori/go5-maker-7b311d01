# 引き継ぎ — Vol.3 キックオフ（go5-maker）

> **新しいチャット(Vol.3)を始めたら、まずこのファイルを読む。**
> 一次情報は `CLAUDE.md`。インシデント台帳は `インシデント.md`（巻をまたぐ通し番号）。
> このファイルは「Vol.2 の到達点」と「Vol.3 への持ち越し」を1枚にまとめた俯瞰図。食い違いは実コード＋`CLAUDE.md` が優先。

最終更新: 2026-07-04 ／ 巻の切り替え: **Vol.2 → Vol.3**

---

## 0. 現在の到達点（このファイル作成時点）

| 項目 | 状態 |
|---|---|
| 公開バージョン(live) | **`?v=193`**（`https://john-mori.github.io/go5-maker-7b311d01/`） |
| GAS_VERSION | **`2026-07-05G`**（`?ping=1` で照合可） |
| ブランチ / 作業ツリー | `main` / **クリーン（未コミットなし）** |
| 直近コミット | `39715fe 🦋バズタブ: フォロー中Blueskyのバズ投稿をエンゲージメント順に表示 (v193)` |
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

### 2-1. 🦋 バズタブ ✅ 実装済（v193 / commit 39715fe）
親候補タブの左端に固定「🦋 バズ」タブを新設し、**月詠み/宵桜がフォローしているBlueskyアカウントの投稿をエンゲージメント順に並べる**機能を再実装・公開済。ブラウザ実機で resolveHandle→getFollows→getAuthorFeed→60件をエンゲージメント降順で描画・リンク動作・JSエラー無しを確認済。

実装内容（`candidates.js` §🦋バズタブ ＋ `style.css` `.buzz-*`）：
- Bluesky公開API（未認証・CORS可 `public.api.bsky.app/xrpc/`）のみ。`bsky_handle__acc1/acc2`／`bsky_did__acc1/acc2` を直読み。DID欠落時のみ `resolveHandle` で解決・保存。
- `getFollows` をページング（`BUZZ_FOLLOW_PAGES=3`＝最大300/アカ）→ **DIDでunion＋重複削除**、自分自身も除外。
- 各フォロー先 `getAuthorFeed`（`filter=posts_no_replies`・`limit=15`）。リポスト(reason付き)は除外＝本人投稿のみ。直近`BUZZ_RECENT_DAYS=14`日で絞る。
- **エンゲージメント = like+repost+reply+quote** の降順。**インプレッション非公開**の旨をUIヘッダに明示。
- API量の上限：`BUZZ_MAX_FEEDS=120`（超過時は「上位120人」注記）／並列プール `BUZZ_CONCURRENCY=5`／`BUZZ_TTL=30分`キャッシュ（`cand_buzz_cache`・対象集合キーで判定）＋🔁で強制更新。表示`BUZZ_SHOW=60`。
- 固定タブ判定は `isFixedCandTab_(id)`（`main`/`buzz`）で `reorderable()`・ドラッグ・`commitTabOrder_` から除外。
- 調整余地（将来）：日数/件数/並列の各定数はファイル冒頭にまとめてある。画像embedはサムネのみ表示（モーダルは未配線）。

### 2-2. アプリ外Bluesky投稿の自動取り込み → ❌ やらない（2026-07-04 Chami決定）
「フォロー先の投稿URLを取り込んでクリック監視」は**やらないと確定**。理由＝**他人の投稿のクリック数はBlueskyが公開しておらず原理的に取得不可**（計測できるのは自分が短縮リンクを仕込んだアプリ経由の投稿だけ＝📋投稿履歴タブで実装済）。フォロー先について取れるのはエンゲージメントのみで、それは🦋バズタブ(§2-1)で表示済のため、この項目は不要と判断。将来やるとしても「履歴取り込み＋いいね等追跡」まで（クリックは不可）。

### 2-3. 📘 改善ロードマップ（2026-07-05策定・Vol.3の中期計画）
**`docs/設計・調査/改善書_Shorts攻略と全体改善ロードマップ.md`** に、①作りやすさ②データ分析③保守性④**Shortsフィード攻略(最重要)** の4本柱で Phase 0〜4 のタスク表（触るファイル・受け入れ条件・Opus/Sonnetモデル割当つき）を策定済み。**裁定4項目＋追加前提は決定済み（2026-07-05 Chami）**: KPI=**engagedViews**／尺=**「1コマ5秒」はコンサル実証済み手法で不変**（同手法のコンサル生が月90万突破・課題は行動量とコツ掴み）／Data API監査=**申請する**／リファクタ=**M-1をPhase 0で先行**／**音源はYouTubeアプリ側で付与**（無音生成は仕様・BGM焼き込みS-2は不採用）。次にやるのは改善書§8 Phase 0: P0規約防衛の明文化・S-6・U-7（wizardイベント不達バグ修正）・M-1共通コア3ファイル。その後 Phase 1= S-1a背景シームレスループ化（演出不変）・D-1取りこぼし回収・S-3メタデータ整備・U-2候補から一気に作成。**S-1b（フェード見直し）は恒久不採用**（フェード演出=コンサル指定と確定・演出変更系の提案自体禁止）。**S-2'（音源リマインド/音源名記録）も不採用**（運用で管理）。

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
