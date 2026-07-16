---
project: go5-maker
version: "現状仕様書 v1.0"
repo_url: https://github.com/John-Mori/go5-maker-7b311d01
public_url: https://john-mori.github.io/go5-maker-7b311d01/
exec_env: "GitHub Pages（フロント静的）/ Cloudflare Workers x2 / Google Apps Script / Google Drive / Google Sheets"
code_version_at_survey: "?v=82（2026-06-29 調査）"
status_md_last_entry: "v=61（2026-06-28）"
surveyed_at: 2026-06-29
agent_read_order:
  - "指示書_go5-maker現状仕様書の作成.md（添付）"
  - "STATUS.md"
  - "CLAUDE.md"
  - "プロジェクト全体設計書_AI引き継ぎ用.md"
  - "app.js / idgen.js / wizard.js / integration.js"
  - "bluesky-core.js / bluesky.js / verify-core.js"
  - "drive-upload.js / drive-worker/src/index.js / link-worker/src/index.js"
  - "gas/コード.gs / gas/snapshot.gs"
  - "schedule/js/store.js / settings-io.js / affiliate-core.js"
---

# go5-maker 現状仕様書

> **新セッション向け引き継ぎ文書。この 1 枚で全体像・パイプライン・スキーマ・連携点・不変条件・既知課題を把握できることを目標とする。**
> すべての記述は実コードを根拠にしており、確認できない項目は **「未確認」** と明示する。
> 秘密の実値（APIキー・トークン・パスワード）は記載しない。キー名と置き場所のみ示す。

---

## §1 システム概要

go5-maker は、iPhone 等の**ブラウザだけ**で「写真＋テキスト → 5 秒・縦型（9:16）動画」を生成し、Bluesky へ自動投稿・Google Drive へ自動保存し、投稿記録を Google スプレッドシートへ蓄積・分析する完全クライアントサイド Web アプリ。主目的は **FANZA アフィリエイトのショート動画を量産・配信**すること。動画合成は Canvas＋MediaRecorder で**端末内完結**（動画データをサーバーへ送信しない）。外部通信は Bluesky XRPC・Cloudflare Workers・GAS Web App・YouTube Data API・短縮 URL API に限定される。（根拠: `プロジェクト全体設計書_AI引き継ぎ用.md` 行17-28, `CLAUDE.md §0`）

**設計思想3本柱**（根拠: `プロジェクト全体設計書_AI引き継ぎ用.md` 行57-60）:
1. クライアントサイド最優先（サーバーはブラウザから原理的に不可能なものだけ）
2. サーバーレスは薄く・非破壊・多層防御（Origin 制限＋共有シークレット＋KV レート制限）
3. 比率ベースの座標系を崩さない（プレビュー＝書き出しの一致が最優先）

**運用対象チャンネル**: `acc1 = 月詠み色恋劇場` / `acc2 = 宵桜艶帖～Yoizakura Tsuyacho～`。アカウント切替（`getCurrentAccount()`）で背景動画・Bluesky設定・レイアウト・記録先シートがすべて独立して切り替わる。（根拠: `app.js:517-537`, `gas/コード.gs:39`）

---

## §2 全体アーキテクチャ

```
[ブラウザ（iPhone / PC）— GitHub Pages 静的配信]
  └─ index.html（5タブ）
       │
       ├─ app.js ─── Canvas合成 ─→ 【video-created イベント】
       │                                  │
       ├─ bluesky.js ←─────────────────┘
       │   ├─ handleVideoCreated()
       │   │     └─ bluesky-core.js: blueskyPostRaw()
       │   │           └─ Bluesky XRPC (bsky.social)
       │   │               createSession / uploadBlob / createRecord
       │   ├─ shortenUrl()
       │   │     ├─ 一次: go5-short (link-worker) → KV クリック計測
       │   │     ├─ 二次: da.gd
       │   │     └─ 三次: TinyURL
       │   └─ recordToSheet() → GAS Web App (doPost)
       │                           └─ Google Sheets (記録_ch1 / 記録_ch2)
       │
       ├─ drive-upload.js ← video-created 購読
       │     └─ POST go5-drive-saver (drive-worker)
       │           └─ OAuth refresh_token → Google Drive
       │               (フォルダ作成＋動画/画像アップロード・非破壊)
       │
       ├─ wizard.js ── 5ステップオーバーレイUI（観察のみ・直接APIを呼ばない）
       ├─ scheduler.js ── 予約投稿タイマー（30秒 tick・端末起動中のみ）
       ├─ integration.js ── postMessage ↔ schedule/index.html (iframe)
       └─ schedule/index.html ── カレンダーUI (iframe埋め込み)
              └─ store.js: sch_state_v1 (localStorage)

[Google Apps Script — 別プロジェクト]
  └─ gas/コード.gs
       ├─ doPost()     ── upsert 記録 / testMode / reserve
       ├─ doGet()      ── history / delete / lookup (JSONP callback)
       ├─ refreshEngagement()  ── Bluesky公開API getPosts（毎時）
       ├─ refreshClicks()      ── go5-short /api/stats 開封数取込（毎時）
       └─ runReservations()    ── Bluesky 無人予約投稿（5分間隔）
  └─ gas/snapshot.gs ── YouTube Data API v3 再生数スナップショット
       └─ [✅ コード完成 / ⬜ 未デプロイ・未設定]

[Cloudflare Workers]
  ├─ go5-drive-saver (drive-worker) ── Drive 保存専用・非破壊
  └─ go5-short (link-worker)        ── URL 短縮＋KV クリック計測
```

---

## §3 ディレクトリ／ファイル構成

### フロント（GitHub Pages 静的配信）

| ファイル | 役割 |
|---|---|
| `index.html` | メインUI。5タブ（🎬動画作成/📅カレンダー/🦋投稿/🔗アフィリンク/🧪検証） |
| `app.js` | Canvas 合成・動画録画の中核。`make()` → `video-created` dispatch。`getCurrentAccount()` をグローバル公開 |
| `style.css` | スタイル（ダークUI・タブ・＋/−ボタン） |
| `idgen.js` | 安定動画ID発番（`makeVideoId`）・YouTube 11文字ID抽出（`youtubeId`）（純粋関数） |
| `affiliate-core.js` | FANZAアフィリンク生成（`buildAffiliateLink`）（純粋関数） |
| `affiliate.js` | アフィリンクタブ UI 配線 |
| `bluesky-core.js` | Bluesky 投稿コア（`blueskyPostRaw`・`detectFacets`・`blueskyVerify`） |
| `bluesky.js` | Bluesky UI・`handleVideoCreated`・GAS 記録送信・短縮URL生成 |
| `drive-upload.js` | `video-created` 購読→ drive-worker 経由で Drive 保存 |
| `wizard.js` | 一本道ウィザード（5ステップオーバーレイ） |
| `integration.js` | カレンダー iframe ↔ メイン橋渡し（postMessage＋イベントバス） |
| `scheduler.js` | クライアント側予約投稿タイマー（30秒 tick） |
| `verify.js` | 検証タブ UI（Phase4 ダッシュボード） |
| `verify-core.js` | 検証用純粋関数（`buildGetPostsUrl`・`parseEngagement`・`postedSlotsFromState`） |
| `yt-clicks.js` | YouTube再生数・URL の手動追加・モーダル管理タブ |
| `settings-io.js` | 設定エクスポート/インポート（localStorage 全キー対象） |
| `persist-fields.js` | フィールドの localStorage 永続化 |
| `theme-settings.js` | テーマ設定（カスタム CSS カラー） |
| `post.html` | 単独 Bluesky 投稿ページ（**残置**・現メインフローとは繋がっていない） |
| `assets/bg_main.mp4` | acc1 背景動画 |
| `assets/bg_account2.mp4` | acc2 背景動画 |

