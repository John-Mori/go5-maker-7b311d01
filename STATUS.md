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
1. ~~【短縮URL】短い独自ドメインを付けるか~~ → ✅ **決定（Chami 2026-06-25）：da.gd 継続**（独自ドメインは見送り）。link-worker は**デプロイ済のまま待機**（frontend未接続。将来クリック計測＋独自ドメインが要れば bluesky.js 1行で有効化）。**短縮URLの分裂は完全解消・これ以上の作業不要。**
2. **現行GASの特定**：✅ **デプロイURL確定（Chami提供 2026-06-25）**＝`https://script.google.com/macros/s/AKfycbyQlrWuud5WfE3YMjoYzX2WhstTyWw_sOxVCaT8EfaFMXwi_WZzWIBKarHdtXVsY3Fj/exec`（フロント `bsky_gas_url` と同じはず）。残：プロジェクト名・記録先シートID（再デプロイ時に Apps Script 画面で確認。**新規プロジェクトは作らず「デプロイを管理→既存→新バージョン」**で更新＝別プロジェクト誤作成を回避）。
3. ~~link-worker の所在~~ → ✅ 解決（main に集約・デプロイ済・待機）。
4. **`wizard.js` の所有（どのsessionが実装するか）**：PC側(main)とスマホ側branchの両方が「次＝wizard.js」を持つと再分裂する。**どちらか一方に固定**したい。背骨ID串刺し（§5末）は配線済なので、wizard はその上に被せるだけ。
5. **記録コントラクト(§6)の実装単位**：(a)フロント payload を `op:'upsert'`/snake_case 化 と (b)GAS の upsert/testMode 化 は**同一作業として同時に**行う（片側だけ先行させない）。実施は §3-2 のGAS確定後。

---

## 4. 納品物（最終）
- ① 手順書（一本道の使い方・テストモード・Qセーブ等・設定入出力・ホーム画面追加）
- ② 最終レポート（問題/想定外/方式選定/テスト結果/セキュリティ判断）

## 5. 作業ログ
- 2026-06-25：事前チェック(§2)を4サブエージェントで完了。決定事項4件をロック。Phase A 設計確定。短縮URL=da.gd化(v=47)・Bluesky接続テスト(v=48)は別件で実装済。
- 2026-06-25：シートURL短縮の要望を設計反映（YouTube=videoId+短縮URL／アフィリンクは生のまま）。**`idgen.js` 実装＋`tests/test_idgen.js`（10 PASS）**。既存31ケース回帰なし＝合計41 PASS。`idgen.js` は未登録（公開無影響）。次＝記録コントラクト配線＋`wizard.js`。
- 2026-06-25（スマホ別session・branch `claude/vigilant-mendel-wjbvg5`）：**背骨ID串刺しを配線（GAS非依存・後方互換の安全分のみ）**。
  - `app.js`：動画作成時に `IdGen.makeVideoId(account)` を発番し `video-created` detail に `videoId/account` を載せて配布。
  - `idgen.js` を `index.html` に登録（app.js より前）。`?v=48→49`。
  - `drive-upload.js`：保存フォルダ/ファイル名を **`{ID}_{タイトル}`**（承認#3。Worker変更不要＝同名連番ロジックそのまま）。
  - `bluesky.js`：記録 payload に `videoId` を追加（旧GASは無視＝**後方互換**／upsert化後に行キー `post_id` として活用）。`currentVideoId` を `video-created` で常時保持。
  - 全テスト **41 PASS / 0 FAIL**（回帰なし）。
  - **未実施（ゲート明示）**：(a) GAS の `op:'upsert'`/`testMode`＋作成時「未投稿」行 ＝ §6 の snake_case 契約は **GAS本体とセットで実装**（旧GASに `op:'upsert'` を送ると未投稿行が量産されるため。§0.3/§3.2 のGASプロジェクト・シート確認が前提）。(b) `wizard.js` ＝ PC側(main)と**二重実装＝再分裂の恐れ**のため所有確認待ち（§3-4）。
