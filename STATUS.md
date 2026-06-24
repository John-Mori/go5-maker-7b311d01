# STATUS — 一本道運用化 改修（go5-maker）

> 改修書：`(添付)改修書：5秒動画メーカー「一本道運用化」`／一次情報：`CLAUDE.md`
> 起点バージョン：`?v=48`／最終更新：2026-06-25 (JST)
> 本ファイルは別セッション/別AIへの引き継ぎ前提。節目で更新する。

---

## 0. ロック済みの決定事項（Chami確認済 2026-06-25）

1. **進め方＝段階実装**。Phase A＝**記録層(3)→一本道(1)**から。各段で iPhone 実機確認を挟む。
2. **タスク2（YouTube再生数の自動取得）＝今は見送り**（後日。Data APIキー未発行）。
3. **GAS は拡張＋再デプロイOK**。`writeRecord_` を upsert 化／testMode 分岐を追加。
   - ⚠️ **実装直前にChamiへ要確認**：現行の GAS プロジェクト名・デプロイURL・記録先スプレッドシート（過去に別プロジェクト誤作成の経緯あり）。
4. **設定エクスポート(8f)の鍵**：エクスポートは**2ボタン**＝「🔒鍵を除いて書き出し（推奨）」「⚠️全部（鍵含む）」。全部側は警告を出す。書き出しファイルは手元限定・repo禁止。

---

## ★ 絶対に壊さない不変条件（改修書§の再掲・全工程で厳守）

1. 比率座標系（W=1080,H=1920、`H×係数`/`W×係数`、px/vh/vw禁止、`U(v)=v*H/1280`）。プレビュー＝書き出し一致。→ 8a/8b で特に厳守。
2. drive-worker は非破壊（create/read のみ）。
3. link-worker の `u:<code>` は不変。※現リポジトリ内に link-worker は未発見（要確認・後述「未解決」）。
4. GAS の `SHARED_SECRET` は未設定のまま（フロントは送らない）。
5. 変更後は `index.html` の `?v=N` を上げる。

---

## 1. フェーズ・ロードマップ

| Phase | 内容 | 状態 |
|---|---|---|
| **A** | 記録層(3)＋一本道(1) | 🟡 設計完了・実装未着手 |
| B | テストモード(4)＋重複管理(5) | ⬜ 未着手（記録層の後に自然接続） |
| C | UI改善 8a/8b/8c/8d | ⬜ 未着手（比率座標系厳守） |
| D | 説明欄補助(6)＋カレンダー分離(7) | ⬜ 未着手 |
| E | PWA＋設定入出力＋オートフィル対策 8e/8f | ⬜ 未着手 |
| （保留） | YouTube再生数(2)／Supabase本採用 | ⏸ スコープ外（後日） |

---

## 2. Phase A 詳細設計

### 2.1 安定動画ID（背骨の串）
- **発番タイミング＝動画作成時（投稿前）**。Bluesky の `cid`/`post_uri` は投稿後にしか出ないため、**cidに依存しない**形にする。
- **形式**：`{acc}-{YYYYMMDD}-{HHMM}-{rand4}`
  - 例：`acc1-20260625-1432-k7af`（`rand4`＝base36乱数4桁。同分内の重複回避）
  - テストモードは先頭に `test-` を付す：`test-acc1-...`
- **串刺し先**：①画面表示 ②Driveフォルダ名（`drive-upload.js`）③Bluesky記録 ④シート行キー。
- **シート行キー**：既存 `post_id` 列を**この安定IDで埋める**（列追加せずスキーマ最小変更）。`post_uri` は別列に従来どおり保存（投稿後に更新）。

### 2.2 記録の単位＝1動画（upsert化）
- **作成時**：フロントが安定ID発番→GASへ `status=未投稿` の行を **upsert（新規作成）**。
- **YouTube手動投稿後**：同ID行へ `youtube_url` を upsert（列が無ければ後日追加。Phase Aでは任意）。
- **Bluesky投稿成功時**：同ID行へ `post_url/post_uri/short_url/status=公開済` を upsert。
- **upsertキー**：`post_id`（＝安定動画ID）。一致行あれば**変更フィールドのみ更新**、無ければ新規。
  - → 現状の「空行再利用＝上書きリスク」を解消。同IDで複数回送っても行は増えない。