### カレンダーサブページ（iframe 埋め込み）

| ファイル | 役割 |
|---|---|
| `schedule/index.html` | カレンダー UI 本体（親から iframe で埋め込む） |
| `schedule/js/store.js` | スケジュール状態管理（`sch_state_v1` localStorage） |
| `schedule/js/app.js` | カレンダー UI ロジック |
| `schedule/js/generator.js` | スロット生成ロジック |
| `schedule/js/config.js` | カレンダー設定 |
| `schedule/js/daytype.js` | 曜日・祝日ロジック |
| `schedule/data/holidays.js` | 祝日データ |
| `schedule/data/schedule_master.js` | スケジュールマスター |
| `schedule/data/verification_plan.js` | 検証プランデータ |

### Google Apps Script（別デプロイ）

| ファイル | 役割 |
|---|---|
| `gas/コード.gs` | GAS メイン（doPost upsert・doGet JSONP・毎時 refresh・5分予約投稿） |
| `gas/snapshot.gs` | YouTube 再生数スナップショット（✅コード完成・⬜未デプロイ） |
| `gas/セットアップ手順.md` | GAS デプロイ手順 |
| `gas/snapshot-setup.md` | snapshot.gs セットアップ手順 |
| `gas/snapshot-STATUS.md` | snapshot.gs の現在ステータス |

### Cloudflare Workers

| ファイル | 役割 |
|---|---|
| `drive-worker/src/index.js` | go5-drive-saver 本体（Drive 保存専用・非破壊） |
| `drive-worker/wrangler.toml` | go5-drive-saver 設定（FOLDER_ID_ACC1/2 コミット済） |
| `link-worker/src/index.js` | go5-short 本体（URL 短縮・KV クリック計測） |
| `link-worker/wrangler.toml` | go5-short 設定 |
| `.github/workflows/deploy-drive-worker.yml` | drive-worker CI/CD（Wrangler 自動デプロイ） |
| `.github/workflows/deploy-link-worker.yml` | link-worker CI/CD |

### テスト

| ファイル | 内容 |
|---|---|
| `tests/test_affiliate.js` | `buildAffiliateLink` テスト |
| `tests/test_bluesky.js` | facet バイトオフセット検証 |
| `tests/test_idgen.js` | ID 発番・YouTube ID 抽出（10 ケース） |
| `tests/test_record_upsert.js` | GAS `upsertRowOf_` ミラーテスト |
| `tests/test_scheduler.js` | 予約投稿タイマーロジック |
| `tests/test_verify.js` | 検証ダッシュボード純粋関数（5 ケース） |

---

## §4 一本道パイプライン：現状のステップ

「**1 作品＝1 パイプライン**」が設計上の骨格。`wizard.js` はオブザーバとして各ステップをガイドし、既存エンジン（`bluesky.js`・`drive-upload.js`・GAS）は**直接呼ばない**（二重投稿防止）。

### 起動経路

| 経路 | 操作 | 根拠 |
|---|---|---|
| **主（ウィザードボタン）** | `#wizStartBtn`「🪄 今から1本」クリック → `startWizard()` | `wizard.js:59,157` |
| **従（カレンダー経由）** | カレンダー iframe から `slot-create` postMessage → `integration.js` が `#slotCtxMovie` バナー表示 → バナー下のウィザードボタンをタップ → `startWizard()`。wizard.js 自体は postMessage を受信しない | `integration.js:40-55`, `wizard.js:59` |

### ステップ詳細

| ステップ | 内容 | 担当 | 手動/自動 |
|---|---|---|---|
| **1** | 作品URL＆アカウント選択 → `buildAffiliateLink()` でアフィリンク生成・プレビュー → `W.workUrl`・`W.affLink` 確定 | `wizard.js:renderStep1`, `affiliate-core.js` | 手動入力 |
| **2** | 既存 UI で動画作成 → `video-created` 受信で自動進行 → `W.videoId`・`W.title` 確定 | `wizard.js:renderStep2`, `app.js:make()` | 手動（ボタン）→ 自動進行 |
| **2b** ✦ | Drive 保存（`video-created` を `drive-upload.js` が購読）: タイトル名フォルダ作成 → 動画・プレビューPNG・元写真・Bsky追加画像を保存 | `drive-upload.js` | 自動（非同期・ウィザード外） |
| **3** | Bluesky 投稿（既存 `bluesky.js` 自動投稿フローを観察）→ `bluesky-posted` 受信で `W.postUrl` 確定 → 短縮URL をポーリング取得 | `wizard.js:renderStep3`, `bluesky.js:handleVideoCreated` | 手動（確認ダイアログ承認）→ 自動 |
| **4 〔手動ゲート〕** | YouTube 説明文コピー → **手動でアップロード** → YouTube URL を貼付 → `recordToGas()` で GAS へ upsert | `wizard.js:renderStep4` | **完全手動**（YouTube 自動投稿不可） |
| **5** | 完了表示（作品URL・短縮URL・YouTube URL リンク）。「閉じる」で終了 | `wizard.js:renderStep5` | 自動（確認のみ） |

（根拠: `wizard.js:10-21`(W定義), `wizard.js:356-516`(各ステップ)）

### 持ち回す文脈オブジェクト `W` のフィールド

```js
W.account   // 'acc1' | 'acc2'
W.workUrl   // 作品 URL（FANZA 等）
W.affLink   // 生成アフィリンク
W.videoId   // 安定動画 ID（§5 参照）
W.title     // 動画タイトル
W.postUrl   // Bluesky 投稿URL
W.postUri   // Bluesky 投稿URI（at://... 形式）
W.shortUrl  // 短縮URL（YT 説明欄に貼る URL）
W.ytUrl     // YouTube URL（ユーザー手入力）
W.ytId      // YouTube 11文字 ID（IdGen.youtubeId() で抽出）
```

（根拠: `wizard.js:10-21`）

### ウィザードの二重投稿防止

`startWizard()` 冒頭で `#bskyEnable` の現在値を `_prevBskyEnable` に退避し、強制 `checked=true`。`closeWizard()` 時に元に戻す（`wizard.js:157-162,175-177`）。ウィザード自身は Bluesky API を直接呼ばず、`bluesky-posted` を観察するだけ。各ステップ遷移時に `removeListeners()` で旧リスナーを解除（`wizard.js:226,574-583`）。

