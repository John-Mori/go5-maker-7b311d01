# CLAUDE.md — 5秒動画メーカー(スマホ版)開発コンテキスト

> **このフォルダ(スマホ版)が現行・最新ソースです。** ここを見れば「今の最新」が分かります。
> Claude Code は本ファイルを自動で読み込みます。MacBook 等で `git clone` した場合も同じコンテキストが効きます。

---

## 0. これは何か

iPhone等の**ブラウザだけ**で、写真＋テキストから **5秒・縦型(9:16)** 動画を作る完全クライアントサイドのWebアプリ。
合成は端末内(Canvas＋MediaRecorder)。PC・サーバー不要。FANZAアフィリエイトリンク生成機能も同梱。

- **公開URL：** https://john-mori.github.io/go5-maker-7b311d01/
- **リポジトリ：** https://github.com/John-Mori/go5-maker-7b311d01 (GitHub Pages・main/(root))

---

## 1. 現在の状態(最新)

> **巻の引き継ぎ**：開発チャットは巻(Vol.)で分かれる。現在 **Vol.8**(live=`?v=354` / GAS=`2026-07-14C`。※本行の版数は目安——**liveの正は`index.html`のクエリ・GASの正は`gas/コード.gs`のGAS_VERSION**を都度見る)。新チャットは最初に **`引き継ぎ_Vol7.md`**(次巻分が出来たらそちら)を読むこと(旧巻はすべて `docs/引き継ぎ/` へ移動・2026-07-17)。ミス台帳は `インシデント.md`。開いている依頼の台帳=`local/requests.jsonl`(起動時にopenを読み上げ)。★UI文言の括弧は必ず半角`()`(全角`()`禁止)。
> **中期計画**：機能改修・リファクタ・Shorts対策は **`docs/設計・調査/改善書_Shorts攻略と全体改善ロードマップ.md`**(2026-07-05策定)のタスク表(受け入れ条件・モデル割当つき)に沿って進める。着手前に改善書§1の裁定4項目をChamiに確認すること。
> **AI部門制・研究室(2026-07-11導入・実装Go済)**：メインセッション=研究室(モデルはFable 5→提供終了後Opus)。タスクは `.claude/agents/` の7部門(system-engineer/product-scout/copy-director/shorts-analyst/qa-reviewer/kaizen-analyst/learning-coach)へ、モデル(opus/sonnet/haiku)を**明示指定**して振り分ける。ルール正本=**`docs/departments/00_common/orchestration.md`**(必読・品質優先6段原則/Python積極利用[許可不要]/権限規定。2026-07-18に常読の核+参照章`00_common/rules/`×3へ分割——イベント購読表・セッション分離マップ等は参照章側・同格に有効)。Chamiの改善要求は D1 `go5_kaizen`(12表・稼働中) の improvement_requests へ、デプロイ/バンプは system_changes へ研究室が記録。**改善は承認制**(提案→Chami承認→実装)。**品質を犠牲にしたトークン節約は禁止**(正確性>安全性>検証可能性>保守性>トークン効率>速度)。ロードマップ=`docs/設計・調査/AI組織_実装設計書_v3_統合ロードマップ.md`§10(S0-S2構築済)。

機能は完成済みで安定動作。プレビューの位置調整は **＋/−ボタン式(プレビュー横で見ながら調整)**：

| 種別 | コントロール | 動かす対象 |
|---|---|---|
| 全体 | 全体の縦位置(下へ) | 文字＋帯＋漫画ページ をまとめて |
| 位置(段別) | ①作者名 / ②誘導文 / ③大タイトル | その段の**帯＋文字を一体で**(帯は各段のテキストに統合＝常に文字を包んで一緒に動く。★旧「黒帯の位置(段別)」は廃止・2026-07-07) |
| 黒帯の余白 | 全段共通の帯パディング(`OFF.bandPad`) | 帯の厚み(文字まわりの余白) |
| 段の間隔 | 段どうしの追加スペース(`OFF.rowGap`) | 各段の縦の隙間 |