### 2.3 GAS 変更（`gas/コード.gs`）
- `doPost` に **op を導入**（後方互換：op無し＝従来の記録）。
  - `op:'upsert'`：`post_id` で検索→upsert（changed-fields only）。
  - `testMode:true`：**シート書き込みを一切しない**で `ok` を返す（Bluesky実投稿はフロント側で実施）。
- `doGet`（JSONP）の `action=history|delete|lookup` は**既存を流用**（タスク5で本格利用）。
- `SHARED_SECRET` は未設定のまま（不変条件4）。
- **再デプロイ**：Chamiが「デプロイを管理→鉛筆→新バージョン」。対象プロジェクト/シートを実装直前に確定。

### 2.4 フロント変更
- 新規 `idgen.js`（純粋関数 `makeVideoId(acc, date, isTest)`）＝テスト可能に分離。
- `drive-upload.js`：保存フォルダ名を「タイトル」→「**安定ID＋タイトル**」へ（取り違え防止。要Chami確認＝フォルダ命名の好み）。
- `bluesky.js` `recordToSheet`：payload に `videoId`/`op:'upsert'`/`testMode` を追加。投稿成功時は同IDで upsert。
- 動画作成完了（`video-created`）で**未投稿行を upsert**する配線を追加（現状は投稿時のみ記録）。

### 2.5 一本道ウィザード（`wizard.js` 新規）
- **入口**：主＝「🎬今から1本」ボタン（動画作成タブ上部）／従＝カレンダーのスロット（既存 postMessage 経由）。どちらも同じウィザードを起動。
- **持ち回す文脈**：`{ workUrl, affLink, account, slotId, videoId, title }`。
- **流れ**（既存エンジンを被せるだけ）：
  1. 作品URL貼付→`buildAffiliateLink()`でアフィリンク生成＋acc選択（＋任意スロット）
  2. 動画作成→`video-created`で**ID発番＋未投稿行upsert＋Drive保存**（既存）
  3. **〔手動ゲート〕YouTube**：説明文（アフィリンク内包）生成＋コピー→Chami手動投稿→**YouTube URL貼付で記録**→「上げたら次へ」
  4. **Bluesky投稿**（テンプレ＋同一アフィリンク＋タグ、既存 `blueskyPostRaw`）
  5. **記録＆スロット確定**（同IDで upsert＝公開済、カレンダー writeback）
- **背骨**：1で作ったアフィリンク1本を3・4で使い回し＝作品取り違えを構造的に防止。

### 2.6 テスト（4.5）
- 追加（純粋関数・Nodeテスト、既存31ケースに上乗せ・全PASS維持）：
  - `makeVideoId` の形式・テスト接頭辞・乱数桁。
  - upsert判定ロジック（同ID→更新／別ID→新規）を純粋関数として切り出してテスト。
- 実機：iPhone Safari で「作成→（手動YT）→Bluesky→記録」が1本道で回ること、同IDで行が増えないこと。

### 2.7 Phase A で触るファイル
- 新規：`idgen.js`, `wizard.js`, `tests/test_idgen.js`, `tests/test_record_upsert.js`
- 改修：`gas/コード.gs`（upsert/testMode）, `bluesky.js`（recordToSheet/配線）, `drive-upload.js`（フォルダ名）, `index.html`（ウィザードUI＋`?v=`↑＋script追加）, `integration.js`（スロット起点の橋渡し）

---

### 2.8 シートURLは短く保つ（Chami要望 2026-06-25）
- **YouTube**：長い watch URL を記録しない。記録時に**`youtube_id`(11文字) を抽出**して列に持ち、表示用は**短縮URL(da.gd)** を別列へ。
  - **再生数(タスク2)は `videoId` で取得**するため、短縮しても**カウントに影響なし**（短縮URLは元URLへのリダイレクトでvideoIdは不変）。
  - 短縮は `bluesky.js` の `shortenUrl`（da.gd優先・既実装 v=47）を流用。videoId抽出は `idgen.youtubeId()`。
- **アフィリンク(FANZA)は絶対に短縮しない**（af_id計測が壊れる。生のまま記録）。
- **Bluesky**：既存 `短縮URL` 列（da.gd）を流用。

