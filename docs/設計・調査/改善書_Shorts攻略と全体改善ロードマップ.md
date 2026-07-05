# 改善書 — YouTube Shorts攻略と全体改善ロードマップ

作成: 2026-07-05（Vol.3）／基準コード: v200（commit `631be4b`）／行番号はすべてこの時点のもの
調査手法: 並列調査4本（ファイル構成・データ基盤・作成UX・Shorts攻略Web調査）＋相互批評1本の統合

> **この文書の使い方**: 実装は Opus / Sonnet のセッションが1タスクずつ行う。各タスクは §8 のロードマップ表に「触るファイル・受け入れ条件・推奨モデル・依存」つきで定義してある。着手前に §1 の裁定事項を Chami に確認すること。**§3(P0) は最優先で、他の全施策より先に完了させる。**

## 目標（4本柱）

| # | 目標 | 対応節 |
|---|---|---|
| ① | 5秒動画をより作りやすく | §5 |
| ② | データ分析ができるように | §6 |
| ③ | メンテナンス性の向上 | §7 |
| ④ | **YouTube Shortsのフィードに乗せて再生数を稼ぐ（最重要）** | §3・§4・§9 |

---

## 1. 裁定4項目 → ✅ 全て決定済み（2026-07-05 Chami裁定）

| # | 項目 | 決定 | 影響 |
|---|---|---|---|
| 1 | 主要KPI | **engagedViews**（views/クリック/FANZA報酬は副KPI） | §9の全AB判定は engagedViews 中央値で行う。D-5（Analytics API）の優先度が上がる |
| 2 | 尺の方針 | **5秒維持**（ABなし・ループ数で勝負） | **S-4（尺拡張AB）は不採用**。U-5（WebCodecs）は「フレーム厳密ループ＋バッチ生成」目的のみに縮小＝優先度低。P0-5（FANZA複数コマ許諾）は不要に（1コマ利用の規約確認は引き続き推奨）。**S-1a（背景の完全ループ化）の重要度がさらに上がる**（5秒はループ数が生命線） |
| 3 | Data API監査申請 | **申請する** | 早期にフォーム提出（無料・審査数週〜数ヶ月）。承認まではU-4（共有シート最適化）で運用、承認後にアップロード自動化（Phase 3） |
| 4 | リファクタ時期 | **Phase 0で先行**（M-1のみ） | S-1/S-2より前に共通コア3ファイル＋sync許可リスト反転を実施。大分割（M-2）は従来通り機能の谷間に段階実施 |

> 参考（裁定時の判断材料）: viewsは2025/3以降ループ毎+1で稼ぎやすいが収益非直結。10.8万本分析の中央値ビュー最大は11〜20秒帯だが、5秒維持を選択＝プロダクトのコンセプトとループ戦略を優先。APIクォータは2025/12改定で緩和済み（1日100本相当）で、残る壁は未監査privateロックのみ。

### 追加の前提（2026-07-05 Chami・この改善書の解釈を規定する）

1. **「1コマを5秒で」はコンサル指導の実証済み手法であり不変の制約**。同手法の他のコンサル生が月90万円を突破している。尺・構成のアルゴリズム的最適化（§11の尺分析等）はこの制約の外では適用しない。
2. **Chamiの自己診断＝課題は「行動量」と「コツ掴み」の不足**。したがってこの改善書の重心は
   - **行動量** → §5（量産を楽にする: タップ削減・候補から一気に・バッチ生成）
   - **コツ掴み** → §6（どの作品/コマ/文言/音源/時間帯が伸びたかを振り返れるデータ基盤）
   に置く。アルゴリズム一般論の施策（§4）は「実証済み手法を邪魔しない範囲」でのみ適用する。
3. **BGMは動画ファイルに入れない**。YouTubeアプリのShortsエディタで「許可された音楽」を付けるのが主流運用であり、**これはライセンス上も唯一の合法ルート**（トレンド音源が使えるのはアプリ内追加だけ・§11出典）。生成動画が無音であることは問題ではなく仕様。リスクは「付け忘れ」のみ（→S-2'）。
4. 動画の演出（フェードイン等）はコンサル手法の一部である可能性があるため、**演出変更系タスクは着手前にコンサル手法との整合をChamiに確認**（S-1b）。

---

## 2. 現状分析の要点（事実・v200時点）