**2行モード**：①作者・④コメント(大タイトル)にそれぞれ「2行モード」チェックボックス(`authorTwoLine`/`topTwoLine`)。ONで欄を2行textarea化し、**ユーザーの改行(\n)位置で2行に分割**・中央揃え・帯は両行を1枚で囲う(`drawTitleBlockUnified`)。保存キー `movie_author_two_line` / `movie_two_line`。

- すべて基準フレーム高さ比(px/vh/vw 不使用)。`localStorage` 保存・復元、「既定値に保存」「リセット」対応。各コントロールは `app.js` の `CONTROLS` テーブルで駆動(＋/−ボタンが `OFF[key]` を step 単位で増減)。

### 変更履歴(開発の順番)
18. **Google Drive 自動保存(v=36)**：動画作成完了時(`video-created`)に、生成動画＋元画像を **Cloudflare Worker 経由**で `マイドライブ/AFI5秒動画/[チャンネル]/[動画名]/` へ自動アップロード。フロント＝`drive-upload.js`(チャンネルは `getCurrentAccount()`＝acc1/acc2、未判定なら保存せずエラー。失敗しても動画作成は成功のまま・リトライ可)。Worker＝`drive-worker/`(**非破壊：フォルダ新規作成・ファイル新規アップロード・参照のみ。削除/上書き/移動/改名APIは不在＝grep検証済**。同名は `_2,_3…` 連番で新規作成)。認証は本人OAuth refresh_token(個人Gmailのため Service Account 不可)を **Worker Secrets** に保管。スコープは `drive`(既存フォルダへ書くため／作成専用コードで運用。承認済)。Origin制限＋共有シークレット＋KV日次レート制限の多層防御。フォルダIDは env 固定(取り違え防止)。手順＝`drive-worker/SETUP.md`。秘密はフロント/repo/ログに出さない(SHARED_SECRETのみフロント可＝ソフト鍵)。
1. FANZAアフィリンク生成機能を統合(タブ切替・純粋関数＋テスト)
2. プレビュー文字改善(「作者：」常時表示・黒帯はみ出し対策)
3. 基準座標系を **1080×1920** に統一(全パラメータ比率化／プレビュー＝書き出し一致)
4. 「全体の縦位置」スライダー追加
5. スマホで横潰れする不具合を修正(CSSの9:16固定崩れ／`?v=` キャッシュ対策)
6. スライダーの保存・既定値・リセット(汎用 `Store` ヘルパ)
7. 黒帯を3段別に独立制御
8. 文字も3段別に独立 ＝ 現在の7本構成
9. **Bluesky 自動投稿**を追加(完全クライアントサイド)。動画作成後に確認ダイアログ→**挿入した元写真**＋固定文＋提携文＋**生のアフィリンク(無改変)** を投稿
10. **投稿記録＆クリック集計**を追加。投稿後、共有URLを GAS Web App へ送信→Bitly短縮→Googleスプレッドシートに「題名(動画タイトル)/各URL/クリック数」を記録。クリック数＝**投稿短縮URLの開封数**(アフィリンクには介入しない設計)
13. **スケジュール統合 Phase1(v=13)**：投稿スケジュール最適化システムを **📅カレンダータブ**として統合(`schedule/` に配置し **iframe** 埋め込み＝CSS/JS衝突回避・既存機能は回帰ゼロ)。同一オリジンで localStorage 共有。タブは 🎬動画作成／📅カレンダー／🦋投稿／🔗アフィリンク(🧪検証はカレンダー内)。設計書＝`5秒動画タイムスケジュール/docs/統合設計書_動画メーカー×スケジュール.md`。
17. **Phase5 無人予約投稿(v=19)**：GAS拡張で**タブを閉じても**予約時刻に自動投稿。クライアントの「⏰予約」に**☁️無人トグル**追加→GASへ `type:'reserve'`(本文＝固定文＋自動アフィリンク／画像base64)送信。GAS側 `runReservations`(5分トリガー)が「予約」シートのpendingを `bskyPost_`(createSession→uploadBlob→createRecord・facet)で投稿、画像はDrive一時保存→投稿後ゴミ箱。投稿アカウントはGASプロパティ `BSKY_HANDLE/BSKY_APP_PW`。無人OFFは従来の端末タイマー(Phase3)。
(v17=iPhone UI改善 / v18=投稿UI刷新：本文固定文＋アフィリンク自動付与・実アバター取得・編集確認モーダル)
16. **スケジュール統合 Phase4 検証ダッシュボード(v=16)**：🧪検証タブを追加。共有ストア(`sch_state_v1`)の「公開済」投稿を一覧し、**Bluesky公開API(`public.api.bsky.app` getPosts・未認証・CORS)で いいね/リポスト/返信** を取得＋**Bitlyクリック(slot.click_count)**＋**FANZA成約(手入力・localStorage `verify_fanza`)** を day-type 別に集計。純粋関数 `verify-core.js`(`buildGetPostsUrl`/`parseEngagement`/`postedSlotsFromState`)＝`tests/test_verify.js` 5項目。検証KPIをYouTube前提→Bluesky指標へ再定義(設計書§6.4)。
15. **スケジュール統合 Phase3 予約投稿(v=15)**：`scheduler.js` を追加。🦋投稿タブに **⏰予約投稿**(datetime＋予約ボタン＋予約中リスト)。30秒ごとの tick で期限到来(pending かつ scheduledAtMs≤now)の予約を `BlueskyCore.blueskyPostRaw` で自動投稿→`bluesky-posted`(slotId付)発火→`integration.js`がスロット書き戻し＋ブラウザ通知。**このタブを開いている間のみ**(画像等はin-memory／無人化はPhase5のcronで対応)。`dueItems` は純粋関数でNodeテスト可(`tests/test_scheduler.js` 3項目)。📅から来た場合は枠の予定時刻をプリフィル。
14. **スケジュール統合 Phase2 一気通貫(v=14)**：カレンダーのスロット編集に「🎬この枠で動画を作る／🦋この枠を投稿する」を追加→`postMessage`で親へ(`schedule/js/app.js`)。親は `integration.js` で受けて該当タブへ切替＋**対象スロットのバナー表示**(`#slotCtxMovie/#slotCtxPost`)。投稿成功で `bluesky.js` が `bluesky-posted` を発火→`integration.js`がiframeへ`slot-writeback`→スロットを **公開済＋URL** に更新。橋渡しは postMessage＋同一オリジンlocalStorage。次：Phase3 予約投稿／Phase4 Bluesky用検証KPI。
12. **3タブ統合(v=12)**：1ページに **🎬動画作成／🦋投稿／🔗アフィリンク** の3タブ。投稿手段は2つ＝**①動画作成後の自動投稿**(`#bskyEnable`／本文＋動画の元写真)と **②単独で今すぐ投稿**(🦋投稿タブの `#postNowBtn`／本文＋任意画像 `#postImg`)。本文 `#bskyText`・アカウント設定は両手段で共通。🦋投稿タブに **Bluesky風ライブプレビュー**(このまま投稿される見た目)。タブ切替は `affiliate.js` の `TABS`。`post.html` は単独ページとして残置(同等機能)。
11. **UI再設計(v=11)**：①位置調整を**スライダー→＋/−ボタン**化し、プレビュー横(スマホは sticky)で見ながら微調整。②**黒帯の余白**(`OFF.bandPad`)と**段の間隔**(`OFF.rowGap`)を追加(計9コントロール)。③Bluesky投稿欄を**1つの自由テキスト本文(`bskyText`)に統合**(固定文/提携文/作品URL欄を廃止)。本文中のURLは `detectFacets` で自動リンク化(facetのindexは**UTF-8バイトオフセット**)。★アフィリンクは編集中は生表示だが**投稿直前に短縮へ差し替わる**(2026-07-20訂正)。④アプリパスワード等は折りたたみ＝任意(未入力なら投稿スキップ)

