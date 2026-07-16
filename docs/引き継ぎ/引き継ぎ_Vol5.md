# 引き継ぎ — Vol.5 キックオフ（go5-maker）

> **新しいチャット(Vol.5)を始めたら、まずこのファイルを読む。**
> 一次情報は `CLAUDE.md`。インシデント台帳は `インシデント.md`（巻をまたぐ通し番号）。中期計画は `docs/設計・調査/改善書_Shorts攻略と全体改善ロードマップ.md`。
> このファイルは「Vol.4 の到達点」と「Vol.5 でやること」を1枚にまとめた俯瞰図。食い違いは実コード＋`CLAUDE.md` が優先。

最終更新: 2026-07-07 ／ 巻の切り替え: **Vol.4 → Vol.5**

---

## 0. 現在の到達点（このファイル作成時点）

| 項目 | 状態 |
|---|---|
| 公開バージョン(live) | **`?v=238`**（`https://john-mori.github.io/go5-maker-7b311d01/`） |
| GAS_VERSION | **`2026-07-07A`**（T10接頭辞ガード＋T11 LockService・**live反映済み** 2026-07-07・`?ping=1`照合済） |
| ブランチ / 作業ツリー | `main` |
| 現行ソースの場所 | **`D:\SougouStartFolder\go5-maker`**（このセッションの全デプロイはここから成功。GitHub Pages/GAS live と一致） |
| デプロイ | GitHub Pages（`.nojekyll`＝INC-66）。Pages のデプロイ段階が一時失敗することがある→ワークフロー再実行 or `gh api -X POST repos/John-Mori/go5-maker-7b311d01/pages/builds` |
| 記録シート | 「AFI動画アナリティクス分析」。掃除後の健全状態＝**月詠み24行 / 宵桜15行・誤混入0・純ゴミ0・重複0（実測）** |

**機密ファイル（絶対にコミットしない）**：`scripts/scrape_config.json` / `scripts/gas_deploy_config.json` は `.gitignore` 済。`raw/` は git 管理外（コンサル資料・公開リポジトリ禁止）。

---

## 1. Vol.4 でやったこと（v201 → v238 の要約）

Vol.4 は前半（v201〜v209＝改善書 Phase 0/1＋候補タブ拡張、詳細は `引き継ぎ_Vol4.md`）と、後半の**大規模なデータ健全化**（v210〜v238）に分かれる。後半の要点：

### A. 候補タブ・投稿履歴・リビルドの作り込み（v210〜v231）
- **投稿済み判定の全経路修正（INC-71・v218/220）**：候補の「投稿済み」pillが点灯しない多重欠陥を、正規化チェーン統一＋明示cid＋メモ化索引＋GAS extractCid_ のBooks対応で根治。
- **FANZA Books 対応（v222/224/225）**：`.com` 2階層URLの content_id 優先（`booksM[3]||booksM[2]`）、100%OFF(price=0)の割引計算バグ修正（`parseFanzaItem`/worker/`isOnSale_`）、セール%OFFスクレイプ、Books/同人セール表示の同形式化。
- **🔁リビルド機能拡張（v223/226/228）**：履歴から「リビルドで作る」→同一作品ならBluesky再投稿せず前回投稿を引き継ぎ（クリック計測継続）／投稿履歴の編集に「🔁リビルド結合」を追加（作品URL一致の動画を選んで結合）／リビルド版のクリックは総合値＋括弧表示（`rebuildMerged`/`rebuildBaseClicks`）。
- **UI/配色/ボタン幅の恒久ルール化（v227/229/230/231）**：ボタン幅はテキスト長に自動追従（`width:max-content`・`.fz-modal button` / `.vedit-modal button` で担保・インライン`width:100%`禁止）／候補タブに**アカウント別「投稿済み非表示」トグル**（`cand_hide_posted`・両ch独立）／価格ラベル「現定価」／候補→動画生成で**YouTube題名(`ytTitle`)が前作のまま残るバグ修正**（`#top`に input+change 両発火・tabYT再構築）／候補カードの「投稿予定プレビュー」を下段に横並び（画像＋右一行コメント）／**Bluesky独自画像未添付なら`_Bsky投稿`画像を重複保存しない**。

