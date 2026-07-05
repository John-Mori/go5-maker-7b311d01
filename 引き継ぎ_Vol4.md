# 引き継ぎ — Vol.4 キックオフ（go5-maker）

> **新しいチャット(Vol.4)を始めたら、まずこのファイルを読む。**
> 一次情報は `CLAUDE.md`。インシデント台帳は `インシデント.md`（巻をまたぐ通し番号）。中期計画は `docs/設計・調査/改善書_Shorts攻略と全体改善ロードマップ.md`。
> このファイルは「Vol.3 の到達点」と「Vol.4 でやること」を1枚にまとめた俯瞰図。食い違いは実コード＋`CLAUDE.md` が優先。

最終更新: 2026-07-05 ／ 巻の切り替え: **Vol.3 → Vol.4**

---

## 0. 現在の到達点（このファイル作成時点）

| 項目 | 状態 |
|---|---|
| 公開バージョン(live) | **`?v=203`**（`https://john-mori.github.io/go5-maker-7b311d01/`）※Phase 0=v201/202・Phase 1=v203 |
| GAS_VERSION | **`2026-07-05H`**（D-1・**live反映済み** 2026-07-05・`?ping=1`照合済・記録シートに ハッシュタグ/リビルド元ID/タイトル文字数 列追加済） |
| ブランチ / 作業ツリー | `main` |
| 直近コミット | Phase 1（S-1a/D-1/U-2/S-3=v203） |

### ✅ Phase 1 実装（2026-07-05・改善書 §8 Phase 1）— フロントは live 反映済み(v203)
- **S-1a 背景シームレス化**：acc2 `bg_account2.mp4` を5.0sシームレスループへ差し替え（ループ継ぎ目 PSNR 21.2→27.0dB＝隣接フレーム同等）。acc1 `bg_main.mp4` は元々シームレス（継ぎ目26.6>隣接19.9dB）で**無改変**。app.js の acc2 bg に `?v=203` キャッシュバスト付与（背景mp4は通常 ?v 無し）。演出コードは不変。
- **U-2 候補から一気に作成**：`candidates.js` の `transferToMovie_` 後に `#makeBtn` へスクロール＋フォーカス＋パルス強調（`.cta-ready-pulse`）＝候補→作成が残り1タップ。**カード直下の⚡ボタン（モーダルを介さない版）は未実装**（カードごとの画像/コメント/URL収集が要り candidates.js が複雑なため follow-up）。
- **S-3 メタデータ**：`buildTitle` にタグ数ガードレール（3〜5推奨・15超で全無効を警告・#Shorts推奨・`#ytTagWarn` に表示）。既定タグを `#Shorts #マンガ #漫画紹介 #anime` に。**非破壊**（ユーザーのタグは書き換えない）。2ch別文言は既存の per-account テンプレ（yt_tags__/bsky_text__）で構造的に対応済。
- **✅ D-1（記録取りこぼし回収）＝GAS反映済み**（`2026-07-05H`・2026-07-05 デプロイ・`?ping=1`でH確認・列追加migrate完了）：hashtags/リビルド元ID/タイトル文字数を記録・予約経由(無人)投稿へ videoId/カテゴリ/作品状態/リビルド元 を中継。以後の新規投稿から新列が埋まる（既存行は不変・タイトル文字数は書込時に式付与）。
- **ベースライン（Studio目視）＝Chami運用**（swipe率・フィード表示回数・年齢制限有無を記録）。改善書§9。

### 次にやること
- **最優先＝D-1 の GAS デプロイ**（上記）。その後 Phase 2（D-5 Analytics API＝ChamiのOAuth/高度なサービス設定要／D-2 実売数シート合流＝D-1後／U-1 カテゴリ自動リセット／U-4 YouTube共有ボタン／U-3 カウントダウン投稿／D-3 Looker＋週次／D-4 bucket_snapsサーバー移行）。