---

## 2. ファイル構成

| ファイル | 役割 | 触ってよいか |
|---|---|---|
| `core/util.js` | **共通土台(Go5Util)**：`$`/`esc`(必ず`"`をエスケープ)/`fmtTs`/`fmtWhen`/`yen`/`num`/`lsGet`/`lsSet`/`jsonp`/`copyText`。window＋module.exports両対応 | 共通ヘルパ統一時 |
| `core/account.js` | **アカウント解決(Go5Acct)**：`current()`/`key(base,acc)`/`handleOf`/`didOf`/`setDid`/`onChange`。**`current_account`直読み・`acc1`フォールバックはここ1箇所だけ** | アカウント解決の変更時 |
| `core/storage-keys.js` | **localStorageキーの登録制レジストリ(Go5Keys)**：`isSecret`/`syncAllowed`(許可リスト)/`classify`/`legacySynced`。**クラウド同期は許可リスト方式**(新キーは既定で同期しない＝INC-62恒久対策・改善書§2-4) | 新キー追加時は分類を登録 |
| `index.html` | 画面(動画作成タブ＋アフィリンクタブ＋7スライダー)。script読み込みは **core層→機能層** の順 | UI追加時 |
| `app.js` | ★中核：Canvas合成・テキスト描画・録画・スライダー配線 | 描画/座標の変更はここ |
| `style.css` | スマホ向けスタイル(ダークUI・タブ・スライダー群) | |
| `affiliate-core.js` | アフィリンク生成の**純粋関数** `buildAffiliateLink()` | 仕様変更時のみ |
| `affiliate.js` | アフィリンク画面のUI配線(入力・コピー・永続化) | |
| `bluesky-core.js` | Bluesky 投稿コア。**純粋関数** `buildBlueskyPost()`(本文＋リンクfacet)＋ `blueskyPostWithImage()`(ログイン→画像アップロード→投稿) | 仕様変更時のみ |
| `bluesky.js` | Bluesky 設定UIの配線・確認ダイアログ・**元写真**のJPEG圧縮(1MB制限対応)・投稿後に GAS へ記録送信。`video-created` イベントを購読 | |
| `gas/コード.gs` | **サーバーレス(Google Apps Script)**。投稿記録をスプレッドシートへ追記、`refreshClicks` で毎時クリック数更新(★Bitlyは全廃・短縮はクライアント側/自前worker)。本体とは別デプロイ | 仕様変更時 |
| `gas/セットアップ手順.md` | Bitlyトークン・Sheet・GASデプロイの手順書 | |
| `assets/bg_main.mp4` | 背景動画 | 差し替え可 |
| `tests/test_affiliate.js` | Node テスト(T-1〜T-4＋エッジ) | |
| `tests/test_bluesky.js` | Node テスト(`buildBlueskyPost` の facet バイトオフセット検証) | |
| `docs/設計・調査/設計書_スマホ版.md` / `docs/設計・調査/改修設計書_スマホ版完全版.md` | 設計・保守ドキュメント(2026-07-17にルート直下から移動) | |