### GAS 記録コントラクト（同一 videoId を upsert キーとして 2〜3 回送る）

| タイミング | payload（主要フィールド） |
|---|---|
| 動画作成時（未投稿行生成） | `{ op:'upsert', videoId, channel, title, status:'未投稿', testMode }` |
| Bluesky 投稿成功時 | `{ op:'upsert', videoId, channel, post_url, post_uri, short_url, status:'公開済', testMode }` |
| YouTube URL 記録（任意） | `{ op:'upsert', videoId, channel, youtube_id, youtube_short }` |

（根拠: `STATUS.md §6`, `bluesky.js:519-534`, `gas/コード.gs:115-132`）

### イベントバス（カスタムイベント）

| イベント名 | dispatch 元 | 主な購読者 | payload の主フィールド |
|---|---|---|---|
| `video-created` | `app.js:make()` | `bluesky.js`, `drive-upload.js`, `wizard.js`（ステップ2） | `title, blob, name, videoId, account, test` |
| `bluesky-posted` | `bluesky.js:notifyPosted()`, `scheduler.js` | `integration.js`（slot-writeback）, `bluesky.js`（GAS記録・短縮URL）, `wizard.js`（ステップ3） | `post_uri, post_url, affiliate, hashtags, posted_at, title, slotId?` |
| `account-changed` | `app.js:setAccount()` | `integration.js`（iframe へ recompute） | `{ id }` |

（根拠: `プロジェクト全体設計書_AI引き継ぎ用.md` 行127-137, `app.js:535`, `integration.js:40-83`）

### postMessage（親 ↔ schedule iframe）

| 方向 | type | 内容 |
|---|---|---|
| iframe → 親 | `slot-create` | カレンダーの「🎬この枠で動画を作る」→ `activeSlot` にバナー表示 |
| iframe → 親 | `slot-post` | カレンダーの「🦋この枠を投稿する」→ 投稿タブへ切替 |
| 親 → iframe | `recompute` | アカウント切替時に再計算を指示 |
| 親 → iframe | `slot-writeback` | 投稿成功時にスロット状態（公開済・URI・URL 等）を書き戻す |

（根拠: `integration.js:40-83`）

---

## §5 内部 video ID 仕様

### 発番規則

**形式**: `{acc}-{YYYYMMDD}-{HHMM}-{rand4}`

```
通常例: acc1-20260625-1432-k7af
テスト: test-acc1-20260625-1432-9zx0
```

- `acc` = `acc1` または `acc2`（それ以外は `acc1` に正規化）
- `YYYYMMDD-HHMM` = 録画完了時のローカル時刻
- `rand4` = base36（`[0-9a-z]` 36文字）4桁乱数（同一分内の衝突回避）
- テストモード時は先頭に `test-` を付加

（根拠: `idgen.js:35-39`, `STATUS.md §2.1`）

### 発番タイミング

`app.js:make()` 内で録画完了後・`video-created` dispatch 直前に発番（`app.js:390-393`）。Bluesky の `cid`/`post_uri` **に依存しない**（投稿前に確定する）。

### スルーライン（串刺し先）

| 利用箇所 | 用途 | 根拠 |
|---|---|---|
| `video-created` event `detail.videoId` | 全購読者への配布 | `app.js:394` |
| `bluesky.js` `currentVideoId` | 投稿記録 payload の upsert キー | `bluesky.js:42,885-888` |
| `wizard.js` `W.videoId` | 各ステップへの引き継ぎ | `wizard.js:10` |
| GAS シート `post_id` 列 | シート行の upsert キー | `gas/コード.gs:187,210` |
| **Google Drive フォルダ/ファイル名** | **使用しない**（タイトルのみ） | `drive-upload.js`, `STATUS.md` 2026-06-26 |

> ⚠️ Drive 保存のフォルダ名・ファイル名は動画タイトルのみ（videoId プレフィックスなし）。2026-06-26 の設計変更で ID プレフィックスを撤去。同名フォルダは Worker 側で `_2,_3...` 連番で回避。（根拠: `drive-upload.js:107-110`, `STATUS.md` 2026-06-26 エントリ）

### 補助関数（`idgen.js` エクスポート）

| 関数 | 用途 |
|---|---|
| `IdGen.makeVideoId(acc, date, opts)` | ID 発番。`opts.test=true` でテスト接頭辞、`opts.rng` で乱数注入 |
| `IdGen.isTestId(id)` | `test-` 判定 |
| `IdGen.accOfId(id)` | ID からアカウント抽出 |
| `IdGen.youtubeId(url)` | YouTube URL / ID → 11文字 ID |
| `IdGen.youtubeWatchUrl(id)` | 11文字 ID → 正規 watch URL |

（根拠: `idgen.js:35-76`）

---

## §6 データストア

### §6.1 Google Sheets

**スプレッドシート**: GAS スクリプトプロパティ `SHEET_ID` で指定（`gas/コード.gs:34-36`）

#### 記録シート（`記録_ch1` / `記録_ch2`）

40列固定（`HEADERS40`）。列名・順序（`gas/コード.gs:22-28`）:

```
 1: post_id             ← 安定動画ID（upsert キー）
 2: 投稿日時            ← 投稿時刻（Date 型）
 3: 曜日                ← 数式で自動計算（WEEKDAY/CHOOSE）
 4: day-type            ← 数式（平日/休前日/土日祝）
 5: 時間帯スロット      ← 数式（深夜/朝/昼/夕/夜）
 6: 特別期間(手動)
 7: ジャンル
 8: 題名(コメント)      ← 動画タイトル
 9: ハッシュタグ
10: サムネ/フック種別(A/B)
11: CTA・リンク提示方法
12: Blueskyラベル
13: 作品cid             ← URL から正規表現抽出（extractCid_）
14: YouTube動画URL      ← youtubeId（11文字）または短縮URL
15: Bluesky投稿URL
16: 短縮URL             ← go5-short / da.gd（実際に共有する URL）
17: インプレッション     （手入力・未確認: 自動連携なし）
18: インプCTR%
19: 視聴回数
20: 平均視聴維持率%
21: いいね              ← refreshEngagement() で毎時更新
22: リポスト            ← refreshEngagement() で毎時更新
23: 返信               ← refreshEngagement() で毎時更新
24: フォロー増
25: Bitlyクリック       ← 現在は go5-short 開封数（列名はテンプレ互換のため変更不可）
26: FANZA発生成約       ← 手入力
27: FANZA確定成約       ← 手入力
28: 発生報酬¥
29: 確定報酬¥
30: 承認率%             ← 数式（AA/Z）
31: リンククリック率%   ← 数式（Y/S）
32: CVR発生%            ← 数式（Z/Y）
33: CVR確定%            ← 数式（AA/Y）
34: EPC発生¥            ← 数式（AB/Y）
35: EPC確定¥            ← 数式（AC/Y）
36: RPM(¥/1000再生)    ← 数式（AC/S*1000）
37: Bitly_ID            ← 現在未使用（温存・将来 link-worker クリックへ転用可）
38: post_uri            ← Bluesky at:// URI
39: クリック更新日時
40: 反応更新日時
```