### ✅ Phase 0 完了（2026-07-05・改善書 §8 Phase 0）
- **P0（規約防衛の明文化）**：`CLAUDE.md §6.1` に FANZA直リンク禁止／煽り文言禁止／1コマ目露出基準／2ch同一動画禁止／BGM焼込禁止／FANZA規約確認(宿題) を記載。
- **S-6**：投稿確認モーダルに「1コマ目・サムネは全年齢で大丈夫？」注意書き（`index.html`/`style.css` の `.pc-agecheck`・アンバー・タップ増なし）。
- **U-7**：`wizard.js` の `video-created`/`bluesky-posted` 購読を `window`→`document` に修正（発火が document・bubbles無しで届いておらずウィザード自動進行が不達だった）。
- **M-1（共通コア3ファイル＋sync許可リスト反転）**：`core/util.js`(Go5Util)／`core/account.js`(Go5Acct)／`core/storage-keys.js`(Go5Keys) を新設。**クラウド同期をブロックリスト→許可リスト方式へ反転**（`settings-io.js`）＝未登録の新キーは既定で同期されない（INC-62恒久対策）。危険な `esc`（`"`非エスケープ）3系統を安全版に統一（`bluesky.js`/`scheduler.js`/`api-diag.js`）。`tests/test_storage_keys.js`(9 PASS)＋既存62テスト回帰なし。
  - **⚠ 残りの受け入れ確認（Chami・目視）**：詳細設定→「クラウドに保存」を押すと**コンソールに『同期されなくなるキー一覧』**が1度出る（`[go5 sync反転]`）。想定＝`movie_drafts__`/`sch_state_v1`/`view_snaps`/`yt_scheduled__`/`current_account`/`verify_fanza`/`field_*`/`rank_mode`/移行フラグ 等（＝改善書§2-4の漏洩キー）。**本物の設定が混じっていなければOK**（検証済みの想定リストと一致）。
  - **M-1の残タスク（M-2送り）**：各ファイルの `$`/`esc`/`lsGet`/`fmtTs`/アカウント直読みの**呼び出し側**を core へ寄せる機械的置換は、神ファイル分割(M-2)で1ファイルずつ実施（§7準拠・今回は土台作成と最重要配線＝sync反転・esc安全化に限定）。
| 現行ソースの場所 | **`D:\SougouStartFolder\go5-maker`**（旧 Desktop\go5-maker から移設済み。D:ドライブの `スマホ版` フォルダは無関係な古いコピー） |
| デプロイ | GitHub Pages（`.nojekyll`＝INC-66）。反映確認は `curl .../index.html?cb=<ts> \| grep 'candidates.js?v='` |

**機密ファイル（絶対にコミットしない）**：`scripts/scrape_config.json` / `scripts/gas_deploy_config.json` は `.gitignore` 済。追跡は `*.example.json` のみ。

---

## 1. Vol.3 でやったこと（v193 → v200 の要約）

一次の詳細は各コミットメッセージ。大きな塊：

1. **🦋 バズタブ新設(v193)**：候補タブ左端の固定タブ。月詠み/宵桜がフォローするBlueskyアカウントの投稿をエンゲージメント（like+repost+reply+quote）降順で表示。Bluesky公開API(未認証・CORS)のみ。`candidates.js` の `renderBuzz` 一式＋`style.css .buzz-*`。後に `jp.bsky.app`/`bsky.app` を除外(v198)。

2. **💡候補タブ改修(v194〜v200)**：既定ソート=**追加日が新しい順**(v194)／「🖼投稿画像」ボタン→「🖼投稿編集」に改名・モーダルをX起点/DMM起点で統一(v194-196)／モーダル刷新＝絵文字削除・白地黒字・**「動画生成へ」導線**(作品データを動画作成タブへ転送)・「消す」に確認ポップアップ(v195)／貼り付けボタンの幅崩れ修正・案内文一行化(v196)／**セール中のみ表示フィルタ＋Books/同人・AI種別バッジ**(v198)／作品サムネの下に**保存済み動画生成用画像を表示＋タップで拡大**(v199)。

3. **🔁リビルド機能(v198, v200)**：動画作成タブの「リビルド」チェック→投稿履歴からリビルド対象を選ぶピッカー。選ぶと**その作品のURL・作者名(サークル名)・投稿バージョンURL(アフィID入り)・割引・FANZA作品情報・作品状態(新作/準新作)を自動反映**。投稿すると対象に「被リビルド」印を自動付与。**原因調査**：ピッカーが投稿履歴と食い違っていた根因＝`listForRebuildPicker_` が `ensureIds()` 未呼び出しでID未付与の履歴が欠落＋題名が記録タイトル固定→YouTubeタイトル優先解決に統一＋日付ラベル付与で解消(v200)。投稿履歴タブに「被リビルドを非表示」トグルも追加(v198)。