---

## 3. 座標系の規約(最重要・崩さない)

- 基準フレーム **`W=1080, H=1920`(9:16)が唯一の基準座標系**。`index.html` の `<canvas width height>` も一致させる。
- 位置・フォントサイズは `H×係数` / `W×係数`。旧来の絶対px定数は **`U(v)=v*H/1280`** で基準フレームに換算。
- プレビューも書き出しも**同一Canvasに同じ式で描画** → PC/スマホ/書き出しで一致(CSSは9:16を一様縮小表示するだけ)。
- 縦オフセットは `OFF` オブジェクトで一元管理：
  - `OFF.whole`(全体)／`OFF.textAuthor/textDetail/textTitle`(各段の位置＝帯＋文字を一体で動かす)。
  - **段別オフセットは描画位置にのみ加算し、段の送りY(次段位置)には反映しない**＝他段に波及しない。
  - **帯は各段のテキストに統合**＝帯と文字は常に同じオフセットで一緒に動く(★旧・帯独立軸 `OFF.bandAuthor/bandDetail/bandTitle` は廃止・2026-07-07。「帯だけ」を別に動かすことはできない)。
- `document.fonts.ready` 後に再描画(フォールバックフォント計測由来のズレ防止)。

### localStorage キー
`preview_offset_y`(全体)／`preview_text_author|detail|title`、各 `*_default`(既定値)。2行モード＝`movie_author_two_line`/`movie_two_line`。旧キー `v_offset`・`preview_band_y`・`preview_band_author|detail|title` は退役(読まれない)。