**upsert キー**: `post_id` 列（安定動画ID）
**upsert ロジック**: `upsertRowOf_(postIdCol, videoId)` が `post_id` 列を線形走査し一致行番号を返す純粋関数（`gas/コード.gs:163-167`）。一致なし → 空の投稿日時行を再利用、なければ末尾追加（後方互換）。
**自動計算数式**: `setComputed_()` が行番号に合わせた WEEKDAY/IF/IFERROR 式を設定（`gas/コード.gs:146-158`）。
**`putIf` によるクランプ防止**: upsert 更新時は既存値を空で上書きしない（`gas/コード.gs:208`）。カウンタ（いいね等）は新規行のみ 0 初期化（`gas/コード.gs:219`）。

#### 予約シート（`予約`）

11列固定（`RES_HEADERS`）（`gas/コード.gs:324`）:

```
1: 予約ID  2: 予約日時  3: 本文  4: 画像fileId  5: slot_id
6: ステータス  7: 結果URI  8: 結果URL  9: 投稿日時  10: エラー  11: channel
```

#### 再生数_スナップショット（`gas/snapshot.gs` — ⬜未デプロイ）

9列（`SNAP_HEADERS_`）（`gas/snapshot.gs:36-39`）:

```
internal_id, youtube_id, channel, published_at,
snapshot_at, elapsed_min, elapsed_bucket, view_count, view_delta
```

#### 再生数_管理（`gas/snapshot.gs` — ⬜未デプロイ）

8列（`MGMT_HEADERS_`）（`gas/snapshot.gs:40-43`）:

```
internal_id, youtube_id, channel, published_at,
status, first_seen, last_snapshot_at, last_view_count
```

---

### §6.2 Google Drive

**フォルダ構成**（drive-worker が作成）:

```
マイドライブ/
  └─ AFI5秒動画/                   ← env.FOLDER_ID_ACC1 / FOLDER_ID_ACC2（固定）
       └─ 月詠み色恋劇場/ or 宵桜艶帖/   ← チャンネル名フォルダ（未確認: チャンネル名をフォルダ名にするか要確認）
            └─ {タイトル}/          ← 動画ごとの子フォルダ（同名は _2,_3... で回避）
                 ├─ {タイトル}.mp4          ← 録画動画
                 ├─ {タイトル}_プレビュー.png ← 合成済み Canvas PNG（1080×1920）
                 ├─ {タイトル}.jpg 等        ← 元写真（`#photo` の選択ファイル）
                 └─ {タイトル}_Bsky.{ext}   ← 🦋タブの追加画像（選択時のみ）
