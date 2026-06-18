# CLAUDE.md — 5秒動画メーカー（スマホ版）開発コンテキスト

> **このフォルダ（スマホ版）が現行・最新ソースです。** ここを見れば「今の最新」が分かります。
> Claude Code は本ファイルを自動で読み込みます。MacBook 等で `git clone` した場合も同じコンテキストが効きます。

---

## 0. これは何か

iPhone等の**ブラウザだけ**で、写真＋テキストから **5秒・縦型(9:16)** 動画を作る完全クライアントサイドのWebアプリ。
合成は端末内（Canvas＋MediaRecorder）。PC・サーバー不要。FANZAアフィリエイトリンク生成機能も同梱。

- **公開URL：** https://john-mori.github.io/go5-maker-7b311d01/
- **リポジトリ：** https://github.com/John-Mori/go5-maker-7b311d01 （GitHub Pages・main/(root)）

---

## 1. 現在の状態（最新）

機能は完成済みで安定動作。プレビューの位置調整は **計9コントロール（＋/−ボタン式・プレビュー横で見ながら調整）**：

| 種別 | コントロール | 動かす対象 |
|---|---|---|
| 全体 | 全体の縦位置（下へ） | 文字＋帯＋漫画ページ をまとめて |
| 文字（段別） | ①作者名 / ②誘導文 / ③大タイトル の文字 | その段の**文字だけ** |
| 黒帯（段別） | ①作者名 / ②誘導文 / ③大タイトル の帯 | その段の**黒帯だけ** |
| 黒帯の余白 | 全段共通の帯パディング（`OFF.bandPad`） | 帯の厚み（文字まわりの余白） |
| 段の間隔 | 段どうしの追加スペース（`OFF.rowGap`） | 各段の縦の隙間 |

- すべて基準フレーム高さ比（px/vh/vw 不使用）。`localStorage` 保存・復元、「既定値に保存」「リセット」対応。各コントロールは `app.js` の `CONTROLS` テーブルで駆動（＋/−ボタンが `OFF[key]` を step 単位で増減）。

### 変更履歴（開発の順番）
1. FANZAアフィリンク生成機能を統合（タブ切替・純粋関数＋テスト）
2. プレビュー文字改善（「作者：」常時表示・黒帯はみ出し対策）
3. 基準座標系を **1080×1920** に統一（全パラメータ比率化／プレビュー＝書き出し一致）
4. 「全体の縦位置」スライダー追加
5. スマホで横潰れする不具合を修正（CSSの9:16固定崩れ／`?v=` キャッシュ対策）
6. スライダーの保存・既定値・リセット（汎用 `Store` ヘルパ）
7. 黒帯を3段別に独立制御
8. 文字も3段別に独立 ＝ 現在の7本構成
9. **Bluesky 自動投稿**を追加（完全クライアントサイド）。動画作成後に確認ダイアログ→**挿入した元写真**＋固定文＋提携文＋**生のアフィリンク(無改変)** を投稿
10. **投稿記録＆クリック集計**を追加。投稿後、共有URLを GAS Web App へ送信→Bitly短縮→Googleスプレッドシートに「題名(動画タイトル)/各URL/クリック数」を記録。クリック数＝**投稿短縮URLの開封数**（アフィリンクには介入しない設計）
13. **スケジュール統合 Phase1（v=13）**：投稿スケジュール最適化システムを **📅カレンダータブ**として統合（`schedule/` に配置し **iframe** 埋め込み＝CSS/JS衝突回避・既存機能は回帰ゼロ）。同一オリジンで localStorage 共有。タブは 🎬動画作成／📅カレンダー／🦋投稿／🔗アフィリンク（🧪検証はカレンダー内）。設計書＝`5秒動画タイムスケジュール/docs/統合設計書_動画メーカー×スケジュール.md`。
15. **スケジュール統合 Phase3 予約投稿（v=15）**：`scheduler.js` を追加。🦋投稿タブに **⏰予約投稿**（datetime＋予約ボタン＋予約中リスト）。30秒ごとの tick で期限到来(pending かつ scheduledAtMs≤now)の予約を `BlueskyCore.blueskyPostRaw` で自動投稿→`bluesky-posted`(slotId付)発火→`integration.js`がスロット書き戻し＋ブラウザ通知。**このタブを開いている間のみ**（画像等はin-memory／無人化はPhase5のcronで対応）。`dueItems` は純粋関数でNodeテスト可（`tests/test_scheduler.js` 3項目）。📅から来た場合は枠の予定時刻をプリフィル。
14. **スケジュール統合 Phase2 一気通貫（v=14）**：カレンダーのスロット編集に「🎬この枠で動画を作る／🦋この枠を投稿する」を追加→`postMessage`で親へ（`schedule/js/app.js`）。親は `integration.js` で受けて該当タブへ切替＋**対象スロットのバナー表示**（`#slotCtxMovie/#slotCtxPost`）。投稿成功で `bluesky.js` が `bluesky-posted` を発火→`integration.js`がiframeへ`slot-writeback`→スロットを **公開済＋URL** に更新。橋渡しは postMessage＋同一オリジンlocalStorage。次：Phase3 予約投稿／Phase4 Bluesky用検証KPI。
12. **3タブ統合（v=12）**：1ページに **🎬動画作成／🦋投稿／🔗アフィリンク** の3タブ。投稿手段は2つ＝**①動画作成後の自動投稿**（`#bskyEnable`／本文＋動画の元写真）と **②単独で今すぐ投稿**（🦋投稿タブの `#postNowBtn`／本文＋任意画像 `#postImg`）。本文 `#bskyText`・アカウント設定は両手段で共通。🦋投稿タブに **Bluesky風ライブプレビュー**（このまま投稿される見た目）。タブ切替は `affiliate.js` の `TABS`。`post.html` は単独ページとして残置（同等機能）。
11. **UI再設計（v=11）**：①位置調整を**スライダー→＋/−ボタン**化し、プレビュー横（スマホは sticky）で見ながら微調整。②**黒帯の余白**(`OFF.bandPad`)と**段の間隔**(`OFF.rowGap`)を追加（計9コントロール）。③Bluesky投稿欄を**1つの自由テキスト本文(`bskyText`)に統合**（固定文/提携文/作品URL欄を廃止）。本文中の生アフィリンクは `detectFacets` で自動リンク化＝無改変。④アプリパスワード等は折りたたみ＝任意（未入力なら投稿スキップ）