### キャッシュ運用
`index.html` のアセット参照は `app.js?v=N` の形。**中身を変えたら `N` を1つ上げる**とスマホで確実に最新が読まれる(現在 v=12)。

### Bluesky 投稿(§9 機能)の要点
- 完全クライアントサイド。`https://bsky.social` の XRPC を直接叩く(CORS対応・サーバー不要)。認証は**アプリパスワード**(通常PWではない／revoke 可能)。
- フロー：`app.js` の `make()` 成功時に `video-created` を dispatch → `bluesky.js` が購読 → 確認ダイアログ → `#cv` の最終フレームを JPEG 圧縮(≤約950KB)→ `blueskyPostWithImage()`。
- 画像 embed(`app.bsky.embed.images`)と外部リンクカードは併用不可のため、**作品URLは本文に richtext#link facet 付きで入れる**(facet の index は **UTF-8 バイトオフセット**)。
- 設定の localStorage キー：`bsky_enable` / `bsky_text`(本文1ボックス) / `bsky_handle` / `bsky_app_pw` / `bsky_gas_url` / `bsky_gas_secret`。位置調整は `preview_*`(`preview_band_pad`・`preview_row_gap` を追加)。
- 投稿は `BlueskyCore.blueskyPostRaw({identifier,appPassword,text,imageBlob,alt})`＝本文そのまま投稿＋`detectFacets` で本文中URLを自動リンク化。旧 `buildBlueskyPost`/`blueskyPostWithImage` も残置(互換・テスト用)。
- 秘匿情報(アプリパスワード・af_id・シークレット)は **console に出さない**(既存方針を踏襲)。

### 投稿記録＆クリック集計(§10 機能)の要点
- **クリック数＝投稿の短縮URLの開封数**(★Bitlyは全廃・現在は自前 link-worker＝2026-07-20確認)。本文の作品リンク/セール会場リンクは**どちらも最終投稿時には短縮リンク**(★旧記述「生のまま(無改変)」は誤り)。作品リンクは編集中は生アフィリンク表示だが、**投稿直前に `measureWorkLink_` が短縮へ差し替える**(今すぐ/予約/無人予約/動画後自動の全経路)。短縮は302素通し(Locationに完全URL)なので **af_id は保持され計測は壊れない**。アフィリンクのクリック実数は取得不可(FANZA 管理画面が正)。
- 投稿の共有URLは `at://…/<rkey>` から `https://bsky.app/profile/<handle>/post/<rkey>` を組み立て(`bluesky-core.js`)。
- クライアントは GAS Web App へ `{channel,title,postUrl,affiliateUrl,workUrl,hashtags,postUri}` を **Content-Type無指定の POST**(＝simple request でプリフライト回避)。★共有URLの短縮は**クライアント側**(`shortenAndShow`→`makeShortAndShare`)が投稿直後に行い、GASへは**短縮済みの値**を送る。GASはシート追記が主で、短縮値が来なかった時だけ `daGdShorten_()`(da.gdのみ)でフォールバック短縮する副経路が残る。
- **記録は2チャンネル別シート**：GAS(`gas/コード.gs` v2)が `channel`(acc1/acc2)に応じて **`記録_ch1`/`記録_ch2`** へ**列名マッピング**で自動記入(記録先は「動画記録分析テンプレート.xlsx」を取り込んだスプレッドシート前提＝`設定`/`Holidays`/`集計` 含む)。`refreshClicks`(Bitly)＋`refreshEngagement`(Bluesky公開API いいね/リポスト/返信)を毎時更新。分析テンプレ＝プロジェクト直下 `記録分析テンプレート/`。
- ★**Bitlyは全廃**(`gas/コード.gs` 冒頭コメントに明記)。短縮は自前 Cloudflare Worker(`link-worker`)＝**チャンネル別独自ドメイン**(月詠み `5mgl.com` / 宵桜艶帖 `yoz2.com`)。Worker失敗時のみ da.gd→TinyURL へフォールバック、全滅時は元URLのまま。シートの「Bitly_ID」「Bitlyクリック」列名は互換のため残置だが、中身は **link-worker の開封数**。
- X(旧Twitter)はこの構成では不可(OAuth＋サーバー必須・直投稿はCORS不可)。