```

（根拠: `drive-upload.js:128-130`, `drive-worker/src/index.js:66-87`）

**非破壊の確認**: `drive-worker/src/index.js` 全体（267行）において Google Drive API への DELETE・PATCH（上書き/改名/移動）・ゴミ箱送り呼び出しが **0件** であることを確認済み。使用する HTTP メソッドは `GET`（存在確認）・`POST`（フォルダ新規作成・resumable セッション開始）・`PUT`（ファイルデータ転送）のみ。（根拠: `drive-worker/src/index.js:140,150,159,170,191,201`）

**Drive 保存トリガー**: `drive-upload.js` が `video-created` を購読し `window.getCurrentAccount()` でチャンネルを確認。`acc1`/`acc2` 以外は `channel_unresolved` エラーで保存しない（取り違え防止）。（根拠: `drive-upload.js:101-114`）

**予約投稿の一時画像（GAS）**: `gas/コード.gs` の `getDriveFolder_()` が `go5-reservations` フォルダへ一時保存し、投稿後 `setTrashed(true)` でゴミ箱送り（`gas/コード.gs:333-337,383`）。GAS 側 Drive 操作は drive-worker の「非破壊」設計とは独立。

---

## §7 Cloudflare Worker

### go5-drive-saver（drive-worker）

| 項目 | 内容 | 根拠 |
|---|---|---|
| デプロイ名 | `go5-drive-saver` | `drive-worker/wrangler.toml:1` |
| エンドポイント | `POST /`（単一。それ以外は 405 / OPTIONS はプリフライト応答） | `drive-worker/src/index.js:21-29` |
| リクエスト形式 | `multipart/form-data`（`channel`, `title`, `video`, `image` x 複数） | `drive-worker/src/index.js:44-65` |
| 認証 | `X-Shared-Secret` ヘッダ と `env.SHARED_SECRET`（Worker Secret）の完全一致 | `drive-worker/src/index.js:32-35` |
| CORS | `env.ALLOWED_ORIGIN` の 1 Origin のみ。不一致は 403 | `drive-worker/src/index.js:249-257,28` |
| レート制限 | KV バインディング `env.RL` が存在すれば日次カウンタ制限。**現在 KV 無効**（wrangler.toml コメントアウト）→ 制限なしで通過 | `drive-worker/wrangler.toml` |
| OAuth | `GOOGLE_REFRESH_TOKEN`・`GOOGLE_CLIENT_ID`・`GOOGLE_CLIENT_SECRET`（Worker Secrets）でリクエスト毎に access_token 取得 | `drive-worker/src/index.js:116-135` |
| 同名回避 | フォルダ: `name`, `name_2`, `name_3`…（衝突ループ）。ファイル: `stem_2.ext`… | `drive-worker/src/index.js:167-168,183-185` |
| 非破壊 | create/read のみ（DELETE・PATCH・上書きなし、確認済） | `drive-worker/src/index.js` 全体 |
| CI/CD | `.github/workflows/deploy-drive-worker.yml`（Wrangler 自動デプロイ） | |

### go5-short（link-worker）

| 項目 | 内容 | 根拠 |
|---|---|---|
| デプロイ名 | `go5-short` | `link-worker/wrangler.toml:1` |
| エンドポイント | `POST /api/shorten`・`GET /api/stats`・`GET /`（ヘルス）・`GET /:code`（リダイレクト） | `link-worker/src/index.js:40-63` |
| コード生成 | SHA-256 ハッシュ → BASE62（[0-9a-zA-Z]）先頭 7 文字（衝突時 +1 ずつ最大 12 文字） | `link-worker/src/index.js:136-142` |
| KV スキーマ | `u:<code>` = 宛先 URL（不変）/ `c:<code>` = クリック数 / `rl:YYYY-MM-DD` = 日次レート制限（48h TTL） | `link-worker/src/index.js` |
| `u:<code>` 不変の理由 | 発行時に既存エントリを上書きするコードパスが存在しない。別 URL が占有していればコードを伸ばして回避 | `link-worker/src/index.js:100-101` |
| 認証（shorten） | `X-Shared-Secret` ヘッダ | `link-worker/src/index.js:71-73` |
| 認証（stats） | クエリパラメータ `secret`（GET のためクエリ渡し） | `link-worker/src/index.js:125-126` |
| CORS（stats） | `Access-Control-Allow-Origin: *`（クリック数は非機密・ソフト鍵前提） | `link-worker/src/index.js:124` |
| 宛先制限 | `env.ALLOWED_HOSTS`（既定: `bsky.app,bsky.social,youtube.com,youtu.be`）。FANZA は含まず → アフィリンク短縮不可 | `link-worker/wrangler.toml:11` |
| CI/CD | `.github/workflows/deploy-link-worker.yml` | |

**現在のフロント接続状態**: `bluesky.js:shortenUrl()` は link-worker を一次（go5-short）・da.gd を二次・TinyURL を三次として使う設計（`bluesky.js:595-600`）。link-worker は**デプロイ済みで待機中**。`SHORT.WORKER_URL` がデフォルト値（`go5-short.trustsignalbot.workers.dev`）のまま正しく参照されれば一次として機能する。

---

## §8 Google Apps Script

**デプロイ先**: フロント localStorage の `bsky_gas_url` に保存された GAS Web App URL へ `Content-Type` 無指定 POST（simple request・プリフライト回避）。`SHARED_SECRET` は現在**未送信**（GAS 側も未設定。不変条件 4）。

### `gas/コード.gs` — 主要関数一覧

| 関数 | 用途 | 呼ばれ方 |
|---|---|---|
| `doPost(e)` | 投稿記録（upsert）・testMode 分岐・無人予約（type:'reserve'） | HTTP POST |
| `doGet(e)` | 履歴取得（JSONP callback）・削除・短縮URL lookup | HTTP GET |
| `writeRecord_(channel, f)` | 1 投稿を記録（upsert または空行再利用/末尾追加） | `doPost`, `runReservations` |
| `upsertRowOf_(postIdCol, videoId)` | `post_id` 列を走査し upsert 先行番号を返す純粋関数 | `writeRecord_` |
| `setComputed_(sh, map, r)` | 数式列（曜日・day-type・時間帯・計算KPI）を設定 | `writeRecord_` |
| `refreshEngagement()` | Bluesky 公開 API getPosts で いいね/リポスト/返信を毎時更新 | 毎時トリガー |
| `refreshClicks()` | go5-short `/api/stats` で開封数を毎時更新（`Bitlyクリック` 列へ） | 毎時トリガー |
| `handleReserve_(body)` | 無人予約を「予約」シートへ積む | `doPost` type:'reserve' |
| `runReservations()` | 予約シートの pending 行を Bluesky へ投稿 | 5分トリガー |
| `bskyPost_(text, imageBlob)` | GAS 側 Bluesky 投稿（`BSKY_HANDLE`/`BSKY_APP_PW` 使用） | `runReservations` |
| `detectFacets_(text)` | URL・ハッシュタグ facet（UTF-8 バイトオフセット）生成 | `bskyPost_` |
| `daGdShorten_(longUrl)` | da.gd で短縮（フロント生成 shortUrl がない経路のフォールバック） | `writeRecord_` |
| `workerClicks_(code)` | go5-short `/api/stats` を呼びクリック数取得 | `refreshClicks` |
| `extractCid_(url)` | 作品URL / アフィリンクから `cid=` 値を抽出 | `writeRecord_` |
| `historyItems_(channel, limit)` | 投稿履歴を新しい順に返す（doGet action=history） | `doGet` |
| `deleteRecord_(channel, postUri, short)` | 行の内容をクリア（行は詰めない） | `doGet` action=delete |
| `setupTrigger()` | `refreshClicks`・`refreshEngagement` の毎時トリガーを登録（初回 1 回） | 手動実行 |
| `setupReservationTrigger()` | `runReservations` の 5 分トリガーを登録（初回 1 回） | 手動実行 |

（根拠: `gas/コード.gs` 全体）

**SHARED_SECRET の扱い**: `doPost` 冒頭で `prop_('SHARED_SECRET')` を取得し、**設定されていれば** `body.secret` と照合（`gas/コード.gs:118-119`）。現在は不変条件 4 により**設定しない**。設定すると既存フロントが secret を送らないため全リクエストが弾かれる。

**testMode**: `body.testMode === true` の場合、シートへの書き込みを一切せず `{ok:true, testMode:true}` を返す（`gas/コード.gs:122`）。Bluesky 実投稿はフロント側で実施済み。

### `gas/snapshot.gs` — YouTube 再生数スナップショット（✅コード完成・⬜未デプロイ）

`コード.gs` と**同一 GAS プロジェクト**に追加するスクリプト。`openSS_`・`prop_`・`headerMap_`・`CH_SHEETS` を共用（`gas/snapshot.gs` 参照箇所: 行151,200,209,248 等）。

**経過時間ティア定義**（`gas/snapshot.gs:46-51`）:

| elapsed_min（上限） | interval（分） | label |
|---|---|---|
| ≤ 360 | 30 | `0-6h` |
| ≤ 1440 | 120 | `6-24h` |
| ≤ 10080 | 360 | `1-7d` |
| ≤ 40320 | 1440 | `7-28d` |
| > 40320 | — | status='done'（記録終了）|

**処理フロー**: `snapshotViews()` が 30 分トリガーで起動 → `seedNewVideos_()` で記録シートの YouTube URL から新動画を管理シートへ登録 → ティア判定で今回スナップ対象を抽出 → YouTube Data API v3 `videos.list?part=snippet,statistics`（最大 50 件バッチ）で再生数取得 → スナップシートへ追記・管理シート更新（`gas/snapshot.gs:196-314`）。

**未デプロイ（デプロイ前に必要な作業）**: GAS へスクリプトをペースト → `YOUTUBE_API_KEY` を Script Property に設定 → `setupSnapshotTrigger()` を 1 回手動実行。（根拠: `gas/snapshot-STATUS.md`）

---

## §9 外部API連携

### Bluesky AT Protocol

**サービスURL**: `https://bsky.social`（`bluesky-core.js:DEFAULT_SERVICE`）

**フロントからの投稿フロー** (`bluesky-core.js:63-135`):
1. `createSession` → `POST /xrpc/com.atproto.server.createSession`（identifier + アプリパスワード）→ `{ accessJwt, did, handle }`
2. `uploadBlob` → `POST /xrpc/com.atproto.repo.uploadBlob`（`Authorization: Bearer <accessJwt>`・バイナリ）→ `{ blob: {...} }`
3. `createRecord` → `POST /xrpc/com.atproto.repo.createRecord`（`{ repo: did, collection: 'app.bsky.feed.post', record }`）→ `{ uri, cid }`

**facet 実装（UTF-8 バイトオフセット）**: `byteLen(s)` が `TextEncoder.encode(s).length`（フォールバック: `unescape(encodeURIComponent(s)).length`）でバイト長を計算し、URL・ハッシュタグの `byteStart`/`byteEnd` を算出（`bluesky-core.js:18-23,170-202`）。日本語等マルチバイト文字でもズレなし。