### B. 宵桜(acc2)のYouTube情報欠落＝INC-72（v232〜v236）
per-account構造欠陥が「片方だけ壊れた」に見える典型。**D1** 検証タブのYouTube照会が50件でsilent打ち切り→**50件バッチ分割**（`fetchData_`）。**D2** `fetchVideos`が失敗を`{}`で握り潰す→`{__error}`。**D4** DID矯正がverify_ytを移し忘れ→随伴移送。**D3=決定打（v236）** 識別子(postUri/短縮/videoId)が全世代ずれて照合不成立の行を、**YouTube実データ照合**（投稿題名＝YouTube題名の正規化一致＋投稿時刻72h以内で同名判別）で各行へ対応づけ、**アイテム本体`item.ytUrl`へ書き戻し**（キー回転に不変な恒久形＝再発根絶）。「🔧 YT情報を診断・修復」ボタンと72時間バケットも追加。

### C. アカウント混入の根治＝INC-73（v237＋GAS 2026-07-07A）★Vol.4の最大成果
**17エージェント監査＋敵対検証（10所見確定）**で全経路を確定（`docs/設計・調査/改善書_宵桜艶帖YouTube情報欠落_原因調査.md`§11 が正本）。実装：
- **T1 所有権サニタイザ `sanitizeOwnership_`**（`refresh()`冒頭・冪等・ローカルのみ）：誤アカウントに混入した投稿を **投稿者DID(台帳解決済み時)→videoId接頭辞** の二段判定で正chへ自動帰還。到着先は強キー(postUri>videoId)で重複統合、`verify_yt`随伴移送。**postUriアイテムは台帳が解決済みの時だけ移動＝正当な手動移動を誤って戻さない**（未解決時は解決後の後追いで移動）。↩️は `_ownerPin` で所属固定（自動判定より人の指示が上）。
- **T2** `moveOne_`：`move_row`の応答検証＋失敗を `sheet_move_pending` へ積み次回自動再送／`moveItemAccount_`は本人投稿(DID一致)の移動を強警告。
- **T3** `restoreHistoryFromSheet_`：弱キー(`t:題名|YT`)横断移動を禁止＋ローカル品の所属ガード。
- **T4** `bluesky.js`：DID学習毒(無検証`setAcctDid`)を除去。ハンドル解決後、両DID解決済み・相異の時だけDID矯正。`Go5AccountRepair.ledgerFresh` 追加。
- **T5** `pushItemToGas_`/`pushRemadeToGas_`/`sendSync_`：シートchannelを**videoId接頭辞優先**（`chOfVid_`）＝誤タブ薄行の「感染プリンタ」停止。
- **GAS 2026-07-07A**：**T11** `doPost`全体を`LockService`で直列化＝重複行根絶／**T10** `writeRecord_`冒頭で videoId接頭辞≠channel を正chへリダイレクト＝最終防壁。
- **既存シート異常はGAS API(prune_history/delete)で掃除済**（宵桜の月詠み混入3行・ut2c重複・純ゴミ薄行を除去。上記の健全状態を実測）。

### D. 投稿履歴レイアウト調整（v238）
非表示トグルの🙈削除・縦1.5倍・自動幅・**行の枠外(リスト最上部の独立バー)へ移動**（先頭カードに重ならない）／作品↗を`.vrow-links`で同列化／被リビルドの高さを「リビルドで作成」と統一／**🗑押下で削除対象行を赤枠明示**（`.vrow-deleting`・確認中も表示・キャンセルで解除）。

---

## 2. Vol.5 でやること

**確定タスクは無い（Vol.4でユーザー起点の不具合修正を一巡完了）。** Vol.5 は以下から着手判断：

### 2-1. 未着手の残タスク（監査の第2波以降・任意）
改善書§11の実装計画のうち **T12/T13 は未実装**（優先度低・現状のprune/deleteで代替可）：
- **T12** GAS `deleteRecord_` に videoId キー対応（薄行の遠隔削除を1操作に）。
- **T13** GAS `action=cleanup_rows`（誤タブ行クリア＋重複デデュープの冪等ワンショット・dryRun付き推奨）。
- **T6/T7**（改善書計画）：`histAdd`書き込み時の接頭辞ガード・予約account凍結／`runBulkGen`に所有権フィルタ。**T1サニタイザ＋GAS T10で実害はほぼ消えている**ため、必要になったら。

### 2-2. 中期ロードマップ（`docs/設計・調査/改善書_Shorts攻略と全体改善ロードマップ.md` §8）
Phase 1 まで実装済み。**Phase 2 以降が未着手**：
- D-5 Analytics API（engagedViews/維持率の自動記録・**Chami の OAuth/高度なサービス設定要**）→ D-2 実売数シート合流 → D-3 Looker Studio＋週次メール → D-4 bucket_snaps サーバー移行 → U-4 YouTube共有ボタン → U-1 カテゴリ自動リセット → U-3 カウントダウン投稿。
- Phase 3=API監査承認後のアップロード自動化・バッチ生成(U-6)。Phase 4=神ファイル分割(M-2)・GAS分割(M-3)・イベント規約(M-4・発火/購読は`document`統一)・テスト追加。