---

## 2. ファイル構成

| ファイル | 役割 | 触ってよいか |
|---|---|---|
| `index.html` | 画面（動画作成タブ＋アフィリンクタブ＋7スライダー） | UI追加時 |
| `app.js` | ★中核：Canvas合成・テキスト描画・録画・スライダー配線 | 描画/座標の変更はここ |
| `style.css` | スマホ向けスタイル（ダークUI・タブ・スライダー群） | |
| `affiliate-core.js` | アフィリンク生成の**純粋関数** `buildAffiliateLink()` | 仕様変更時のみ |
| `affiliate.js` | アフィリンク画面のUI配線（入力・コピー・永続化） | |
| `bluesky-core.js` | Bluesky 投稿コア。**純粋関数** `buildBlueskyPost()`（本文＋リンクfacet）＋ `blueskyPostWithImage()`（ログイン→画像アップロード→投稿） | 仕様変更時のみ |
| `bluesky.js` | Bluesky 設定UIの配線・確認ダイアログ・**元写真**のJPEG圧縮（1MB制限対応）・投稿後に GAS へ記録送信。`video-created` イベントを購読 | |
| `gas/コード.gs` | **サーバーレス（Google Apps Script）**。投稿URLを Bitly 短縮→スプレッドシート追記、`refreshClicks` で毎時クリック数更新。本体とは別デプロイ | 仕様変更時 |
| `gas/セットアップ手順.md` | Bitlyトークン・Sheet・GASデプロイの手順書 | |
| `assets/bg_main.mp4` | 背景動画 | 差し替え可 |
| `tests/test_affiliate.js` | Node テスト（T-1〜T-4＋エッジ） | |
| `tests/test_bluesky.js` | Node テスト（`buildBlueskyPost` の facet バイトオフセット検証） | |
| `設計書_スマホ版.md` / `改修設計書_スマホ版完全版.md` | 設計・保守ドキュメント | |

---

## 3. 座標系の規約（最重要・崩さない）

- 基準フレーム **`W=1080, H=1920`（9:16）が唯一の基準座標系**。`index.html` の `<canvas width height>` も一致させる。
- 位置・フォントサイズは `H×係数` / `W×係数`。旧来の絶対px定数は **`U(v)=v*H/1280`** で基準フレームに換算。
- プレビューも書き出しも**同一Canvasに同じ式で描画** → PC/スマホ/書き出しで一致（CSSは9:16を一様縮小表示するだけ）。
- 縦オフセットは `OFF` オブジェクトで一元管理：
  - `OFF.whole`（全体）／`OFF.textAuthor/textDetail/textTitle`（各段の文字）／`OFF.bandAuthor/bandDetail/bandTitle`（各段の帯）。
  - **文字オフセットは描画位置にのみ加算し、段の送りY（次段位置）には反映しない**＝他段に波及しない。
  - 帯オフセットは帯の矩形Yにのみ加算（基準Y基準）。文字と帯・各段は完全独立。