**複数画像（最大 4 枚）**: `blueskyPostRaw` が `imageBlobs[]`（配列）と `imageBlob`（単数・後方互換）を concat し、並列 `uploadBlob` → `createPost` に `imageRefs[]` として渡す（`bluesky-core.js:108-113,214-218`）。

**`blueskyPostRaw` の引数と返り値**:
- 引数（オブジェクト `o`）: `identifier`, `appPassword`, `text`, `imageBlobs[]`, `imageBlob`（互換）, `alt`, `service`
- 返り値: `{ uri, cid, handle, rkey, postUrl }`（`postUrl` = `https://bsky.app/profile/<handle>/post/<rkey>`）

（`bluesky-core.js:206-225`）

**GAS 側投稿** (`bskyPost_`): スクリプトプロパティ `BSKY_HANDLE`/`BSKY_APP_PW` を使用。無人予約投稿専用。フロントの `bluesky-core.js` と同等のフロー（`gas/コード.gs:393-420`）。

**Bluesky 公開 API（未認証 CORS 可）**: `refreshEngagement()` と `verify-core.js` が `public.api.bsky.app/xrpc/app.bsky.feed.getPosts` を 25 件バッチで呼ぶ（`gas/コード.gs:277-304`, `verify-core.js:12-16`）。

**内部 ID ↔ Bluesky 投稿の紐付け**: 投稿成功後の `post_uri`・`post_url` を `recordToSheet()` で GAS へ送り、`post_id`（= videoId）行へ upsert で書き込む（`bluesky.js:519-534`, `gas/コード.gs:215-217`）。

### YouTube Data API v3

- **用途A**: `gas/snapshot.gs` による再生数スナップショット（⬜**未デプロイ**）。`videos.list?part=snippet,statistics`、最大 50 件バッチ、1 呼び出し = 1 ユニット（`gas/snapshot.gs:93-121`）。
- **用途B**: フロント `yt-clicks.js` が端末の localStorage に保存した `yt_api_key` を使い各行の YouTube 動画の再生数・投稿日時を直接取得する（**未確認**: `yt-clicks.js` の詳細実装は本調査で未確認）。

### FANZA アフィリエイト

- **API 呼び出しなし**（商品情報を API で取得しない）
- `buildAffiliateLink(rawUrl, afId)` で入力 URL から `cid=` を正規表現（`/cid=([^/?&\s]+)/`）で抽出し、アフィリンク URL を生成するだけ（`affiliate-core.js:16`）
- **生成 URL 形式**: `https://al.fanza.co.jp/?lurl={encodeURIComponent(clean)}&af_id={af}&ch=toolbar&ch_id=link`（`affiliate-core.js:19-24`）
- **返り値**: `{ ok:true, cid, link }` または `{ ok:false, error:'empty'|'no_cid'|'bad_url' }`
- アフィリンクは**生のまま投稿・記録**（短縮なし。af_id 計測を守るため）

### 短縮 URL

| サービス | 優先度 | 用途 | クリック計測 |
|---|---|---|---|
| go5-short（link-worker） | 一次 | Bluesky 投稿・YT 説明欄の短縮 URL | KV で開封数カウント |
| da.gd | 二次（フォールバック） | link-worker 失敗時 | なし |
| TinyURL | 三次（フォールバック） | da.gd 失敗時 | なし |

（根拠: `bluesky.js:595-600`）

**GAS → go5-short `/api/stats`**: `refreshClicks()` が `短縮URL` 列の `go5-short` URL からコードを抽出し、毎時クリック数（開封数）を `Bitlyクリック` 列へ反映（`gas/コード.gs:257-273`）。列名はテンプレ互換のため変更不可。

---

## §10 テストモードの挙動

テストモードは「**Bluesky に実際に投稿するが、スプレッドシートには記録しない**」設計。テスト投稿で記録を汚さない。

| 処理 | テストモード時の挙動 | 根拠 |
|---|---|---|
| videoId 発番 | 先頭に `test-` を付加（例: `test-acc1-20260625-1432-k7af`） | `app.js:390-393`, `idgen.js:39` |
| `video-created` detail | `test: true` フラグを含む | `app.js:394` |
| Drive 保存 | タイトルを `"test_" + rawTitle` に変更してフォルダ/ファイル名に前置 | `drive-upload.js:109` |
| Bluesky 投稿 | **実際に投稿する**（`blueskyPostRaw` をそのまま使用） | `bluesky.js:handleVideoCreated` |
| GAS 記録 | `testMode:true` を payload に付けて送信 → GAS は**シート未記録で `ok` を返す** | `bluesky.js:522-525`, `gas/コード.gs:122` |
| `testMode` 判定条件 | `IdGen.isTestId(videoId)`（`test-` 始まり）が真のとき | `bluesky.js:522-525` |

**UI**: 動画作成カードに「🧪 テストモード」チェックボックス（v=56 追加）。

---

## §11 不変条件（現行）

以下はコードと設計書で確認できる「壊してはいけない約束」。改修時に 1 つでも違反したら手を止めて確認。

| # | 不変条件 | 根拠 |
|---|---|---|
| 1 | **比率座標系**（W=1080, H=1920）。位置・サイズは `H×係数` / `W×係数`。px/vh/vw 直接使用禁止。旧来 px 値は `U(v)=v*H/1280` で換算。プレビュー＝書き出しの一致が最優先 | `CLAUDE.md §3`, `app.js CONTROLS/OFF` |
| 2 | **drive-worker は非破壊**（create/read のみ）。DELETE・PATCH・上書き・移動・改名 API を追加しない | `drive-worker/src/index.js`（267行全確認済）|
| 3 | **link-worker の `u:<code>` は不変**。既存の短縮 URL が後から別宛先に変わってはならない | `link-worker/src/index.js:100-101` |
| 4 | **GAS の `SHARED_SECRET` は未設定のまま**。フロントは `secret` を送らない。設定すると全リクエストが弾かれる | `gas/コード.gs:118-119`, `STATUS.md §★` |
| 5 | **秘密の本体**（OAuth refresh_token・Bluesky アプリパスワード等）は各サービスの Secrets/Properties のみ。console・repo・レスポンスに出力しない | `CLAUDE.md §6`, 各設計書 |
| 6 | **変更後は `index.html` の `?v=N` を上げる** | `CLAUDE.md §3` |
| 7 | **アフィリンクのテンプレート変更は `affiliate-core.js` の `buildAffiliateLink()` 内のみ** | `CLAUDE.md §6` |
| 8 | **アフィリンクは生のまま投稿・記録**（短縮しない。`af_id` 計測を壊さないため）。link-worker の ALLOWED_HOSTS にも FANZA ドメインは含まない | `STATUS.md §2.8`, `link-worker/wrangler.toml:11` |

---

## §12 環境変数・設定一覧

### Cloudflare Worker Secrets（`wrangler secret put` で登録。コードに書かない）