- 2026-06-25（同session・「任せる」でPhase A所有を当sessionに確定）：**記録層(3)の本体＝GAS upsert を後方互換で実装**。
  - **所有確定**：以後の Phase A（記録層→wizard）は当session（branch `claude/vigilant-mendel-wjbvg5`）で進める。PC側(main)は wizard/記録層に着手しないこと（再分裂防止）。
  - `gas/コード.gs`：`doPost` に `testMode`（書かずok）＋ `videoId` を追加。`writeRecord_` を **upsert化**（`videoId` があれば `post_id` 列で同ID行を探し、無ければ従来の空行再利用/追記。更新は `putIf` で**空値クランプ無し**、カウンタ0初期化は新規行のみ）。純粋関数 `upsertRowOf_` に分離。
  - `bluesky.js`：投稿記録 payload に `op:'upsert'`／`status:'公開済'` を追加（既存 `videoId` と併せ §6 を camelCase で実装＝**現行GASのフィールド名を壊さない選択**。§6のsnake_caseからは意図的に逸脱・要同期）。
  - 新規 `tests/test_record_upsert.js`（6 PASS／`upsertRowOf_` のミラー）。全テスト **47 PASS / 0 FAIL**。
  - **後方互換が要**：旧GAS（未デプロイ）でも `op`/`videoId`/`testMode` を無視して従来通り1行追記＝壊れない。**GAS再デプロイは任意・好きな時**で、やると同ID行へ upsert（重複行が消える）。手順は応答に明記。
  - **まだ送っていない**：作成時「未投稿」行（旧GAS量産回避のため、GAS再デプロイ確認後にwizardで導入）。`status`列はテンプレに無く現状未書込（将来#4で列追加時に有効化）。
- 2026-06-25（同session・Chami判断「Bitly撤去＋GASスリム化」）：**Bitly を全廃（無料枠オーバーの主因）・GASをスリム化**。
  - **診断**：記録ごちゃごちゃの主因は **Bitly無料枠**（`bitlyShorten_`/`bitlyClicks_` が制限で失敗→短縮URL空・クリック未更新）。加えて `refreshClicks` が1行ずつUrlFetch+sleepで毎時最大500回＝消費者枠のトリガー90分/日に接近し黙って落ちる副因。Bitlyは既に冗長（共有はda.gd/link-worker・Bitlyリンクは誰も踏まず計測不能）。
  - `gas/コード.gs`：`bitlyShorten_`/`bitlyClicks_`/`refreshClicks` を**削除**。`daGdShorten_`（da.gd・1投稿1回・トークン不要）に置換。`writeRecord_` は **フロント生成の `shortUrl` を優先**、無い経路（無人予約/旧クライアント）だけ da.gd 短縮。`Bitly_ID` 書込を停止。`setupTrigger` から `refreshClicks` トリガーを撤去（`refreshEngagement` のみ毎時）。テンプレ列 `Bitly_ID`/`Bitlyクリック` は温存（未使用・将来 link-worker クリックへ転用可）。`BITLY_TOKEN` プロパティ不要に。
  - `bluesky.js`：投稿記録を「即時記録 → 短縮URL確定で同一行へ upsert 追記」に変更（`shortenAndShow` に `onShort` コールバック追加。`videoId` ある時のみ追記＝二重行なし）。payload に `shortUrl` 追加＝**シートの短縮URL列に“実際に共有するURL”が入る**ように。
  - 全テスト **47 PASS / 0 FAIL**（回帰なし）。**GAS再デプロイは任意**（未デプロイでも記録は従来通り動く。デプロイで毎時Bitlyフェッチが消え安定＋短縮URLが正しく入る）。
  - **クリック「回収」の follow-up**：da.gd はクリックAPI無し。本物のクリック計測が要るなら共有リンクを link-worker に切替（短さ妥協 or 独自ドメイン）→ `/api/stats` をGASかフロントで取り込み `Bitlyクリック` 列へ。これは §3-1 の保留（da.gd継続）と表裏。