- `document.fonts.ready` 後に再描画（フォールバックフォント計測由来のズレ防止）。

### localStorage キー
`preview_offset_y`（全体）／`preview_text_author|detail|title`／`preview_band_author|detail|title`、各 `*_default`（既定値）。旧キー `v_offset`・`preview_band_y` は自動移行。

### キャッシュ運用
`index.html` のアセット参照は `app.js?v=N` の形。**中身を変えたら `N` を1つ上げる**とスマホで確実に最新が読まれる（現在 v=12）。

### Bluesky 投稿（§9 機能）の要点
- 完全クライアントサイド。`https://bsky.social` の XRPC を直接叩く（CORS対応・サーバー不要）。認証は**アプリパスワード**（通常PWではない／revoke 可能）。
- フロー：`app.js` の `make()` 成功時に `video-created` を dispatch → `bluesky.js` が購読 → 確認ダイアログ → `#cv` の最終フレームを JPEG 圧縮（≤約950KB）→ `blueskyPostWithImage()`。
- 画像 embed（`app.bsky.embed.images`）と外部リンクカードは併用不可のため、**作品URLは本文に richtext#link facet 付きで入れる**（facet の index は **UTF-8 バイトオフセット**）。
- 設定の localStorage キー：`bsky_enable` / `bsky_text`（本文1ボックス） / `bsky_handle` / `bsky_app_pw` / `bsky_gas_url` / `bsky_gas_secret`。位置調整は `preview_*`（`preview_band_pad`・`preview_row_gap` を追加）。
- 投稿は `BlueskyCore.blueskyPostRaw({identifier,appPassword,text,imageBlob,alt})`＝本文そのまま投稿＋`detectFacets` で本文中URLを自動リンク化。旧 `buildBlueskyPost`/`blueskyPostWithImage` も残置（互換・テスト用）。
- 秘匿情報（アプリパスワード・af_id・シークレット）は **console に出さない**（既存方針を踏襲）。

### 投稿記録＆クリック集計（§10 機能）の要点
- **クリック数＝投稿の短縮URL（Bitly）の開封数**。アフィリンクは本文に**生のまま（無改変）**貼るため af_id 計測は壊れない。生アフィリンクのクリック実数は取得不可（FANZA 管理画面が正）。
- 投稿の共有URLは `at://…/<rkey>` から `https://bsky.app/profile/<handle>/post/<rkey>` を組み立て（`bluesky-core.js`）。
- クライアントは GAS Web App へ `{secret,title,postUrl,affiliateUrl}` を **Content-Type無指定の POST**（＝simple request でプリフライト回避）。GAS が Bitly 短縮＋Sheet追記。
- Bitly トークンは **GAS 側のスクリプトプロパティに隠蔽**（公開サイトには置かない）。トークン秘匿＋CORS回避のためにサーバーレスを1つ挟む構成。
- X(旧Twitter)はこの構成では不可（OAuth＋サーバー必須・直投稿はCORS不可）。

---

## 4. ビルド・テスト・公開

- ビルド不要（素のHTML/JS）。ローカル確認：`python3 -m http.server 8000` → `http://localhost:8000/`
- テスト：`node tests/test_affiliate.js`（全PASSを確認）
- 公開（GitHub Pagesへ反映）：
  ```bash
  git add -A && git commit -m "変更内容" && git push
  # 1〜2分で公開URLに自動反映
  ```
  push認証：GitHubユーザー名＋Personal Access Token（リモートURLにトークンを埋め込まない）。

---

## 5. 作業の進め方（モデル分業ポリシー）

メインセッション＝設計・計画・レビュー・統合に専念。実装の物量は Task ツールで**軽量モデル（例 sonnet）のサブエージェント**へ委譲する。委譲時は「目的・入力と出力・受け入れ条件」を明記。探索やログ調査などノイズの多い作業もサブへ寄せ、メインの文脈を設計判断のためにきれいに保つ。

---

## 6. やってはいけない／注意

- 上記 §3 の比率ベース座標系を崩さない（px/vh/vw を直接使わない）。
- プレビューと書き出しは同一Canvas・同一描画式に保つ（一致が崩れる変更を避ける）。
- 変更後はアセットの `?v=` を上げる。
- アフィリンクのテンプレート変更は `affiliate-core.js` の `buildAffiliateLink()` 内のみで局所化する。