**go5-drive-saver（drive-worker）**:

| キー名 | 用途 |
|---|---|
| `GOOGLE_CLIENT_ID` | OAuth2 クライアント ID |
| `GOOGLE_CLIENT_SECRET` | OAuth2 クライアントシークレット |
| `GOOGLE_REFRESH_TOKEN` | OAuth2 リフレッシュトークン（個人 Gmail）|
| `SHARED_SECRET` | フロントとの共有シークレット（ソフト鍵）|

**go5-short（link-worker）**:

| キー名 | 用途 |
|---|---|
| `SHARED_SECRET` | 短縮発行・stats 取得の認証（ソフト鍵）|

（根拠: `drive-worker/wrangler.toml` コメント, `link-worker/wrangler.toml:21-22`）

### Worker vars（`wrangler.toml [vars]` — リポジトリにコミット済）

| Worker | キー名 | 用途 |
|---|---|---|
| drive-worker | `ALLOWED_ORIGIN` | CORS 許可 Origin |
| drive-worker | `FOLDER_ID_ACC1` | acc1 の保存先親フォルダ ID |
| drive-worker | `FOLDER_ID_ACC2` | acc2 の保存先親フォルダ ID |
| drive-worker | `DAILY_LIMIT` | 日次アップロード上限（KV 無効のため現在機能しない）|
| link-worker | `ALLOWED_ORIGIN` | CORS 許可 Origin |
| link-worker | `ALLOWED_HOSTS` | 短縮先ホスト許可リスト |
| link-worker | `DAILY_LIMIT` | 日次発行上限 |

### GAS スクリプトプロパティ（Script Properties）

| キー名 | 用途 |
|---|---|
| `SHEET_ID` | 記録先スプレッドシート ID（必須）|
| `BSKY_HANDLE` | 無人予約投稿用 Bluesky ハンドル |
| `BSKY_APP_PW` | 無人予約投稿用 Bluesky アプリパスワード |
| `SHORT_SHARED_SECRET` | go5-short `/api/stats` 認証（省略時はソフト鍵の既定値を使用）|
| `YOUTUBE_API_KEY` | YouTube Data API キー（snapshot.gs 専用・**現在未設定**）|

（根拠: `gas/コード.gs:31,240,394`, `gas/snapshot.gs:24`）

> ⚠️ `SHARED_SECRET` は**設定しないこと**（不変条件 4 参照）。

### フロント localStorage キー

**アカウント設定（共通）**:

| キー名 | 用途 |
|---|---|
| `current_account` | 現在のアカウント（`acc1` / `acc2`）|
| `fanza_af_id` | FANZA アフィリエイト ID |

**Bluesky 設定（アカウント別: `*__acc1` / `*__acc2`）**:

| キー名パターン | 用途 |
|---|---|
| `bsky_enable__*` | 自動投稿フラグ |
| `bsky_text__*` | 投稿本文テンプレート |
| `bsky_work_url__*` | 作品 URL |
| `bsky_handle__*` | Bluesky ハンドル |
| `bsky_app_pw__*` | Bluesky アプリパスワード（機微）|
| `bsky_unattended__*` | 無人投稿（GAS 経由）トグル |

**Bluesky 設定（共通）**:

| キー名 | 用途 |
|---|---|
| `bsky_gas_url` | GAS Web App URL |
| `bsky_gas_secret` | GAS 共有シークレット（現在 GAS 側が未チェックのため実質未使用）|
| `bsky_avatar_<handle>` | アバター画像キャッシュ |
| `bsky_dn_<handle>` | 表示名キャッシュ |
| `short_hist__<acc>` | 短縮 URL 履歴（アカウント別・最大 200 件）|

**Worker URL（端末ごとに localStorage で上書き可）**:

| キー名 | 用途 |
|---|---|
| `short_worker_url` | go5-short エンドポイント上書き |
| `short_shared_secret` | go5-short シークレット上書き |
| `drive_worker_url` | drive-worker エンドポイント上書き |
| `drive_shared_secret` | drive-worker シークレット上書き |

**レイアウト調整（アカウント別: `*__acc1` / `*__acc2`）** ※ STATUS.md タスク 8d（v=58）で acc 別分離実装済:

| キー名パターン | 用途 |
|---|---|
| `preview_offset_y__*` | 全体縦オフセット |
| `preview_text_author__*` | 作者名段の文字オフセット |
| `preview_text_detail__*` | 誘導文段の文字オフセット |
| `preview_text_title__*` | 大タイトル段の文字オフセット |
| `preview_band_author__*` | 作者名段の帯オフセット |
| `preview_band_detail__*` | 誘導文段の帯オフセット |
| `preview_band_title__*` | 大タイトル段の帯オフセット |
| `preview_band_pad__*` | 全段共通の帯パディング |
| `preview_row_gap__*` | 段間隔 |
| 各 `*_default__*` | 「既定値に保存」用 |

**テキスト編集補助（アカウント別）**:

| キー名パターン | 用途 |
|---|---|
| `yt_desc__*` | YouTube 説明文テンプレート |
| `yt_tags__*` | YouTube タグ |
| `yt_desc_quick__*` | Qセーブ（YouTube 説明文）|
| `bsky_text_quick__*` | Qセーブ（Bluesky 本文）|
| `yt_desc_undo__*` | 元に戻す（YouTube 説明文）|
| `bsky_text_undo__*` | 元に戻す（Bluesky 本文）|

**カレンダー / 検証**:

| キー名 | 用途 |
|---|---|
| `sch_state_v1` | スケジュール状態（`{overrides, slotData}`・プラン共有＋実行層チャンネル別）|
| `verify_fanza` | FANZA 成約手入力値（検証タブ用）|
| `sb_session_v1` | Supabase セッション（アダプタ未検証・現在不使用）|

**その他**:

| キー名 | 用途 |
|---|---|
| `yt_api_key` | YouTube Data API キー（`yt-clicks.js` 用・端末内のみ・リポジトリに置かない）|
| `verify_yt__<acc>` | 行ごとの YouTube URL 入力（検証タブ）|
| `verify_manual__<acc>` | 手動追加した投稿記録（検証タブ）|

（根拠: `プロジェクト全体設計書_AI引き継ぎ用.md` 行140-145, `CLAUDE.md §3`, `settings-io.js`, `schedule/js/store.js:14`, `yt-clicks.js:26`）

---

## §13 既知の課題・未実装・TODO

