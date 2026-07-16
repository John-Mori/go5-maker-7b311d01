# 5秒動画メーカー（スマホ版）— プロジェクト全体設計書 / AI引き継ぎ用

> **このファイルの使い方（重要）**
> このマークダウンは「Claude（通常チャット含む）が読み込めば、このプロジェクトが
> *何のセッションで・何を作っているのか* を一発で理解し、そのまま設計をブラッシュアップする
> 議論に入れる」ことを目的にした **引き継ぎ＆設計ドキュメント** です。
> コードの詳細仕様は `CLAUDE.md`（プロジェクトの公式コンテキスト）が一次情報。本書はその上位の
> 「全体像・設計思想・課題・次の論点」をまとめた俯瞰図です。食い違いがあれば実コードと `CLAUDE.md` が優先。
>
> **読んだAIへのお願い**：まずは§13「設計ブラッシュアップの論点」を一緒に詰める相手として振る舞ってください。
> いきなり実装に飛ばず、課題（§12）と論点（§13）を踏まえて選択肢と推奨を提示してほしい。

最終更新: 2026-06-24 ／ 対応バージョン: `?v=48`（`link-worker` 追加時点）

---

## 1. これは何か（30秒サマリ）

iPhone等の**ブラウザだけ**で、写真＋テキストから **5秒・縦型(9:16)** の動画を作る、**完全クライアントサイド**のWebアプリ。
動画合成は端末内（Canvas＋MediaRecorder）で完結し、**PC・サーバー不要**。用途は成人向け漫画作品（FANZA）の宣伝ショート動画の量産＆配信。

単なる動画作成にとどまらず、**「作る→保存する→投稿する→記録する→検証する」までの運用パイプライン**を、
GitHub Pages（静的ホスティング）＋少数のサーバーレス（Cloudflare Workers / Google Apps Script）で組んでいるのが特徴。

- **公開URL**: https://john-mori.github.io/go5-maker-7b311d01/
- **リポジトリ**: https://github.com/John-Mori/go5-maker-7b311d01 （GitHub Pages・main/(root) 公開）
- **ビルド不要**: 素のHTML/JS。`?v=N` クエリでキャッシュ更新。
- **2アカウント運用**: `acc1`＝月詠み色恋劇場 / `acc2`＝宵桜艶帖（背景動画・テーマ配色・各種設定がアカウント別）。

---

## 2. 全体アーキテクチャ

```
┌──────────────────────────── ブラウザ（スマホ／PC）────────────────────────────┐
│  GitHub Pages 上の静的サイト（index.html）＝5タブ構成                          │
│                                                                              │
│  🎬動画作成   📅カレンダー(iframe)  🦋投稿   🔗アフィリンク   🧪検証          │
│   app.js       schedule/*           bluesky.js  affiliate.js   verify.js       │
│   └Canvas合成   └投稿時間最適化       └Bluesky投稿  └FANZAリンク  └KPI集計        │
│                                                                              │
│  グルー: integration.js（親⇄iframe postMessage）／ scheduler.js（端末内予約）   │
│  状態: localStorage（プレビュー位置・アカウント別設定・スケジュール・履歴）       │
└───────────────┬───────────────┬───────────────┬──────────────────────────────┘
                │ video-created  │ POST /api/shorten│ POST(JSON) 記録
                ▼                ▼                 ▼
   ┌────────────────────┐ ┌──────────────────┐ ┌───────────────────────────────┐
   │ drive-worker (CF)  │ │ link-worker (CF) │ │ gas/コード.gs (Google Apps Script)│
   │ 動画＋画像をGDrive  │ │ 自前URL短縮       │ │ Bitly短縮＋スプレッドシート記録    │
   │ へ自動保存(非破壊)  │ │ 302即リダイレクト  │ │ ＋毎時クリック/反応更新＋無人予約投稿│
   └─────────┬──────────┘ └────────┬─────────┘ └───────────────┬───────────────┘
             ▼                     ▼                           ▼
        Google Drive          Cloudflare KV            Bitly API / Bluesky公開API /
     (マイドライブ/...)       (u:code, c:code)          Google Sheets / Drive(一時)
```