- 2026-06-25（同session・Chami目的確定＝**2段ファネルの計測**）：測りたいのは ①YT説明欄の短縮URLの**開封数**（YT→Bluesky）と ②投稿内**FANZAアフィリンクの踏破数**（Bluesky→FANZA）。いいね/リポストは「URL入口」ゆえ付かず指標外。成約はFANZA管理画面が正。
  - **②は却下（Chami判断）**：アフィリンクは**生のまま**（link-worker経由にすれば踏破数は取れるが、方針反転＋FANZA規約マスキング禁止の懸念）。→ 投稿単位の踏破数は測らない。
  - **①は実装**：`bluesky.js` の `shortenUrl` を **link-worker 一次**（→da.gd→TinyURL→長URL）へ。**YT説明欄用途でURL長は無問題**＝計測できる自前Workerを最優先。開封は go5-short のKVで自動カウント開始。`SHORT.WORKER_URL/SHARED_SECRET`（localStorage上書き可）。
  - 全テスト **47 PASS / 0 FAIL**。要確認：link-worker の `SHARED_SECRET` 実値がフロント既定（drive流用のソフト鍵）と一致しているか（不一致なら da.gd へ無害フォールバック＝計測されないだけ）。
  - **①の見える化＝実装済（GAS）**：`refreshClicks` を **link-worker版に作り直し**（同名で再利用）。`短縮URL`列が `go5-short/<code>` の行は `<code>` を抜いて `/api/stats?code=&secret=` を叩き、開封数を `Bitlyクリック`列（＝意味を「開封数」に変更・**列名はテンプレ互換のため不変**）へ毎時反映。直近200行・sleep100ms＝クォータ安全。secretは `prop_('SHORT_SHARED_SECRET')`（既定＝フロントと同じソフト鍵）。`setupTrigger` に `refreshClicks` 毎時を再登録。**スキーマ変更なし**。
- 2026-06-25（同session・Chami「投稿再開は全部片付いてから・順番は任せる」）：**データ層を完成し、GAS変更を“再デプロイ1回”に集約**。
  - これで GAS 側の Phase A 変更が全部入り：①upsert（重複行なし）②testMode ③Bitly全廃＋da.gdフォールバック ④link-worker開封数の取り込み（refreshClicks刷新）。**Chami の手作業は「GAS再デプロイ1回＋setupTrigger実行1回」だけ**。
  - **正確な順番（合意）**：(1)データ層完成〔済〕→(2)Chamiが**GAS再デプロイ1回**＋実機で1本テスト確認→(3)検証済み土台の上で **`wizard.js`（一本道UI）**→(4)投稿再開。wizardは検証後に着手（未検証の土台に被せない）。
  - 次＝(2)の再デプロイ待ち。完了後 **`wizard.js`** へ。
- 2026-06-25（同session・実投稿で発覚した取り違えバグを修正）：**自動投稿が🦋投稿タブの「作品URL」欄(`bsky_work_url`・localStorage保存)を使うため、欄が前日のままだと別作品を案内してしまう** footgun（main にも元から存在）。
  - 修正：自動投稿の確認モーダル(`confirmEditable`)に **「📕案内する作品URL」欄(`#pcWorkUrl`)** を追加。①現在値を明示 ②その場で差し替え→本文末尾アフィリンクを作り直し（**動画は作り直さない**）③前回投稿と同じURLなら⚠️警告／空なら⚠️警告 ④OKで `bsky_work_url` に保存＋`bsky_last_posted_work` 更新（記録・YT説明欄・プレビューの作品も揃う）。`index.html` にモーダル欄追加。
  - 全テスト 47 PASS / 0 FAIL。**注意：これは branch のみ。公開(main)未反映**（live=main は5コミット遅れ）。根治は wizard（作品URL→アフィ→動画→投稿を1本道で持ち回す）。

## 6. Phase A 記録コントラクト（フロント→GAS。配線/ウィザード実装の基準）
動画作成〜投稿で、**同一 `videoId` を upsert キー**に2回送る。GASは `op:'upsert'` を `post_id` で突き合わせ、変更フィールドのみ更新。
- **(2) 動画作成時**：`{ op:'upsert', videoId, channel, title, status:'未投稿', testMode }`
- **(5) Bluesky投稿成功時**：`{ op:'upsert', videoId, channel, post_url, post_uri, short_url, status:'公開済', testMode }`
- **(3) YouTube手動投稿後**（任意）：`{ op:'upsert', videoId, channel, youtube_id, youtube_short, status:'YT済' 等 }`
- `testMode:true` の時、GASは**書き込まない**（Bluesky実投稿はフロントで実施）。
- Content-Type 無指定POST（simple request／プリフライト回避）は現状踏襲。`SHARED_SECRET` 未送信のまま。
- アフィリンクは payload に**生のまま**（短縮しない）。