### 2-1. Shorts視点の現状（重大順・§1追加前提で解釈済み）
1. **音声はYouTubeアプリ側で付与する運用**（§1前提3）: 生成動画は無音（`app.js:365` 映像トラックのみ）だが、これは仕様であり問題ではない。実リスクは**音源の付け忘れ**（無音のまま公開するとフィードで不利）と、**どの音源で伸びたかが記録に残らない**こと。
2. **t=0で前景（マンガ）が透明**: `app.js:12` `REVEAL_START=0.5, REVEAL_DUR=2.0` のフェードインで、最初のフレームに商品が写っていない。スワイプ判断は冒頭0.5〜1秒で下されるため一般論ではフック上不利。**ただしフェード演出はコンサル手法の一部の可能性があるため、変更はChami確認待ち（S-1b）**。
3. **ループが切れる**: フェードのため最終フレーム≠先頭フレーム、かつ背景動画の5.00s地点が素材の切れ目と一致しない。ループ再生は2025/3以降 view+1 かつ推薦シグナル。**5秒維持の裁定によりループ数が生命線**であり、少なくとも背景のシームレス化（S-1a・演出不変）は安全に実施できる。
4. **同型量産リスク**: 全動画が同一テンプレ（同一背景・同一構図・同一文言パターン）。2025/7施行の「inauthentic content」ポリシーの典型例に該当し得る（収益化剥奪リスク）。1コマ目・文言・題名の差別化（P0-3）はコンサル手法と両立する範囲で行う。
5. **投稿手数の6〜7割がYouTube側**: 1本あたり合計27〜40タップのうち、カメラロール保存→YouTubeアプリ→題名/説明コピペ→URL戻しで約20タップ・アプリ切替3回。**「行動量」がボトルネックというChamiの自己診断に直結する改善領域**（§5）。

### 2-2. リンク構造（規約防衛の現状）
- YouTube説明欄には**FANZAリンクは入らない**。入るのは短縮URL（r2/da.gd）のみで、遷移先は**Bluesky投稿**（`bluesky.js:159-162` DEF_YTDESC・`putUrlTop` :619）。
- 生のFANZAアフィリンクがあるのはBluesky投稿本文のみ。つまり現行は `YouTube → 短縮URL → Bluesky投稿（クッション）→ FANZA` の2段構造で、**外部リンクポリシー（ポルノ直リンク禁止）に対して既に守りの形になっている**。
- 残余リスク: (a) クッションであるBluesky投稿自体に成人向け寄り画像＋生リンクがある、(b) 動画の1コマ目/内容が性的示唆と判定されると**年齢制限→フィード配信が実質ゼロ**（2025/8からAI年齢推定も稼働）。

### 2-3. データ基盤の現状
- 記録タブ（`月詠み`/`宵桜艶帖`・gas/コード.gs:75）には33+6+4列があり、**曜日/day-type/時間帯スロットはシート数式で自動**、視聴回数/クリック/いいね等は毎時トリガーで自動。**分析軸は列としてはかなり揃っている**。
- **取りこぼし（送っているのに捨てている）**: `hashtags` は doPost が受信するのに writeRecord_ が書かない（コード.gs:398 vs :467-548）。`rebuildOf` は bluesky.js:711 が送るのに doPost が読まない＝リビルド系譜が復元不能。予約経由投稿は videoId/カテゴリ/状態なしの薄い行になる（:1005-1009）。
- **実売数（fetch_sales.mjs→KV `sales:<cid>`）はシートに入らない**＝候補タブ表示専用。投稿→クリック→実売のファネルが繋がっていない。
- 手動でしか入らない列: インプレッション/CTR/**平均視聴維持率**/フォロー増/FANZA成約・報酬。維持率は **YouTube Analytics API（OAuth・無料）で自動化可能**（`averageViewPercentage`、engagedViews は2025/4からAPI提供）。Studio限定なのは「フィード表示回数」「Viewed vs swiped率」のみ。
- ランキングの経過時間バケット（30分/1h/…）は端末localStorage `view_snaps` 依存で「開いた時だけ観測」。一方サーバー側 `snapshot.gs` はティア別間隔で28日分の精密スナップを既に蓄積しているのに**UI未接続**。