---

## 4. ビルド・テスト・公開

- ビルド不要(素のHTML/JS)。ローカル確認：`python3 -m http.server 8000` → `http://localhost:8000/`
- テスト：`node tests/test_affiliate.js`(全PASSを確認)
- 公開(GitHub Pagesへ反映)：
  ```bash
  git add -A && git commit -m "変更内容" && git push
  # 1〜2分で公開URLに自動反映
  ```
  push認証：GitHubユーザー名＋Personal Access Token(リモートURLにトークンを埋め込まない)。

### GAS(コード.gs)の反映(自動化済み・手動コピペ禁止)

- `gas/コード.gs` を編集したら**必ず `GAS_VERSION` をバンプ**する(日付＋英字サフィックス。例 `2026-07-02H`)。
- 反映は **`GASを反映.bat`(＝`node scripts/deploy_gas.mjs`)** を実行するだけ。
  clasp で push→**既存デプロイIDに新バージョンを当てる**ため **exec URL は不変**。
  `?ping=1` でバージョン一致を機械検証し、`?action=admin_setup` で**トリガー再設定＋ヘッダ移行**まで自動実行する。
  → GAS エディタへの手動コピペ・手動再デプロイは案内しない(初回だけ `GAS初期設定.bat`)。
- 反映前チェックだけしたい時は `node scripts/deploy_gas.mjs --check`。
- **`clasp pull` を `gas/` に対して実行しない**(ローカルが正。クラウド版で上書きされる)。
  設計・落とし穴の詳細は `docs/設計・調査/GAS自動反映_設計書.md`。
- 秘密(`.clasp.json` / `scripts/gas_deploy_config.json` / `~/.clasprc.json`)はコミット禁止。

---

## 5. 作業の進め方(モデル分業ポリシー)

メインセッション＝設計・計画・レビュー・統合に専念。実装の物量は Task ツールで**軽量モデル(例 sonnet)のサブエージェント**へ委譲する。委譲時は「目的・入力と出力・受け入れ条件」を明記。探索やログ調査などノイズの多い作業もサブへ寄せ、メインの文脈を設計判断のためにきれいに保つ。

### 5.1 モデル選択ガイド(このプロジェクトの費用対効果)

**既定は Sonnet**。次の「格上げトリガー」が出たときだけ Opus 4.8(最難関の真因追跡・設計・出荷前レビューは Fable 5)に上げる。体感 7〜8 割は Sonnet で十分。

| 作業の種類 | 例 | 推奨モデル |
|---|---|---|
| 見た目・文言の調整 | 配色/ボタン配置/タブ並べ替え/ラベル変更/版上げ＆反映 | **Sonnet** |
| 単一ファイルの素直な追加 | 表示欄・バッジ追加・CSS微調整・チェックボックス追加 | **Sonnet** |
| 原因が見えないバグ追跡 | 「直しても再発」/選んだ値と実際使う値のズレ/clasp .gs↔.js | **Opus / Fable** |
| データ・基盤に触る変更 | gas/コード.gs ロジック/Worker/GAS反映/記録の列・データモデル/非同期の順序 | **Opus / Fable** |
| 設計・レビュー | 設計書/インシデント.md の一般化/API制約の判断 | **Opus / Fable** |

**格上げトリガー(1つでも当てはまれば Opus/Fable)**
- 同じ不具合が直しても**再発**する(＝真因が別にある)
- 変更が **gas/コード.gs・Worker・GAS反映・記録の列/データモデル・非同期/イベント順序** に触れる
- **複数ファイルにまたがる新機能**(CSSだけで終わらない)
- **設計書がほしい／出す前にレビューしたい**