**設計思想（3本柱）**
1. **クライアントサイド最優先**：動画合成・プレビュー・投稿は端末完結。サーバーは「ブラウザからは原理的に無理な事」だけを担う最小構成。
2. **サーバーレスは薄く・非破壊・多層防御**：各Workerは Origin制限＋共有シークレット（ソフト鍵）＋KVレート制限。破壊的操作（削除/上書き）は実装しない。秘密の本体は各サービスのSecretsにのみ置く。
3. **比率ベースの座標系を絶対に崩さない**（§10）。プレビューと書き出しが同一Canvas・同一描画式で一致することがプロダクトの肝。

---

## 3. 機能ドメイン別の中身

### 3.1 🎬 動画作成（`app.js` / `index.html` / `style.css`）
- **基準フレーム**: `W=1080, H=1920`（9:16）。`DURATION=5秒`, `FPS=30`。旧px定数は `U(v)=v*H/1280` で換算。
- **描画**: `drawFrame(t)` 1本にプレビューも書き出しも集約。背景動画(`assets/bg_*.mp4`)＋アップロード写真＋3段テキスト（作者名／誘導文／大タイトル）と黒帯。
- **位置調整**: 計9コントロール（＋/−ボタン式）。`OFF` オブジェクトで一元管理し、`app.js` の `CONTROLS` テーブルが配線：
  - `whole`（全体）／`textAuthor|textDetail|textTitle`（各段の文字）／`bandAuthor|bandDetail|bandTitle`（各段の帯）／`bandPad`（帯の余白）／`rowGap`（段間隔）。
  - **文字オフセットは描画位置のみに加算し、段送りには波及させない**（他段に影響しない独立設計）。
- **録画**: `cv.captureStream(FPS)`＋`MediaRecorder`。MIME優先順 `video/mp4(avc1)`→`video/mp4`→`video/webm(vp9)`→`video/webm`、ビットレート8Mbps。
- **完了時**: `document` に **`video-created`**（`{title, blob, name}`）を dispatch → 投稿/保存系が購読。
- **アカウント切替**: `getCurrentAccount()`＝`acc1/acc2`。背景動画とテーマ配色（acc1=白文字＋黒縁＋黒帯 / acc2=温白文字＋桜ピンク3層グロー＋梅色帯）。切替で `account-changed` を dispatch。

### 3.2 🔗 アフィリンク（`affiliate-core.js` / `affiliate.js`）
- 純粋関数 `buildAffiliateLink(rawUrl, afId)`：作品URLから `cid` を抽出し、FANZAアフィリエイトリンク `https://al.fanza.co.jp/?lurl=...&af_id=...&ch=toolbar&ch_id=link` を生成。
- `afId` 未入力時はプレースホルダ `【アフィID】`（構造プレビュー）。エラーは `empty / no_cid / bad_url`。
- テンプレ変更は **`buildAffiliateLink()` 内のみ**に局所化する規約。

### 3.3 🦋 投稿（`bluesky-core.js` / `bluesky.js`）
- **完全クライアントサイドの Bluesky 投稿**。`https://bsky.social` の XRPC を直接叩く（CORS対応）。認証は**アプリパスワード**（revoke可）。
- **投稿コア** `BlueskyCore.blueskyPostRaw({identifier, appPassword, text, imageBlob, alt})`：本文そのまま投稿＋`detectFacets()` で本文中URL/ハッシュタグを自動リンク化（facet index は **UTF-8バイトオフセット**）。
- **at:// → 共有URL**：`at://…/<rkey>` から `https://bsky.app/profile/<handle>/post/<rkey>` を生成。
- **3つの投稿経路**：
  1. **動画作成後の自動投稿**（`video-created` 購読 → 編集可能な確認モーダル → 投稿）
  2. **今すぐ単独投稿**（🦋タブの postNow ボタン）
  3. **予約投稿**（§3.6 scheduler.js、またはGAS無人）
- 投稿成功で **`bluesky-posted`**（`{post_uri, post_url, affiliate, hashtags, posted_at, title, slotId?}`）を dispatch。
- **短縮URL**：`shortenUrl()` が **自前Worker(link-worker) → is.gd → cleanuri → 長いURL** の順でフォールバック（§5.2／§12）。
- **記録送信**：`bluesky-posted` 購読で GAS Web App へ `{channel,title,postUrl,affiliateUrl,workUrl,hashtags,postUri}` を POST（§3.7）。
- **短縮URL履歴**：端末内・アカウント別（`short_hist__<acc>`、最大200件）。`post.html` は同等機能の単独ページとして残置。