### 2-3. 監視ポイント（Vol.4の修正が効いているかの実機確認）
- 宵桜の投稿履歴を開くと **T1サニタイザが混入投稿を自動帰還**（「⚠️ N件を正しいアカウントへ移動しました ↩️」表示）。以後は自動修正されるので、混入報告が来たら**まず接頭辞・DID台帳・操作履歴の非対称**を疑う（`[[go5-account-ownership-model]]` メモリ参照）。
- 新規投稿で重複行・誤タブ行が**再発しないこと**（GAS T10/T11 が防壁）。

---

## 3. 反映・運用のルール（Vol.5でも厳守）

- **フロント変更後は `index.html` の `?v=N` を必ず上げる**（52箇所一括）。次の変更から **`?v=239`**。Editツールの `replace_all` で `?v=238`→`?v=239` が手軽（分類器がPowerShell/Bashを断続的にブロックする時間帯があるため）。
- **GAS変更後は `GAS_VERSION` を上げてから** `node scripts/deploy_gas.mjs`。反映確認は `?ping=1`。**GAS本番デプロイは毎回ユーザーの明示承認が必要**（auto mode分類器がブロックする＝「任せる/進めて」の一般GOでは通らない。ユーザーに `node scripts/deploy_gas.mjs` を実行してもらうか、明示承認を得る）。`.gs`は`node --check`不可→`.js`にコピーして構文確認。
- **GASへのPOSTはcurlだとリダイレクトで411**になる→ブラウザ`fetch`（preview_eval）を使う。GETのhistory/diagnose/pingはcurlでOK（`&callback=cb`でJSONP、`sed`で剥がす）。
- **デプロイ確認は必ずlive照合**：`curl .../index.html?cb=<ts> | grep '?v='`。Pagesが `building` で止まる/デプロイ段階で "Deployment failed, try again later." になることがある→`gh run rerun <id> --failed` かビルド再要求。
- **実装完了後は `git commit && git push` まで**。コミット末尾に `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`（fable使用時は Fable 5）。
- **プレビュー検証の作法**：ビューポートが0×0に潰れることがある→`preview_resize` mobile で寸法測定。スクショはbg videoでタイムアウトしがち→`preview_eval`で寸法/DOMを実測。`window.Go5AccountRepair` をスタブ化するとDID判定を制御して T1 を単体検証できる。
- **配色ルール**：Claude風の紫UI禁止。アカウントテーマ配色（acc1=宵藍系 / acc2=葡萄梅系）。
- **ボタン幅の恒久ルール**：`width:auto`/`max-content`でテキスト幅に追従。全幅は主要CTA/リスト行のみ。インライン`width:100%`をボタンに付けない（`[[go5-button-style-pref]]`）。
- **不変条件**：比率座標系（W=1080/H=1920）・**前景の見た目/演出**（コンサル手法）・drive-worker非破壊・link-worker `u:<code>`不変・GASの`SHARED_SECRET`未設定・秘密はSecrets/Propertiesのみ。**videoIdは作成時に`acc1-`/`acc2-`接頭辞＝所属の権威シグナル**（T1/T5/T10の根幹）。

---

## 4. 一次情報・参照先

| 目的 | ファイル |
|---|---|
| 公式コンテキスト（最新仕様） | `CLAUDE.md` |
| 中期計画（Phase 2以降が未着手） | `docs/設計・調査/改善書_Shorts攻略と全体改善ロードマップ.md` |
| **アカウント混入・YT欠落の原因調査＋実装状況** | `docs/設計・調査/改善書_宵桜艶帖YouTube情報欠落_原因調査.md`（§10=YT欠落D1〜D5、§11=混入の全経路監査＋実装計画T1〜T13） |
| ミス台帳（巻またぎ・INC通し番号・最新=INC-73） | `インシデント.md` |
| 前巻キックオフ（Vol.4前半の詳細） | `引き継ぎ_Vol4.md` |
| アカウント混在の恒久対策 設計（旧） | `設計_投稿履歴アカウント混在の恒久対策.md` |
| GAS自動反映 設計 | `docs/設計・調査/GAS自動反映_設計書.md` |