| # | 種別 | 内容 | 根拠 |
|---|---|---|---|
| 1 | **未デプロイ** | `gas/snapshot.gs`（YouTube 再生数スナップショット）はコード完成済みだが、GAS へ未ペースト・`YOUTUBE_API_KEY` 未設定・トリガー未登録 | `gas/snapshot-STATUS.md`（全 ⬜）|
| 2 | **保留** | YouTube Data API によるフロント側での再生数自動取得（改修書タスク 2）は「Data APIキー未発行」で保留中 | `STATUS.md §1` |
| 3 | **インフラ** | drive-worker の KV レート制限が無効（`wrangler.toml` でコメントアウト）。現在の多層防御は Origin 制限＋SHARED_SECRET のみ | `drive-worker/wrangler.toml` |
| 4 | **残置** | `post.html`（単独 Bluesky 投稿ページ）は現メインフロー（`integration.js`・`wizard.js`）の外にあり、カレンダー slot-writeback 等が繋がっていない | `post.html` 存在確認 |
| 5 | **スタブ** | `schedule/js/store.js` の Supabase アダプタ（行38-155）は実装あり・コメントに「本実装はライブDB未検証」と明記 | `schedule/js/store.js:37` |
| 6 | **ドキュメント乖離** | `STATUS.md` のログが v=61（2026-06-28）で止まっており、現在の v=82 までの変更記録がない（v=62〜82 の変更履歴が欠落）| `STATUS.md` vs `index.html` |
| 7 | **ドキュメント乖離** | `CLAUDE.md §3` の `bsky_*` localStorage キー表記がサフィックスなし（旧仕様）。現在の実態は `__acc1`/`__acc2` サフィックスあり（8d 実装済み v=58） | `CLAUDE.md:96` vs `プロジェクト全体設計書_AI引き継ぎ用.md:142` |
| 8 | **ドキュメント乖離** | `CLAUDE.md §3` の「現在 v=12」はキャッシュバージョン番号の古い記述。現在 v=82 | `CLAUDE.md:90` |
| 9 | **設計書不在** | 指示書が参照する `設計書の設計書.md` と `サブエージェントモデル.md` がリポジトリにも調査時のアップロードにも見つからなかった | 本調査時の確認 |
| 10 | **ソフト鍵の直書き** | `drive-upload.js:20` に SHARED_SECRET の既定値がソースコードに直書きされている。設計上「ソフト鍵（公開可）」と定義されており、実防御は Worker 側の Origin 制限。端末ごとに localStorage で上書き可 | `drive-upload.js:17-20`, `CLAUDE.md §18` |
| 11 | **未確認** | `yt-clicks.js` のフロント側 YouTube API 呼び出し実装詳細（利用 API・エラーハンドリング・表示ロジック）は本調査で未確認 | `yt-clicks.js` 未精読 |

---

## §14 用語集

| 用語 | 意味 |
|---|---|
| acc1 | 月詠み色恋劇場（チャンネル 1）|
| acc2 | 宵桜艶帖～Yoizakura Tsuyacho～（チャンネル 2）|
| 安定動画 ID | `makeVideoId()` が発番する `{acc}-{YYYYMMDD}-{HHMM}-{rand4}` 形式の ID。1 パイプライン 1 本 |
| go5-drive-saver | drive-worker のデプロイ名。Drive 保存専用 Cloudflare Worker |
| go5-short | link-worker のデプロイ名。URL 短縮・クリック計測 Cloudflare Worker |
| ソフト鍵 | フロントコードに直書きされているが「公開可」とされている共有シークレット。実防御は Worker 側 Origin 制限 |
| video-created | 動画作成完了を通知する CustomEvent（`app.js:make()` が dispatch）|
| bluesky-posted | Bluesky 投稿成功を通知する CustomEvent（`bluesky.js`/`scheduler.js` が dispatch）|
| account-changed | アカウント切替を通知する CustomEvent（`app.js:setAccount()` が dispatch）|
| facet | Bluesky AT Protocol のリッチテキスト装飾（URL・ハッシュタグ）。UTF-8 バイトオフセットで範囲指定 |
| upsert | 同一 videoId の行があれば更新、なければ新規作成。GAS の `writeRecord_()` が実装 |
| cid | FANZA 作品コンテンツID（`cid=` クエリパラメータから抽出）|
| da.gd | 無料 URL 短縮サービス（トークン不要・CORS 対応・クリック計測なし）|
| 一本道ウィザード | `wizard.js` が提供する 5 ステップのオーバーレイ UI。既存エンジンを観察するだけで直接呼ばない |
| 手動ゲート | YouTube アップロードは自動化不可（YouTube 公式管理画面で手動のまま）。ウィザードのステップ 4 で停止して URL 入力を待つ |
| sch_state_v1 | カレンダーの共有 localStorage キー（`{overrides, slotData}`）|
| exec.acc1 / exec.acc2 | `slotData` 内の実行層フィールド（投稿ステータス・URL 等）をチャンネル別に分離した構造体 |
| 非破壊 | drive-worker の設計方針。ファイル/フォルダの削除・上書き・移動・改名 API を持たない |
| Qセーブ | YouTube 説明文 / Bluesky 本文を localStorage のクイック枠に一時保存する機能（Qロード・リセット・元に戻すと対） |
| refreshEngagement | Bluesky 公開 API（未認証）でいいね/リポスト/返信を毎時更新する GAS 関数 |
| refreshClicks | go5-short `/api/stats` で開封数（旧 Bitly クリック計測の代替）を毎時更新する GAS 関数 |
| runReservations | 予約シートの pending 行を Bluesky へ自動投稿する GAS 関数（5 分トリガー）|
| snapshot.gs | YouTube Data API v3 で経過時間別の再生数スナップショットを蓄積する追加 GAS スクリプト（コード完成・未デプロイ）|
| putIf | GAS `writeRecord_` 内のヘルパー。upsert 更新時に既存値を空で上書きしない（カウンタ 0 クランプ防止）|
| testMode | 動画 ID に `test-` 接頭辞を付け、Bluesky 実投稿するが GAS シート記録しないモード |
| SHARED_SECRET | フロントと Worker が同値を持つソフト鍵。Worker 側は `env.SHARED_SECRET`（Worker Secret）に格納 |
| AFI | アフィリエイト（Drive フォルダ名 `AFI5秒動画` 等で使用）|
| rand4 | base36（[0-9a-z]）4 桁乱数。`idgen.js` の `rand4()` が生成 |

---

> **スポットチェック記録（§4.5 検証）**:
> 1. §5 videoId 形式 → `idgen.js:35-39` で確認 ✅
> 2. §6.1 HEADERS40 40列 → `gas/コード.gs:22-28` で確認 ✅
> 3. §7 link-worker KV スキーマ `u:<code>` 不変 → `link-worker/src/index.js:100-101` で確認 ✅
> 4. §4 W.videoId は video-created 経由 → `wizard.js:356-364` で確認 ✅
> 5. §9 facet UTF-8 byteLen → `bluesky-core.js:18-23` で確認 ✅
> 6. §8 testMode シート未記録 → `gas/コード.gs:122` で確認 ✅
> 7. §7 drive-worker 非破壊 → `drive-worker/src/index.js` 全体走査（DELETE/PATCH 0件）で確認 ✅
>
> **秘密スキャン**: 本文中に API キー・トークン・パスワード・OAuth 資格情報の実値なし ✅
> SHARED_SECRET の既定値は §13-10 でキー名と設計意図のみ言及（実値は記載なし）✅