4. **⏰予約タブ**：現在時刻が予約時間を過ぎたアイテムを表示時点で除外(v198)。

5. **⚙️設定の移動＋PC運用(v197, v199)**：「☁️端末間クラウド同期」「⚙️設定の引っ越し(書出/読込)」の2セクションを🦋投稿タブ→**詳細設定タブ**へ移設(v197)。販売数の15分自動取得タスクが黒いターミナル窓を出す問題を、**wscript経由の非表示VBScriptランチャ**(`scripts/sales_poll_hidden.vbs`)で解消・既存タスク再登録済み(v199)。

6. **📘 改善ロードマップ策定(ドキュメント)**：`docs/設計・調査/改善書_Shorts攻略と全体改善ロードマップ.md`。→ §2 が Vol.4 の本題。

補足：**動画作成後の自動投稿は、画像未添付なら動画の元写真(photoFile)を添付する実装**であることを確認済み（要望は既存実装で満たされていた）。

---

## 2. Vol.4 でやること＝改善書 Phase 0 → Phase 1（本題）

**正本＝`docs/設計・調査/改善書_Shorts攻略と全体改善ロードマップ.md`**（4本柱＝①作りやすさ②データ分析③保守性④Shortsフィード攻略。Phase 0〜4のタスク表に触るファイル・受け入れ条件・Opus/Sonnet割当あり）。

### 2-0. 確定済みの前提（勝手に覆さない・2026-07-05 Chami裁定）
- **主要KPI＝engagedViews**（views/クリック/FANZA報酬は副KPI）。AB判定は engagedViews 中央値。
- **「1コマを5秒で」はコンサル指導の実証済み手法で不変**（同手法のコンサル生が月90万突破）。尺拡張・構成の独自最適化はしない。Chamiの課題認識＝**行動量とコツ掴み不足**なので、改善書の重心は「量産支援」と「振り返り分析」。
- **前景のフェードイン演出はコンサル指定＝不変**。**前景の見た目・演出に触るタスクは提案自体しない**（S-1b恒久不採用）。
- **音源はYouTubeアプリのShortsエディタで付与するのが正**（＝トレンド音源を使える唯一の合法経路）。動画への**BGM焼き込みは作らない**（S-2不採用）。音源リマインド/記録列も不要（S-2'不採用）。
- **Data API監査は申請する**（承認まで数週〜数ヶ月・承認前はアップロード自動化しない）。