### 3.4 📅 カレンダー（`schedule/` を iframe 埋め込み）
- **投稿時間最適化システム**を iframe で隔離埋め込み（CSS/JS衝突回避・本体は回帰ゼロ）。同一オリジンで localStorage 共有。
- **day-type 分類**（`daytype.js`）：前日/当日/翌日の休み状況から **平日型／休前日型／連休初日型／連休中日型／最終日型** を判定。祝日CSV(`holidays.js`)＋長期休暇レンジ（年末年始・お盆）＋週末＋個別override。
- **スロット生成**（`generator.js`）：day-type別テンプレ（`schedule_master.js`）から1日6枠を生成。`accountOffsetMin`（acc1=+0/acc2=+20分）で時刻シフト。確定枠（予約登録済/公開済）は時刻/役割を保護し、変化時のみ `needs_review`。`scheduled_at ≤ now` で自動「公開済」化。冪等（再生成で壊れない）。
- **共有ストア**（`store.js`）：localStorage キー **`sch_state_v1`** ＝ `{overrides, slotData}`。アダプタ抽象で localStorage ⇄ Supabase 切替可（既定 local）。
- **親⇄iframe 連携**（`integration.js` ＋ schedule/js/app.js）：スロット編集の「🎬この枠で動画を作る／🦋この枠を投稿する」を `postMessage`(`source:'sch-calendar'`)で親へ → 親がタブ切替＋対象スロットのバナー表示。投稿成功で親から iframe へ `slot-writeback`（公開済＋URL）を書き戻し。

### 3.5 🧪 検証（`verify-core.js` / `verify.js`、カレンダー内タブ）
- 共有ストア(`sch_state_v1`)の「公開済」投稿を一覧し、KPIを day-type 別に集計。
- **3つのデータ源**：①Bluesky公開API(`public.api.bsky.app` getPosts・未認証・CORS)の **いいね/リポスト/返信**、②Bitlyクリック(`slot.click_count`)、③FANZA成約（手入力・localStorage `verify_fanza`）。
- 純粋関数 `buildGetPostsUrl()`/`parseEngagement()`/`postedSlotsFromState()`。検証KPIはYouTube前提→Bluesky指標へ再定義済。CSV書き出し対応。

### 3.6 ⏰ 予約投稿（`scheduler.js`）— Phase3（端末内）
- 30秒ごとの tick で、純粋関数 `dueItems(queue, now)` が期限到来（pending かつ `scheduledAtMs≤now`）の予約を `BlueskyCore.blueskyPostRaw` で自動投稿 → `bluesky-posted`(slotId付) を dispatch。
- **このタブを開いている間のみ**動作。キュー・画像Blobは **in-memory**（リロードで消える）。無人化は §3.7 のGAS（Phase5）が担当。

### 3.7 ☁️ サーバーレス3種