### 2-4. 保守性の現状
- 神ファイル3本: yt-clicks.js 2166行（責務≒11）/ candidates.js 1504行（≒12）/ bluesky.js 1499行（≒15）。全部IIFE closure共有で部分修正の影響範囲が読めない。
- ヘルパ重複: `$`×10ファイル、`esc`×9（**`"`をエスケープしない危険な系統が bluesky.js:456/scheduler.js:35/api-diag.js:10 に混在**）、lsGet/lsSet系×6、fmtTs×4（仕様差あり）、JSONP×3、アカウント取得3方式（closure正本/window経由/**localStorage直読み**）。
- **クラウド同期がブロックリスト方式**（settings-io.js:24-29）: リストに無い新キーは自動的に同期対象＝ INC-62（アカウント混在）の恒久対策が新キーに効かない。現に `yt_scheduled__` `movie_drafts__`（画像dataURL入り）`sch_state_v1` `view_snaps` 等が漏れて同期対象になっている。
- **実バグ（確認済み）**: wizard.js:395,427 は `window.addEventListener('video-created'/'bluesky-posted')` だが、発火側（app.js:402・bluesky.js:734）は `document` に bubbles 無しで dispatch → **windowには届かない＝ウィザードの自動進行が機能していない**。
- テストは抽出済み純関数のみ7本。アカウント矯正・sync判定・GAS upsert 本体（ミラーのみで乖離検出不能）など、最も危険なコードが未テスト。

---

## 3. P0: 規約防衛（チャンネル喪失＝全施策無意味、を防ぐ）

> すべての再生数施策より先。運用ルールはコード変更ゼロで今日から効く。

- **P0-1. リンク構造の維持ルール明文化**: YouTube説明欄・固定コメントにFANZA直リンクを**絶対に貼らない**（現状の 短縮URL→Bluesky投稿 の2段構造を正とする）。「YouTubeでは見せられない続きは…」型の煽り文言も外部リンクポリシーで名指しの違反パターンなので禁止。
- **P0-2. 1コマ目・全コマの露出基準**: 性的示唆（挑発ポーズ・下着相当露出）は年齢制限→フィード除外と同義。**「電車内で見られて困らないコマだけ使う」**を作成時ルールにし、確認モーダルにチェック観点として一文入れる（実装は §8 S-6）。
- **P0-3. 2チャンネルへの同一動画コピー投稿の禁止**: inauthentic/スパム判定の火種。acc1/acc2では作品・コマ・文言を必ず変える。
- **P0-4. 音源の権利ルール**: 音源は**YouTubeアプリのShortsエディタで「許可された音楽」を付ける**（現行運用＝正式運用）。これはトレンド音源を合法に使える**唯一の経路**でもある。市販曲・トレンド音源を動画ファイルに焼き込むのは違法（Content IDクレーム/削除対象）なので、**将来もBGM焼き込み機能は作らない**（S-2は不採用）。
- **P0-5. FANZA側規約の確認（未調査・Chami宿題）**: マンガのコマ画像の二次利用許諾範囲、複数コマ利用（紙芝居化＝§1-2(b)）の可否。アフィリエイト規約とパッケージ画像利用規定を確認してから尺拡張ABに着手する。

---

## 4. P1: Shortsフィード攻略施策

### S-1a. 背景の完全ループ化（演出不変・安全に実施可）
- **内容**: 背景素材を**ちょうど5.0秒のシームレスループ版**に差し替え（PC側 `loopify.py` で作成可能。bg_main.mp4 自体がこの手法の産物）。前景・テキストの演出には一切触れない。
- 根拠: 5秒維持の裁定によりループ数が生命線（2025/3以降ループ毎view+1・推薦シグナル）。背景の切れ目はループ境界の違和感の一因。
- 受け入れ条件: ループ境界で背景の「飛び」が目視で見えない／座標系・演出・プレビュー一致は完全不変。

### S-1b. 冒頭フェードの見直し（⚠️着手前にChami確認必須）
- **前提**: フェードイン演出（`app.js:12` REVEAL_START=0.5/REVEAL_DUR=2.0）が**コンサル手法で指定された演出かどうかをChamiに確認**。指定演出なら本タスクは恒久不採用とする。
- 指定でない場合のみ: 「フェード無し（frame0から前景完全表示）」トグルを追加してAB比較（§9設計・engagedViews中央値で判定）。一般論ではスワイプ判断が下される冒頭0.5〜1秒に商品が写っている方が有利だが、**実証済み手法を上書きする根拠にはならない**ため必ずABで検証する。

### S-2. ~~BGM焼き込み~~ → 不採用（裁定：音源はYouTubeアプリ側で付与）
音源はYouTubeアプリのShortsエディタで「許可された音楽」を付けるのが主流かつ**ライセンス上唯一の合法経路**（トレンド音源が使えるのはアプリ内追加のみ）。動画ファイルへのBGM焼き込み機能は作らない（P0-4）。

### S-2'. 音源運用の支援（付け忘れ防止＋音源の勝ちパターン学習）
- **内容**: (a) YT投稿タブ（題名/説明欄コピーの画面）に「♪ 音源を付けたか」のリマインド一行を表示。(b) 記録シートの「BGM」列を「音源名」列として使い、YouTubeアプリで付けた音源名を記録できる入力欄を投稿履歴の編集モーダルに追加（任意入力）。
- 狙い: 「コツ掴み」の主要軸のひとつ＝**どのトレンド音源を付けた動画が伸びたか**を振り返れるようにする（現状は音源情報がどこにも残らない）。
- 受け入れ条件: リマインドが表示される／編集モーダルから音源名を保存すると記録シートの列に upsert される。

### S-3. メタデータ・運用整備（コード小・運用中心）
- ハッシュタグは**3〜5個**（#shorts＋ジャンル語＋作品固有）。15個超は全無効。YT題名生成（`buildTitle` bluesky.js:1460-1473）とYT説明欄テンプレに反映。
- タイトルに検索されうるジャンル語（例:「異世界」「OL」等、既存カテゴリと連動）を含める。
- 投稿時間: 視聴者ローカルの夕方〜夜・金曜厚め（Buffer 180万本分析）。scheduleタブのテンプレに反映（day-type別テンプレは既存 schedule_master.js）。
- 1コマ目・テキスト・題名は作品ごとに明確に変える（P0-3と同根・同型量産脱却）。
- 受け入れ条件: buildTitle/説明欄テンプレがタグ3〜5個で生成される／2アカウントのテンプレ文言が別物である。

### S-4. 尺11〜20秒版のABテスト（裁定§1-2・P0-5クリア後）
- 1ページを2〜3コマに分割し、コマごとにパン/ズーム（Ken Burns）で見せる「紙芝居モード」。5秒版と同一作品・同一時刻帯で成績比較（判定設計は§9）。
- 実装は現行 make() の拡張（DURATION可変化＋コマ配列＋タイムライン）だが、リアルタイム録画のままでは20秒拘束が痛いため、**この時点で WebCodecs オフラインレンダリング（§5-5）への移行判断を併せて行う**。

### S-5. 計測の自動化（§6 D-4/D-5 と同一。Shorts改善ループの燃料）
- Analytics API で views / engagedViews / averageViewPercentage を日次取得→シートupsert。`engagedViews ÷ views` を「引き込み率」としてカード/ランキングに表示。Studio限定の「フィード表示回数」「swiped率」は週1で目視棚卸し（§9のベースライン計測を兼ねる）。

### S-6. 確認モーダルに規約チェック観点を表示（P0-2の実装）
- 投稿確認モーダル（bluesky.js:1288-1333）に「1コマ目は全年齢で大丈夫？」の一行注意書きを追加。タップ増なし。

---

## 5. P2: 作りやすさ（タップ削減・自動化）

- **U-1. カテゴリ・リビルドの作成後自動リセット**: persist-fields が `movieAttr*` を復元するため前作のチェックが残り**誤記録の温床**（現バグに近い挙動）。`bluesky-posted` 後に movieAttr* 全OFF＋`field_movieAttr*` クリア（リビルドは実装済み bluesky.js:990-994 と同型に）。
- **U-2. 「候補から一気に作成」**: `transferToMovie_`（candidates.js:433-448）は既に写真/作者/コメント/URLを注入済み。候補カードに「⚡一気に作成」ボタンを追加し、転送→タブ切替→「▶作成」フォーカス（または自動実行前カウントダウン）まで詰める。手動経路の入力ほぼゼロ化。
- **U-3. 確認モーダルの「N秒後に自動投稿（キャンセル可）」トグル**: URL確定済み経路（候補転送/リビルド）限定でカウントダウン投稿。安全性（目視機会）は残しタップを削減。
- **U-4. YouTube投稿の短縮（短期・API不要）**: (a)「YouTubeへ共有」ボタン＝`navigator.share` に動画Fileを渡して共有シートから直接YouTubeアプリへ（カメラロール中継の削減）、(b) 共有直前に題名を自動でクリップボードへコピー、(c) 説明欄は既に短縮URL自動挿入済みなのでコピー1回に集約。目標: YouTube側 約20タップ→約12タップ。
- **U-5. WebCodecs オフラインレンダリング（中期・裁定§1-2と連動）**: `VideoEncoder`+mp4-muxer で150フレームを決定論的に描画・符号化。(i) リアルタイム5秒拘束が消える (ii) フレーム精度の完全ループ (iii) バッチ生成の基盤。iOS Safari 16.4+。背景videoのseek同期が主リスク＝背景を「5.0sシームレス素材の事前デコード」または数式生成に寄せる。
- **U-6. バッチ生成（下書きキュー）**: 既存下書き（最大20件・drafts.js）を「選んだ順に連続生成」。バッチ中は bskyEnable OFF→生成物を予約キューへ。U-5導入後は1本数秒×N本の真のバッチになる。
- **U-7. wizardイベント不達バグ修正**: wizard.js:395,427 の `window.addEventListener` → `document` に変更（§2-4の確認済みバグ。§7 M-4 イベント規約の先行適用）。

---

## 6. P3: データ分析基盤

- **D-1. 取りこぼし回収パック（GAS数行＋クライアント小改修・即効）**
  1. 「ハッシュタグ」列追加＋ `writeRecord_` に putIf 1行（migrate_headers の冪等列追加導線あり コード.gs:267-298）
  2. 「リビルド元ID」列追加＋ doPost で `body.rebuildOf` を拾う → リビルド前後の再生数比較がシートで可能に
  3. 予約経由投稿へ videoId/カテゴリ/workState を中継（予約シートにJSONメタ列を1列追加→runReservations→writeRecord_）
  4. 「音源名」列を追加（YouTubeアプリで付けた音源を記録＝S-2'の受け皿。どの音源が伸びるかの学習軸）
  5. 「タイトル文字数」は setComputed_ に数式1本（過去行にも効く）
  - GAS_VERSION バンプ＋`deploy_gas.mjs`＋`?ping=1` 照合。受け入れ条件: 新規投稿の行に hashtags/rebuildOf が入る／既存行が壊れない。
- **D-2. 実売数のシート合流**: 列「実売数/実売数前日差/実売数更新日時」追加。GASに毎時 `refreshSales()` を新設し、記録タブのcidを集めて fanza-worker `/api/fanza-sales`（POST・最大30件/回）でupsert。**投稿→クリック→実売の3段ファネルが1行で見える**。PCバッチ・worker側は無改修。
- **D-3. 集計の自動化（0円）**: (a) Looker Studio（無料）をシート直結——両チャンネルタブをUNIONする中間シート（`={QUERY(月詠み!…);QUERY(宵桜艶帖!…)}`＋channel列）を1枚追加し、成長曲線・曜日×時間帯ヒートマップをノーコード化。(b) GAS週次レポート（月曜トリガー・MailApp）: 先週Top5/カテゴリ別平均/手動列未入力リマインド。
- **D-4. バケットスナップのサーバー移行**: 端末依存 `view_snaps` を廃し、既に28日分蓄積済みの「再生数_スナップショット」（snapshot.gs）から `action=bucket_snaps` JSONP で30分/1h/2h/6h/24h値を返す。機種変・キャッシュ消去に強くなり、過去分も遡及可能。
- **D-5. YouTube Analytics API（維持率・engagedViews の自動化）**: GASの「高度なサービス」で YouTube Analytics を有効化（チャンネル所有Googleアカウントで実行・OAuth）。日次で `views, engagedViews, averageViewDuration, averageViewPercentage` を videoId 別に取得し「平均視聴維持率%」ほかへ自動upsert。前提確認: acc1/acc2 のチャンネルが同一Googleアカウント管理か（別なら各自のGASまたは片方手動継続）。

---

## 7. P4: 保守性（ビルド無し制約のまま）

方針: 実績ある「IIFE＋`window.名前空間`＋module.exports併記（*-core.js方式）」を共通規約に昇格し、`<script>` を数本増やすだけで分割する。

- **M-1. 共通コア3ファイル（最優先・他タスクの土台）**
  - `core/util.js` → `window.Go5Util`: `$`／`esc`（**`"`を必ずエスケープする1系統に統一**）／`fmtTs`／`yen`／`num`／`lsGet/lsSet`／`jsonp`（settings-io.js:126版採用）／`copyText`。Node併記でテスト可。
  - `core/account.js` → `window.Go5Acct`: `current()`（app.js:525-545の正本を移設）／`key(base, acc?)`（pk/lsk/インライン連結を統合）／`handleOf/didOf/setDid`／`onChange(cb)`。**規約: `localStorage('current_account')` 直読み禁止・'acc1'フォールバックはここ1箇所のみ**。
  - `core/storage-keys.js` → `window.Go5Keys`: 全キーを `{base, scope:'account'|'global'|'cid'|'tab', sync, secret}` の登録制レジストリに。settings-io の isSecretKey/isNoSyncKey をレジストリ参照化し、**クラウド同期を許可リスト方式へ反転**（§2-4の構造問題の恒久解）。tests/test_storage_keys.js で「記録系キーがsync:trueでないか」を表明検査。
  - 移行時の回帰防止: 反転直後は「旧ブロックリストで同期されていたキー一覧」と「新許可リスト」の差分をログ出力し、意図しない同期停止/開始がないか1度目視（INC-62逆パターン予防）。
- **M-2. 神ファイル分割（段階実施・機能改修と混ぜない）**
  - yt-clicks.js → verify-data / verify-render / verify-account-move / verify-sheet-sync / fanza-info（candidatesと共用）/ yt-rank の6分割
  - bluesky.js → bsky-settings / bsky-compose / bsky-record / bsky-repair / bsky-short-hist / bsky-flows の6分割
  - candidates.js → cand-store / cand-images / cand-buzz / cand-tabs / cand-render の5分割
  - 各分割は「1PR=1ファイル切り出し・挙動不変・?v=バンプ・実機スモーク」を受け入れ条件とする。
- **M-3. GAS分割＋ミラー乖離検出**: コード.gs → schema/api/record/settings-sync/stats/reserve/short の複数.gs（claspは複数ファイル対応・deploy_gas.mjs無改修）。`upsertRowOf_` は本体コピーの `gas/upsert-mirror.js` を正本ミラーとし、scripts/check_mirror.mjs で「関数本文テキスト一致」を検査（現状の test_record_upsert.js は再実装ミラーで乖離検出不能）。
- **M-4. イベント契約の明文化**: `core/events.js` に `window.Go5Events = {VIDEO_CREATED:'video-created', …}` と detail スキーマのJSDocを集約。**発火・購読は document に統一**（U-7がその先行修正）。
- **M-5. ファイルヘッダ規約**: 冒頭に「公開API(window.*)／発火・購読イベント／読み書きlocalStorageキー」を必須記載（drafts.js様式を全ファイルへ）。index.html の script 読み込みを「core群→*-core群→機能群」に層別コメント化。
- **M-6. テスト追加の優先順**: ①Go5Keys(sync/secret判定) ②detectAccountMoves_ の分類純関数化＋テスト ③yt-clicks sortItems ④parseBskyPromo_ ⑤upsertミラー一致チェック。
- **M-7. ハードコードされたソフト鍵の整理**: `daremogame...`（bluesky.js:863・コード.gs:667,144付近）と無認証 `settings_pull` JSONP（コード.gs:157）。少なくとも settings_pull にソフト鍵必須化（下書き画像等の設定blobが取得可能なため）。

---

## 8. 実装ロードマップ（タスク表）

> モデル欄は CLAUDE.md §5.1 準拠（見た目/単純=Sonnet、基盤・非同期・複数ファイル・データモデル=Opus）。
> 共通受け入れ条件: `node --check` 全対象／`node tests/test_*.js` 全PASS／実機スモーク／`?v=` バンプ（フロント変更時）／GAS変更時は GAS_VERSION バンプ＋deploy＋ping照合／commit＆push＋live照合。

### Phase 0 — 規約防衛と土台（最初の1〜2セッション）
| ID | タスク | 触るファイル | 主な受け入れ条件 | モデル | 依存 |
|---|---|---|---|---|---|
| P0-1〜3 | 運用ルールの明文化（CLAUDE.md §6 に追記） | CLAUDE.md | ルール3項が「やってはいけない」に載る | Sonnet | なし |
| S-6 | 確認モーダルに1コマ目チェック文言 | bluesky.js | モーダルに注意書き表示・タップ増なし | Sonnet | なし |
| U-7 | wizardイベント不達バグ修正 | wizard.js | ウィザード②が動画作成後に自動で③へ進む（実機） | Sonnet | なし |
| M-1 | 共通コア3ファイル＋sync許可リスト反転 | core/util.js, core/account.js, core/storage-keys.js, settings-io.js ほか置換 | 重複ヘルパ置換後に全機能回帰なし／test_storage_keys.js PASS／同期差分ログ目視 | **Opus** | なし |

### Phase 1 — Shorts即効打＋量産支援（次の2〜3セッション）
| ID | タスク | 触るファイル | 主な受け入れ条件 | モデル | 依存 |
|---|---|---|---|---|---|
| S-1a | 背景の完全ループ化（5.0sシームレス・演出不変） | assets/, （PC側loopify.py） | ループ境界の飛びが目視で見えない・演出完全不変 | Sonnet | なし |
| S-1b | 冒頭フェード見直し（**コンサル手法確認が先**。指定演出なら恒久不採用） | app.js | 確認後にABトグル実装・§9設計で判定 | **Opus** | **Chami確認** |
| S-2' | 音源付け忘れリマインド＋音源名の記録 | index.html, yt-clicks.js, gas/コード.gs | リマインド表示・音源名がシートにupsert | Sonnet | D-1 |
| D-1 | 記録の取りこぼし回収パック | gas/コード.gs, bluesky.js | hashtags/rebuildOf/予約メタ/音源名列が記録される | **Opus** | なし |
| S-3 | メタデータ整備（タグ3〜5・題名・テンプレ） | bluesky.js, schedule/ | 生成タグ数3〜5・2ch別文言 | Sonnet | なし |
| U-2 | 候補から一気に作成（**行動量の主戦場・前倒し**） | candidates.js | 候補→作成まで残り1タップ | Sonnet | なし |
| ベースライン | Studio目視の初回棚卸し（swipe率・フィード表示・年齢制限有無を記録） | （運用） | §9のベースライン表が埋まる | （Chami） | なし |

### Phase 2 — 計測とタップ削減
| ID | タスク | 触るファイル | 主な受け入れ条件 | モデル | 依存 |
|---|---|---|---|---|---|
| D-5 | Analytics API 維持率/engagedViews 自動化 | gas/（高度なサービス） | 日次で維持率列が自動更新 | **Opus** | 前提確認(§6 D-5) |
| D-2 | 実売数のシート合流 refreshSales() | gas/コード.gs | 実売3列が毎時更新・worker無改修 | **Opus** | D-1 |
| U-1 | カテゴリ自動リセット | bluesky.js, persist-fields.js | 投稿後に movieAttr* 全OFF | Sonnet | なし |
| U-4 | YouTube共有ボタン＋題名自動コピー | app.js, index.html | YT側タップ約12まで削減（実測） | Sonnet | なし |
| U-3 | カウントダウン自動投稿トグル | bluesky.js | 確定済み経路のみ・キャンセル可 | Sonnet | U-2 |
| D-3 | Looker Studio 中間シート＋週次レポート | gas/, シート | ヒートマップ表示・月曜メール到達 | Sonnet | D-1 |
| D-4 | bucket_snaps サーバー移行 | gas/コード.gs, yt-clicks.js | 機種変相当（localStorage消去）後もランキング維持 | **Opus** | なし |

### Phase 3 — 裁定後の大物（2026-07-05裁定反映済み）
| ID | タスク | 触るファイル | 主な受け入れ条件 | モデル | 依存 |
|---|---|---|---|---|---|
| ~~S-4~~ | ~~尺11〜20秒 紙芝居モード＋AB~~ | — | **不採用（裁定§1-2=5秒維持）** | — | — |
| U-5 | WebCodecs オフラインレンダリング（**目的縮小: フレーム厳密ループ＋バッチ基盤のみ・優先度低**） | app.js→新 render-core | フレーム厳密ループ・生成が実時間の1/3以下 | **Fable設計→Opus実装** | S-1の効果測定後に要否判断 |
| U-6 | 下書きキューのバッチ生成 | drafts.js, app.js, scheduler.js | 5本連続生成・失敗分離・Drive保存並行 | **Opus** | U-5推奨 |
| API監査 | **申請は決定済（裁定§1-3）**。フォーム提出→承認後 upload 自動化 | scripts/upload_yt.mjs（新規） | private→予約公開の全自動化 | **Opus** | 監査承認 |

### Phase 4 — 保守性の本丸（機能の谷間に随時）
| ID | タスク | モデル | 備考 |
|---|---|---|---|
| M-2 | 神ファイル分割（11PR・1PR=1切り出し） | Sonnet（切り出し）＋Opus（レビュー） | 挙動不変が受け入れ条件 |
| M-3 | GAS分割＋ミラー乖離検出 | **Opus** | deploy_gas.mjs 無改修で通ること |
| M-4/M-5 | イベント契約・ヘッダ規約 | Sonnet | |
| M-6 | テスト5本追加 | Sonnet | |
| M-7 | settings_pull ソフト鍵必須化 | **Opus** | 既存端末の互換に注意 |

---

## 9. 効果測定の設計（ABテスト判定）

- **ベースライン（施策前に必ず取る）**: 直近30本の views / engagedViews / 引き込み率(engaged÷views) / Studio目視のswipe率・フィード表示回数 / 年齢制限の有無。これが無いと全施策の効果が語れない。
- **AB判定の標準形**: 1条件あたり**最低10本×7日間**、同一アカウント・同一時間帯スロットで交互投稿。主指標=engagedViews中央値、副指標=引き込み率・クリック数。**中央値で+30%以上**を採用ライン（Shortsは分散が大きいため平均でなく中央値）。
- **施策別の見る指標**: S-1a/S-1b（ループ/フック）→swipe率(週1目視)と引き込み率／S-2'（音源）→音源名列でグループ比較（どのトレンド音源が伸びるか）／S-3（タグ・時刻）→フィード表示回数(目視)。
- 二次統計由来の閾値（swipe30%・+21%等）は**方向性の根拠であり合格ラインには使わない**。

---

## 10. 不変条件・リスク

**既存の不変条件（維持）**: 比率座標系 W=1080/H=1920・プレビュー=書き出し同一Canvas／完全クライアントサイド・ビルド無し／drive-worker非破壊／link-worker `u:<code>` 不変／秘密はSecrets/Propertiesのみ／紫UI禁止／`?v=`一括バンプ／GASはdeploy_gas.mjs経由のみ。

**新規リスクと手当**:
| リスク | 手当 |
|---|---|
| S-1bがコンサル手法の指定演出を壊す | **Chami確認を着手条件に**。指定演出なら恒久不採用。実施時もABトグルで従来演出を残置 |
| 音源の付け忘れ（無音のまま公開） | S-2'のリマインド＋週次レポート（D-3）に音源名未記入の件数を出す |
| M-1 sync反転で同期漏れ/過剰同期 | 差分ログの目視確認をタスク受け入れ条件に含める（INC-62逆パターン予防） |
| API自動アップでprivateロック | 監査承認前は絶対に本番アップロードに使わない |
| 分割リファクタで回帰 | 1PR=1切り出し・挙動不変・実機スモークを厳守。機能改修と混ぜない |

---

## 11. 主要出典（Shorts攻略・2025〜2026）

公式一次情報:
- videos.insert（privateロック明記）: https://developers.google.com/youtube/v3/docs/videos/insert
- private lock ヘルプ（公開変更・異議申立不可）: https://support.google.com/youtube/answer/7300965
- Data API Revision History（2025/12クォータ改定・2026/6専用バケット）: https://developers.google.com/youtube/v3/revision_history
- Quota Calculator: https://developers.google.com/youtube/v3/determine_quota_cost
- Analytics API Metrics（engagedViews 2025/4〜）: https://developers.google.com/youtube/analytics/metrics
- 外部リンクポリシー（ポルノリンク禁止・煽り文言例）: https://support.google.com/youtube/answer/9054257
- 年齢制限: https://support.google.com/youtube/answer/2802167
- オーディオライブラリ利用条件: https://support.google.com/youtube/answer/3376882
- Shorts音楽ライセンス（アプリ内エディタ限定）: https://support.google.com/youtube/answer/13486873
- 収益化ポリシー（inauthentic content 2025/7）: https://support.google.com/youtube/answer/1311392

二次情報（方向性の根拠として扱う）:
- vidIQ Shorts algorithm 2026: https://vidiq.com/blog/post/youtube-shorts-algorithm/
- Shortimize（swipe率分析）: https://www.shortimize.com/blog/how-does-youtube-shorts-algorithm-work
- quso.ai 尺別分析（11〜20秒帯）: https://quso.ai/research/youtube-shorts-length
- Buffer 投稿時間180万本分析: https://buffer.com/resources/best-time-to-post-on-youtube/
- Social Media Today（inauthenticポリシー解説）: https://www.socialmediatoday.com/news/youtube-clarifies-monetization-update-inauthentic-repeated-content/752892/