**言い切れる見た目/文言 → Sonnet。見えないバグ・基盤・設計 → Opus/Fable。**

**モデルとは別の工数レバー(効きが大きい順)**
1. **インシデント.md を育て続ける**＝安いモデルが過去の穴を踏まなくなる土台(最重要)。
2. 反映(deploy)・記録・データに触る回は**出す前に自己レビュー1回**(過去、出荷前レビューが実際に複数のバグを捕捉)。
3. 調査・grep は**サブエージェント**へ(高いモデルの思考は「判断」に使う)。
4. 小さな修正は**まとめて1ターン**(版上げ・反映の往復を減らす)。

---

## 6. やってはいけない／注意

- 上記 §3 の比率ベース座標系を崩さない(px/vh/vw を直接使わない)。
- プレビューと書き出しは同一Canvas・同一描画式に保つ(一致が崩れる変更を避ける)。
- 変更後はアセットの `?v=` を上げる。
- アフィリンクのテンプレート変更は `affiliate-core.js` の `buildAffiliateLink()` 内のみで局所化する。
- **過去の失敗と汎用教訓は `インシデント.md` にまとまっている。** 設計・実装・デプロイの前に
  該当カテゴリ(§3 A〜F)を一読する。不具合を直したら同ファイルに追記する。
- **「よくあるClaudeの紫デザイン」を使わない(恒久ルール)。** モーダル・オーバーレイ・ボタン等の
  新規UIは `#5b3f8e/#2a1a4e/#1a1a2e/#d4b3ff/#c4a0ff` 等の紫を使わず、アプリ配色
  (ダーク面 `--card`/`#0e1422`・アクセント `--accent`(#2bb3c0 ティール)・クリーム面 `#fffdf6`)に合わせる。
  ※アカウントテーマの紫(月詠み=#241a3d 等)は別枠でOK。ユーザー指示 2026-07-03。

### 6.1 規約防衛(P0・最優先／チャンネル喪失＝全施策が無意味になるのを防ぐ)

> 出典・背景は `docs/設計・調査/改善書_Shorts攻略と全体改善ロードマップ.md` §3(P0)。運用ルールなのでコード変更ゼロで今日から守る。**再生数施策より先。**

- **FANZA直リンクを YouTube 説明欄・固定コメントに絶対に貼らない。** 正は現行の `YouTube → 短縮URL(r2/da.gd) → Bluesky投稿 → FANZA` の2段クッション構造。生アフィリンクが出てよいのは Bluesky 投稿本文のみ。
- **煽り文言を書かない。** 「YouTubeでは見せられない続きは…」型の誘導は外部リンクポリシーで名指しの違反パターン。題名・説明欄・コメントに書かない。
- **1コマ目・サムネ・全コマの露出基準＝「電車内で見られて困らないコマだけ使う」。** 性的示唆(挑発ポーズ・下着相当露出)は年齢制限→Shortsフィード配信が実質ゼロ(2025/8からAI年齢推定も稼働)＝除外と同義。投稿確認モーダルに注意書きあり(S-6)。
- **2チャンネル(acc1 月詠み／acc2 宵桜艶帖)へ同一動画をコピー投稿しない。** inauthentic/スパム判定(2025/7 収益化ポリシー)の火種。作品・コマ・文言を必ず変える。
- **音源は動画ファイルに焼き込まない。** BGMは YouTube アプリの Shorts エディタで「許可された音楽」を付けるのが正式運用(＝トレンド音源を合法に使える唯一の経路)。生成動画が無音なのは仕様。**将来もBGM焼き込み機能は作らない**(改善書 S-2 不採用)。
- **(Chami宿題・未調査)FANZA側規約の確認**：コマ画像の二次利用許諾範囲・複数コマ利用の可否。尺拡張ABは§1裁定で不採用のため急がないが、1コマ利用の規約確認は推奨。