| コンポーネント | 技術 | 役割 | 主なルート/関数 | 秘密/設定 |
|---|---|---|---|---|
| **drive-worker/** | Cloudflare Worker＋KV | 動画＋元画像を Google Drive `マイドライブ/AFI5秒動画/[チャンネル]/[動画名]/` へ**非破壊**自動保存 | `POST /`（form-data: channel/title/video/image） | `GOOGLE_CLIENT_ID/SECRET/REFRESH_TOKEN`, `SHARED_SECRET`, `FOLDER_ID_ACC1/2`, KV `RL` |
| **link-worker/** | Cloudflare Worker＋KV | 自前URL短縮。**302即リダイレクト（中間ページなし）**＋クリック概算 | `POST /api/shorten`, `GET /:code`, `GET /api/stats`, `GET /` | `SHARED_SECRET`, `ALLOWED_HOSTS`(既定bsky.app/social), `DAILY_LIMIT`, KV `LINKS` |
| **gas/コード.gs** | Google Apps Script | Bitly短縮＋スプレッドシート記録、毎時クリック/反応更新、無人予約投稿 | `doPost`(記録/reserve), `doGet`(JSONP読取), `refreshClicks`/`refreshEngagement`(毎時), `runReservations`(5分) | `BITLY_TOKEN`, `SHEET_ID`, `BSKY_HANDLE/APP_PW` |

**drive-worker の非破壊設計（最重要）**：作るのは「フォルダ新規作成／ファイル新規アップロード／参照(read)」のみ。削除・上書き・移動・改名・ゴミ箱APIは**一切実装しない**（grep検証済）。同名は `_2,_3…` 連番で新規作成。認証は本人OAuth refresh_token（個人Gmailのため Service Account 不可）を Worker Secrets に保管。

**link-worker の冪等設計**：コードは **URLのSHA-256→base62**＝同一URLは常に同一短縮URL（重複作成なし）。KV `u:<code>` は不変。`GET /:code` は `302 + Cache-Control:no-store` で即リダイレクト＆クリック概算カウント（`ctx.waitUntil`でブロックしない）。宛先は `ALLOWED_HOSTS` 限定なので、万一ソフト鍵が漏れても踏み台（オープンリダイレクタ）にならない。**未デプロイ**（PC側で作業予定）。

**GAS の記録**：`channel`(acc1/acc2) に応じ **`記録_ch1`/`記録_ch2`** へ列名マッピングで追記。`refreshClicks`(Bitly)＋`refreshEngagement`(Bluesky公開API)を毎時更新。`runReservations` が「予約」シートのpendingを `bskyPost_`（createSession→uploadBlob→createRecord・facet）で無人投稿、画像はDrive一時保存→投稿後ゴミ箱。**注意**：GAS側 `SHARED_SECRET` は現在フロントが送らないため**設定してはいけない**（設定すると全リクエストが弾かれる）。

---

## 4. イベント／メッセージバス（統合の要）

### 4.1 カスタムイベント（document）
| イベント | 発火元 | payload | 主な購読者 |
|---|---|---|---|
| `video-created` | app.js（動画完成時） | `{title, blob, name}` | bluesky.js（自動投稿）, drive-upload.js（Drive保存） |
| `account-changed` | app.js（アカウント切替） | `{id}` | bluesky.js（設定適用）, integration.js（iframe再計算） |
| `bluesky-posted` | bluesky.js / scheduler.js（投稿成功） | `{post_uri, post_url, affiliate, hashtags, posted_at, title, slotId?}` | integration.js（slot-writeback）, bluesky.js（GAS記録＋短縮）, scheduler.js（通知） |

### 4.2 postMessage（親 ⇄ schedule iframe）
- **iframe→親**：`{source:'sch-calendar', type:'slot-create'|'slot-post', slot:{...}}`
- **親→iframe**：`{target:'sch-calendar', type:'recompute'}` ／ `{target:'sch-calendar', type:'slot-writeback', id, status:'公開済', post_uri, post_url, short_url, url, posted_at}`

### 4.3 主な localStorage キー
- **プレビュー位置**：`preview_offset_y`（全体）／`preview_text_author|detail|title`／`preview_band_author|detail|title`／`preview_band_pad`／`preview_row_gap`（各 `*_default` あり）。旧キー `v_offset`・`preview_band_y` は自動移行。
- **アカウント**：`current_account`。多くの設定は `__acc1`/`__acc2` サフィックスで分離。
- **Bluesky/投稿（アカウント別）**：`bsky_enable__*`, `bsky_text__*`, `bsky_work_url__*`, `bsky_handle__*`, `bsky_app_pw__*`, `bsky_unattended__*`, `yt_desc__*`, `yt_tags__*`, `short_hist__*`。共通：`bsky_gas_url`, `fanza_af_id`, `bsky_avatar_<handle>`, `bsky_dn_<handle>`。
- **短縮Worker上書き**：`short_worker_url`, `short_shared_secret`。**Drive Worker上書き**：`drive_worker_url`, `drive_shared_secret`。
- **スケジュール/検証**：`sch_state_v1`（共有状態）, `verify_fanza`（FANZA成約手入力）, `sb_session_v1`（Supabase併用時）。

---

## 5. 直近の変更（短縮URL周り・このセッションの主題）

### 5.1 背景の課題
共有用短縮URLに **TinyURL** を使っていたが、無料リンクが開封時に広告的な **Preview（中間）ページ** を挟むようになり、ユーザーを不安にさせ直帰の原因に。`api-create.php` 側に無効化手段がない。

### 5.2 対応（実装済み・push済み／ブランチ `claude/vigilant-mendel-wjbvg5`）
1. `bluesky.js` の `shortenUrl()` を **TinyURL廃止 → 自前Worker → is.gd → cleanuri → 長いURL** のフォールバック構成へ（短縮処理は1箇所に集約）。
2. **自前短縮 `link-worker/`** を新設（Cloudflare Worker＋KV、302即リダイレクト、冪等、クリック計測、ホスト限定）。`drive-worker` と同じ運用流儀。
3. デプロイ手順 `link-worker/SETUP.md`。キャッシュ版数 `v=47→48`。

### 5.3 残作業
- **link-worker のデプロイ**（`npx wrangler`：KV作成→secret登録→deploy）。**Cloudflareログインが要るためPC側で実施予定**。デプロイ後は `name=go5-short`・同アカウント・同シークレットならフロント編集不要で自動的に自前短縮へ切替（未デプロイ中は is.gd にフォールバックするので安全）。

---

## 6. テスト・公開・運用

- **テスト**：`node tests/test_*.js`（純粋関数中心）。現状 **全PASS（合計31ケース）**：affiliate 11 / bluesky 12 / scheduler 3 / verify 5。
- **公開**：`git add -A && git commit && git push` で GitHub Pages に1〜2分で反映。
- **キャッシュ運用**：`index.html` の `app.js?v=N` 形式。**中身を変えたら N を1つ上げる**（現在 `v=48`）。
- **ブランチ運用（このセッション）**：開発は `claude/vigilant-mendel-wjbvg5`。PRはユーザーが明示的に依頼したときのみ作成。

---

## 7. 座標系の規約（最重要・崩さない）

- 基準フレーム **`W=1080, H=1920`（9:16）が唯一の基準座標系**。`<canvas width height>` も一致。
- 位置・フォントサイズは `H×係数` / `W×係数`。旧px定数は `U(v)=v*H/1280` で換算。**px/vh/vw を直接使わない**。
- **プレビューも書き出しも同一Canvas・同一描画式（`drawFrame`）** → PC/スマホ/書き出しで一致（CSSは9:16を一様縮小表示するだけ）。
- 縦オフセットは `OFF` で一元管理。文字オフセットは描画位置のみ・段送りに波及させない。帯オフセットは帯矩形Yのみ。各段・文字・帯は完全独立。
- `document.fonts.ready` 後に再描画（フォント計測由来のズレ防止）。

---

## 8. ファイル早見表

| 種別 | パス | 役割 |
|---|---|---|
| 画面 | `index.html` / `style.css` | 5タブUI・ダークスマホUI |
| 中核 | `app.js` | Canvas合成・テキスト描画・録画・9コントロール配線・アカウント切替 |
| アフィ | `affiliate-core.js` / `affiliate.js` | `buildAffiliateLink()`（純粋）＋UI＋タブ駆動(`TABS`) |
| Bluesky | `bluesky-core.js` / `bluesky.js` | 投稿コア（facet/at→URL/画像）＋投稿UI・短縮・GAS記録・履歴 |
| 予約 | `scheduler.js` | 端末内予約投稿（`dueItems` 純粋関数・30秒tick） |
| 検証 | `verify-core.js` / `verify.js` | KPI集計（Bluesky/Bitly/FANZA）・CSV |
| 統合 | `integration.js` | 親⇄iframe postMessage・スロットバナー・writeback |
| Drive保存 | `drive-upload.js` ＋ `drive-worker/` | `video-created`購読→Worker→Drive非破壊保存 |
| 短縮 | `link-worker/`（＋`bluesky.js shortenUrl`） | 自前URL短縮（302即リダイレクト・冪等・計測） |
| 記録 | `gas/コード.gs` ＋ `gas/セットアップ手順.md` | Bitly短縮＋スプレッドシート記録＋無人予約 |
| スケジュール | `schedule/`（index.html / js/* / data/*） | 投稿時間最適化カレンダー（iframe） |
| テスト | `tests/test_*.js` | 純粋関数のNodeテスト |
| 資産 | `assets/bg_main.mp4` / `bg_account2.mp4` | アカウント別背景動画 |
| ドキュメント | `CLAUDE.md`（一次情報）／各種 `設計書_*.md` / `統合設計書_*.md` / ガイドHTML | 設計・手順 |
| 単独ページ | `post.html` | 投稿機能の単独版（残置） |

---

## 9. 用語・前提

- **acc1 / acc2**：2つの配信アカウント。acc1=月詠み色恋劇場、acc2=宵桜艶帖。背景・配色・各種設定がアカウント別。
- **FANZA アフィリンク**：作品の `cid` から生成する成約計測用リンク。本文に**生のまま（無改変）**貼る＝af_id計測を壊さない。
- **短縮URL（2系統あるので注意）**：
  - ①**共有用短縮**（ユーザーが実際に踏むURL。YouTube説明欄等に貼る）＝フロントの `shortenUrl()`（is.gd / 自前Worker）。
  - ②**Bitly短縮**（GASがスプレッドシートに記録・毎時クリック更新）。
  - → この①と②が**別URL**である点が現在の構造的論点（§12-A）。
- **day-type**：曜日ではなく「休みの並び」で投稿戦略を変えるための分類。
- **ソフト鍵（SHARED_SECRET）**：フロントに置く共有シークレット。公開前提の弱い鍵で、実防御はWorker側の Origin制限＋レート制限＋最小操作＋ホスト限定が担う。

---

## 10. アーキテクチャ上の不変条件（壊すと事故る）

1. **比率座標系（§7）**を崩さない。プレビュー＝書き出しの一致が最優先。
2. **drive-worker は非破壊**（create/read のみ）。削除・上書きAPIを足さない。
3. **link-worker の `u:<code>` は不変**。既存短縮URLが後から別宛先に変わらない。
4. **GAS の `SHARED_SECRET` は未設定のまま**（現フロントは送らない）。
5. **秘密の本体**（OAuth refresh_token / Bitlyトークン / アプリパスワード）は各サービスのSecrets/Propertiesのみ。console・repo・レスポンスに出さない。
6. 変更後は `?v=` を上げる。

---

## 11. 現在の状態

- 機能は**完成済みで安定動作**。動画作成〜投稿〜記録〜検証の一通りが回る。
- 直近で短縮URLを TinyURL→自前/is.gd系へ刷新（§5）。**link-worker のデプロイのみ未了**。
- テスト全PASS。GitHub Pages公開中。

---

## 12. 現在の課題・未解決事項（設計議論の入口）

> ここが「これから一緒にブラッシュアップしたい」部分。各項目に **A=現状 / B=論点 / C=たたき台** を付す。

### 課題A：短縮URLが2系統に分裂している（計測の不整合）
- **A**：ユーザーが実際に踏むのは①共有用短縮（is.gd / 自前Worker）。一方クリック計測は②Bitly（GASがシートに別の短縮URLを生成）。**②のbit.lyは誰も踏まないため、Bitlyクリック数が実態を反映しない可能性**。
- **B**：計測の単一の真実をどこに置くか。自前 `link-worker` のクリック概算（`c:<code>`）を正にして Bitly を畳むか、共有URL自体を Bitly に統一するか。
- **C案**：link-worker を計測の正にし、`GET /api/stats` の値を GAS の記録シート `Bitlyクリック` 列へ毎時流し込む（Bitly置換）。→ 共有URL＝計測URLが一致。

### 課題B：link-worker 未デプロイ（短縮の確実性が外部依存のまま）
- **A**：デプロイ完了までは is.gd/cleanuri 依存。これらは CORS/可用性/コンテンツ規約で失敗し得る（失敗時は長いURLにフォールバック＝「短縮されない」状態が起こりうる）。
- **B/C**：PC側で `link-worker/SETUP.md` を実行して自前短縮を本番化するのが最優先（このセッションの主目的の仕上げ）。

### 課題C：予約投稿の二層構造（端末内 Phase3 と 無人 Phase5）
- **A**：`scheduler.js`(Phase3) は**タブを開いている間のみ**＆キュー/画像が in-memory（リロードで消失）。無人投稿はGAS(Phase5)だが、画像base64送信・Drive一時保存など別経路。
- **B**：予約の「単一の入口」をどう設計するか。端末内予約をやめて常時GAS無人に寄せるか、両立させるか。在席/不在で挙動が変わる現状はユーザーに分かりにくい。
- **C案**：UI上は「予約＝常に無人(GAS)」を既定にし、端末内即時投稿は別物として分離。

### 課題D：ソフト鍵がリポジトリに平文
- **A**：`drive-upload.js` / `bluesky.js` にソフト鍵(`SHARED_SECRET`)が平文コミット。設計上は許容（実防御は別レイヤ）だが、レート制限の悪用余地は残る。
- **B/C**：Origin制限＋ホスト限定で実害は小さい前提を維持しつつ、必要なら定期ローテーション運用を決める。

### 課題E：MediaRecorder の出力形式が端末依存
- **A**：iOS Safari等で `video/mp4` が録れず `webm` になる場合がある。配信先(YouTube/Bluesky)や端末で扱いに差。
- **B/C**：出力形式の保証範囲を定義。必要なら mp4 固定が無理な端末向けの注意表示／変換方針を決める。

### 課題F：postMessage の origin が `'*'`
- **A**：親⇄iframe の postMessage が `'*'` 宛/`source`フィールド判定。同一オリジン埋め込みだが、厳密には targetOrigin を固定した方が安全。
- **B/C**：同一オリジン固定に締める軽微なハードニング（回帰リスク低）。

### 課題G：CI なし・テストは手動
- **A**：`node tests/*.js` を手で回す運用。回帰検知が人手依存。
- **B/C**：GitHub Actions で push時にテスト実行（純粋関数のみなので軽い）。`session-start-hook` 的な仕組みも候補。

### 課題H：状態が localStorage 集中（端末ローカル）
- **A**：スケジュール/履歴/設定が端末の localStorage。機種変更・複数端末で共有されない（Supabaseアダプタは存在するが未常用）。
- **B/C**：複数端末運用の必要性次第。必要なら Supabase 経路を本採用するか、エクスポート/インポート運用を定着させる。

---

## 13. 設計ブラッシュアップの論点（次のチャットで詰めたいこと）

読んだAIへ：以下を「選択肢＋推奨＋影響範囲（どのファイル/不変条件に触るか）」の形で一緒に整理してほしい。

1. **計測の一本化**（課題A/B）：自前 link-worker を計測の正に据える設計。`/api/stats`→GASシート連携の具体化。Bitlyを残すか畳むか。
2. **予約の単一入口**（課題C）：端末内予約と無人投稿の役割整理。UIの言葉の再定義。
3. **運用の堅牢化**（課題D/F/G）：ソフト鍵運用ルール、postMessage origin固定、CI導入の費用対効果。
4. **マルチ端末/バックアップ**（課題H）：localStorage一極集中からの脱却要否。
5. **出力品質**（課題E）：MediaRecorder形式の保証範囲と、失敗時のユーザー体験。
6. **拡張余地**：3アカウント以上への一般化、テンプレ/テーマの追加、他SNS（X等。ただし直投稿はCORS/サーバー制約あり）。

> 進め方の原則（`CLAUDE.md §5`）：メインは設計・計画・レビュー・統合に専念。実装の物量はサブエージェント（軽量モデル）へ「目的・入出力・受け入れ条件」を明記して委譲。比率座標系と非破壊設計の不変条件を常に死守。

---

## 14. クイックスタート（この設計書を読んだ人が最初にやること）

```bash
# ローカル確認
python3 -m http.server 8000   # → http://localhost:8000/
# テスト
node tests/test_affiliate.js && node tests/test_bluesky.js && \
node tests/test_scheduler.js && node tests/test_verify.js
# 公開（GitHub Pages）
git add -A && git commit -m "変更内容" && git push   # 1〜2分で反映。?v= を上げるのを忘れない
```

- 一次情報は `CLAUDE.md`。各サーバーレスの導入は `drive-worker/SETUP.md` / `link-worker/SETUP.md` / `gas/セットアップ手順.md`。
- まずは§12の課題と§13の論点を一緒に整理するところから。