### 確定（#3/#4）
- #3：Driveフォルダ名＝**`{ID}_{タイトル}`**（取り違え防止。承認済）。
- #4：シートに **`youtube_id`＋`youtube_short`** 列を足す（長いURLは持たない。承認済）。

### 2.9 短縮URLの統合方針（2セッション分裂を解消・2026-06-25）
- **link-worker（自前短縮 `go5-short`）を main に集約＋Cloudflareへデプロイ済**：`https://go5-short.trustsignalbot.workers.dev`（302即リダイレクト・中間ページ無し・KVクリック計測・`u:<code>`不変＝不変条件3を満たす実体）。KV id は wrangler.toml にコミット済。`SHARED_SECRET` は Worker Secret（リポジトリには置かない・frontend接続時に同値を使用＝ソフト鍵）。`ALLOWED_HOSTS=bsky.app,bsky.social,youtube.com,youtu.be`（**dmm=アフィリンクは短縮しない＝生のまま**）。
- **★核心の制約**：workers.dev ドメインだと短縮URLが**52字＝長い**（da.gd は19字）。Chami要望「x.gd並みに短く」を満たすには **link-worker に短い独自ドメインが必要**。
- **当面の正＝da.gd**（短い・稼働中）。独自ドメインを付けたら bluesky.js の1行で link-worker を主に切替（→ 短い＋自前クリック計測）。
- frontend shortenUrl 将来形：`link-worker(短ドメイン時)→da.gd→長URL`。is.gd/cleanuri は**CORS不可で不採用**。
- branch `claude/vigilant-mendel-wjbvg5`：link-worker/と全体設計書を main へ取込済。**branchのbluesky.jsは不採用**（main v=48＝da.gd＋接続テストを維持）。branchは削除可。
- **次のfrontend編集から `?v=49`**（branchが名乗ったv=48は破棄・番号衝突解消）。

## 3. 未解決・要確認
1. **【短縮URL】短い独自ドメインを link-worker に付けるか？**（付ければ「短い＋自前クリック計測」両立。費用＝ドメイン年額。付けないなら da.gd 継続）。Cloudflareログインを要する作業＝このPC環境からのみ可。
2. **現行GASの特定**：プロジェクト名／デプロイURL（`bsky_gas_url`の実値）／記録先スプレッドシートID。GAS再デプロイ前に確定必須。
3. ~~link-worker の所在~~ → ✅ 解決（main に集約・デプロイ済）。

---

## 4. 納品物（最終）
- ① 手順書（一本道の使い方・テストモード・Qセーブ等・設定入出力・ホーム画面追加）
- ② 最終レポート（問題/想定外/方式選定/テスト結果/セキュリティ判断）

## 5. 作業ログ
- 2026-06-25：事前チェック(§2)を4サブエージェントで完了。決定事項4件をロック。Phase A 設計確定。短縮URL=da.gd化(v=47)・Bluesky接続テスト(v=48)は別件で実装済。
- 2026-06-25：シートURL短縮の要望を設計反映（YouTube=videoId+短縮URL／アフィリンクは生のまま）。**`idgen.js` 実装＋`tests/test_idgen.js`（10 PASS）**。既存31ケース回帰なし＝合計41 PASS。`idgen.js` は未登録（公開無影響）。次＝記録コントラクト配線＋`wizard.js`。

## 6. Phase A 記録コントラクト（フロント→GAS。配線/ウィザード実装の基準）
動画作成〜投稿で、**同一 `videoId` を upsert キー**に2回送る。GASは `op:'upsert'` を `post_id` で突き合わせ、変更フィールドのみ更新。
- **(2) 動画作成時**：`{ op:'upsert', videoId, channel, title, status:'未投稿', testMode }`
- **(5) Bluesky投稿成功時**：`{ op:'upsert', videoId, channel, post_url, post_uri, short_url, status:'公開済', testMode }`
- **(3) YouTube手動投稿後**（任意）：`{ op:'upsert', videoId, channel, youtube_id, youtube_short, status:'YT済' 等 }`
- `testMode:true` の時、GASは**書き込まない**（Bluesky実投稿はフロントで実施）。
- Content-Type 無指定POST（simple request／プリフライト回避）は現状踏襲。`SHARED_SECRET` 未送信のまま。
- アフィリンクは payload に**生のまま**（短縮しない）。