### 2-1. Phase 0（土台・最初に）
| ID | タスク | 触る | 受け入れ条件 | モデル |
|---|---|---|---|---|
| P0 | 規約防衛ルールをCLAUDE.md §6に明文化（FANZA直リンク禁止／際どいコマを1コマ目・サムネにしない／2chへ同一動画コピー投稿禁止／煽り文言禁止） | CLAUDE.md | ルールが「やってはいけない」に載る | Sonnet |
| S-6 | 投稿確認モーダルに「1コマ目は全年齢で大丈夫？」の一行 | bluesky.js | 表示・タップ増なし | Sonnet |
| U-7 | **wizardイベント不達バグ修正**：wizard.js:395,427 の `window.addEventListener('video-created'/'bluesky-posted')` を `document` に（発火が document・bubbles無しで window に届いていない） | wizard.js | ウィザード②→③が動画作成後に自動進行(実機) | Sonnet |
| M-1 | **共通コア3ファイル＋sync許可リスト反転**：`core/util.js`(Go5Util・esc等を`"`エスケープ1系統に統一)／`core/account.js`(Go5Acct・`current_account`直読み禁止)／`core/storage-keys.js`(Go5Keys・全キー登録制→**クラウド同期を許可リスト方式へ反転**)。INC-62型事故の恒久防止 | 新core/*＋settings-io.js等 | 重複ヘルパ置換後に全機能回帰なし／test_storage_keys.js PASS／同期差分ログ目視 | **Opus** |

### 2-2. Phase 1（即効打＋量産支援）
| ID | タスク | 触る | 受け入れ条件 | モデル |
|---|---|---|---|---|
| S-1a | 背景を**ちょうど5.0秒のシームレスループ素材**に差し替え（**演出コードには触れない・素材のみ**。PC側 `loopify.py`）。5秒維持ならループ数が生命線 | assets/ | ループ境界の飛びが目視で見えない・演出完全不変 | Sonnet |
| D-1 | **記録の取りこぼし回収**：hashtags(受信してるのに破棄)・rebuildOf(送ってるのにdoPostが読まない)・予約経由投稿のvideoId/カテゴリ/workState中継。GAS列追加＋writeRecord_数行 | gas/コード.gs, bluesky.js | 新規投稿行にhashtags/rebuildOfが入る・既存行不変 | **Opus** |
| S-3 | メタデータ整備：ハッシュタグ3〜5個(15個超で全無効)・題名にジャンル語・2ch別文言・投稿は夕方/金曜厚め | bluesky.js, schedule/ | 生成タグ3〜5・2ch別文言 | Sonnet |
| U-2 | **候補から一気に作成**（行動量の主戦場）：候補カードに「⚡一気に作成」→transferToMovie_→タブ切替→作成ボタンfocus/カウントダウンまで | candidates.js | 候補→作成まで残り1タップ | Sonnet |
| ベースライン | Studio目視の初回棚卸し（swipe率・フィード表示回数・年齢制限の有無を記録） | 運用 | §9のベースライン表が埋まる | Chami |

### 2-3. Phase 2以降（改善書§8参照）
Analytics API(engagedViews/維持率の自動記録・D-5)→実売数シート合流(D-2)→Looker Studio+週次メール(D-3)→bucket_snapsサーバー移行(D-4)→YouTube共有ボタン(U-4)→カテゴリ自動リセット(U-1)→カウントダウン投稿(U-3)。Phase 3=API監査承認後のアップロード自動化・バッチ生成(U-6)・WebCodecs(U-5・優先度低)。Phase 4=神ファイル分割(M-2)・GAS分割(M-3)・イベント規約(M-4)・テスト追加(M-6)。

---

## 3. 反映・運用のルール（Vol.4でも厳守）

- **フロント変更後は `index.html` の `?v=N` を必ず上げる**（48箇所一括。PowerShellで UTF-8 no-BOM の ReadAllText→replace→WriteAllText）。次の変更から **`?v=201`**。
- **GAS変更後は `GAS_VERSION` を上げてから** `node scripts/deploy_gas.mjs`。反映確認は `?ping=1`。clasp の `.gs`/`.js` 取り違えに注意。
- **デプロイ確認は必ずlive照合**：`curl .../index.html?cb=<ts>`。GitHub Pagesは稀に一時失敗／古いコミットで `building` のまま止まることがある → `gh api -X POST repos/John-Mori/go5-maker-7b311d01/pages/builds` で新規ビルドを明示要求（Vol.3で実際に発生・この方法で解決）。`.nojekyll` は消さない。
- **実装完了後は `git commit && git push` まで**やる。コミット末尾に `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`。
- **配色ルール**：Claude風の紫UI（#5b3f8e系）は禁止。アカウントテーマ配色（acc1=宵藍系 / acc2=葡萄梅系）に合わせる。
- **Python は `py -3.12`**（bare `python` は 3.14）。
- **不変条件**：比率座標系（W=1080/H=1920）・**前景の見た目/演出**（コンサル手法）・drive-worker非破壊・link-worker `u:<code>`不変・GASの`SHARED_SECRET`未設定・秘密はSecrets/Propertiesのみ。

---

## 4. 一次情報・参照先

| 目的 | ファイル |
|---|---|
| 公式コンテキスト（最新仕様） | `CLAUDE.md` |
| **中期計画（Vol.4の本題）** | `docs/設計・調査/改善書_Shorts攻略と全体改善ロードマップ.md` |
| ミス台帳（巻またぎ・INC通し番号） | `インシデント.md` |
| 前巻キックオフ（Vol.3の詳細） | `引き継ぎ_Vol3.md` |
| アカウント混在の恒久対策 設計 | `設計_投稿履歴アカウント混在の恒久対策.md` |
| GAS自動反映 設計 | `docs/設計・調査/GAS自動反映_設計書.md` |
