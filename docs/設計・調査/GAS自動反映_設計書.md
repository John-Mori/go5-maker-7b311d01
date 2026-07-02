# GAS自動反映 設計書 (手動コピペ・手動再デプロイの全廃)

作成日: 2026-07-02 ／ 対象リポジトリ: go5-maker ／ 実装担当: Opus/Sonnet (この設計書に沿って実装)

---

## 1. 目的と背景

### 1.1 現状の手動反映手順 (これを全廃する)

`gas/コード.gs` を更新するたびに、ユーザーが iPhone/PC で以下を手作業している:

1. https://script.google.com/ を開いてプロジェクトを開く
2. エディタに新しいコード.gs を全文コピペして保存
3. 「デプロイ」→「デプロイを管理」→ 鉛筆 →「新バージョン」→「デプロイ」
4. `<exec URL>?ping=1` を開いて GAS_VERSION が新しくなったか確認
5. (変更内容により) エディタから `setupTrigger` を手動実行、`?action=migrate_headers` を開く

ユーザーは「GS設定が難しくてよく苦戦してる」と明言しており、
この手順が更新のボトルネック (設定ガイドHTMLを作ったのはこのため)。

### 1.2 ゴール

- Claude が `gas/コード.gs` を編集したら、**PC上のコマンド1発 (またはClaude自身の実行) で
  クラウドのGASに反映され、Web Appの exec URL は変わらないまま新バージョンが有効になる**
- 反映後の後処理 (トリガー再設定・ヘッダ移行) も自動実行
- 反映成否を `?ping=1` のバージョン比較で機械検証
- ユーザーの作業は**初回セットアップ (1回だけ) のみ**。以後ゼロタッチ

---

## 2. 調査結果 (2026-07-02 時点の事実)

| 項目 | 事実 |
|---|---|
| GASプロジェクト | 記録用recorder。Web App デプロイ済み。exec URL: `https://script.google.com/macros/s/AKfycbyQlrWuud5WfE3YMjoYzX2WhstTyWw_sOxVCaT8EfaFMXwi_WZzWIBKarHdtXVsY3Fj/exec` |
| デプロイID | **exec URL 中の `AKfycb...` トークンがそのままデプロイID** (新方式GASの仕様)。デプロイIDを固定して新バージョンを当てれば URL は不変 |
| バージョン検証 | `gas/コード.gs:77` に `var GAS_VERSION = '2026-07-02G（…）'`。`?ping=1` で今動いているコードの GAS_VERSION が返る (`gas/コード.gs:109`) |
| 冪等API | `?action=migrate_headers` / `cleanup_columns` / `diagnose` は doGet で公開済み・冪等 |
| setupTrigger | `gas/コード.gs:843`。**エディタから手動実行のみ**で、リモート実行手段が無い (今回追加する) |
| スクリプトプロパティ | `SHEET_ID` / `YT_API_KEY` / `BSKY_HANDLE` / `BSKY_APP_PW` など。**Apps Script API では設定不可** → 初回に手動設定 (既存ガイドHTMLでカバー済み)。デプロイしても消えない |
| gas/ フォルダ | `コード.gs` の他に `snapshot.gs` (同一GASプロジェクトに「snapshot」ファイルとして追加する設計だった)、ガイド用 `.html` / `.md` が同居 |
| clasp | `npx @google/clasp` → **v3.3.0 が動作確認済み**。Node v24.14.1 |
| OAuth前例 | この PC は wrangler で john.mori8k@gmail.com の OAuth 承認済み → clasp login も同じ流れで承認可能 |
| リポジトリ | GitHub公開リポジトリ (go5-maker-7b311d01)。秘密はコミット禁止 (既存ルール: `scripts/scrape_config.json` を gitignore する方式) |

---

## 3. 方式比較と採用案

| 方式 | 概要 | 評価 |
|---|---|---|
| **A. clasp + PCローカルスクリプト (採用)** | `clasp push` でコード転送 → `clasp deploy -i <デプロイID>` で既存デプロイに新バージョンを当てる。Node スクリプトで検証・後処理まで一気通貫 | ◎ 公式CLI・実績豊富。認証は初回 `clasp login` のみ。Claude が bat を叩けば全自動 |
| B. Apps Script API を素の fetch で叩く | `projects.updateContent` + `deployments.update` | △ clasp がやることの再発明。OAuth トークン管理を自前実装する分だけ損 |
| C. GitHub Actions + clasp | main への push で自動デプロイ | ○ ただし `~/.clasprc.json` (Google リフレッシュトークン) を公開リポジトリの Actions Secrets に置く必要がある。コード.gs の変更は Claude の PC セッションでしか起きないため、現状は過剰。**フェーズ2 (任意)** として設計だけ残す |

**採用: 方式A**。フェーズ2として C を任意追加 (→ §11)。

---

## 4. 全体アーキテクチャ

```
[Claude が gas/コード.gs を編集・GAS_VERSION をバンプ]
        │
        ▼
GASを反映.bat  ──►  node scripts/deploy_gas.mjs
                        │ 0. 設定読込 (scripts/gas_deploy_config.json)
                        │ 1. ローカル GAS_VERSION をパース
                        │ 2. <exec>?ping=1 → 稼働中バージョン取得
                        │    同一ならエラー終了「GAS_VERSIONを上げてから実行」
                        │ 3. .clasp.json を生成 (scriptId, rootDir=gas)
                        │ 4. npx clasp push -f   … コード転送
                        │ 5. npx clasp deploy -i <デプロイID> -d "auto YYYY-MM-DD"
                        │    … 既存デプロイに新バージョンを当てる (URL不変)
                        │ 6. <exec>?ping=1 をポーリング (5秒間隔・最大120秒)
                        │    稼働中バージョン == ローカル版 になるまで待つ
                        │ 7. <exec>?action=admin_setup&secret=… を呼ぶ
                        │    … setupTrigger + migrateHeaders_ を冪等実行
                        │ 8. 結果サマリを表示 (✅/❌ とバージョン・トリガー一覧)
                        ▼
              クラウドGAS (exec URL 不変・新コード稼働)
```

---

## 5. 追加・変更ファイル一覧

| ファイル | 種別 | コミット | 内容 |
|---|---|---|---|
| `gas/コード.gs` | 変更 | する | `admin_setup` アクション追加 + GAS_VERSION バンプ |
| `gas/appsscript.json` | 新規 | する | マニフェスト。**手書き禁止・ブートストラップの temp-pull で取得した実物を置く** (→ §7の落とし穴) |
| `.claspignore` | 新規 | する | ホワイトリスト方式 (→ §6.1) |
| `.clasp.json` | 自動生成 | **しない** (gitignore) | scriptId を含む。deploy_gas.mjs が設定ファイルから毎回生成 |
| `scripts/gas_deploy_config.json` | 新規 | **しない** (gitignore) | scriptId / デプロイID / execUrl / adminSecret |
| `scripts/gas_deploy_config.example.json` | 新規 | する | 上のダミー値テンプレ |
| `scripts/deploy_gas.mjs` | 新規 | する | メインスクリプト (→ §6.3)。**依存パッケージなし** (fetch/child_process のみ。fetch_missing_works.mjs と同じ方針) |
| `scripts/bootstrap_gas.mjs` | 新規 | する | 初回セットアップ補助 (→ §6.5) |
| `GASを反映.bat` | 新規 | する | リポジトリ直下。ダブルクリック/Claude実行用 (→ §6.4) |
| `.gitignore` | 変更 | する | `.clasp.json` と `scripts/gas_deploy_config.json` を追加 |
| `CLAUDE.md` | 変更 | する | 運用ルール追記 (→ §9) |

---

## 6. 詳細設計

### 6.1 `.claspignore` (ホワイトリスト方式・最重要)

`gas/` にはガイドHTML・mdが同居しており、clasp はデフォルトで `.gs/.js/.html` を
**全部プッシュ**し、さらに **push はクラウド側をローカルのミラーに置き換える
(ローカルに無いクラウド側ファイルは削除される)**。事故防止のため必ずホワイトリストにする:

```
# 全部無視して、GASプロジェクトの実体だけ許可
**/**
!コード.gs
!snapshot.gs
!appsscript.json
```

※ `snapshot.gs` を含めるかは §6.5 のブートストラップで実際のクラウド構成を確認して決定する
(クラウドに「snapshot」ファイルが存在する場合のみ含める。存在しないのに push すると
新規追加になる — 関数名の衝突は無いことを確認済みなので追加自体は無害だが、
クラウドとローカルの構成一致を原則とする)。

### 6.2 GAS側の追加: `admin_setup` アクション

`gas/コード.gs` の doGet 内、`migrate_headers` 分岐の近くに追加:

```javascript
// デプロイ後の自動後処理: トリガー再設定＋ヘッダ移行を一括冪等実行。
// deploy_gas.mjs が反映確認後に呼ぶ。secret はスクリプトプロパティ ADMIN_SECRET
// (未設定なら既存のソフト鍵 = shortSecret_() と同じ既定値) と照合。
if (p.action === 'admin_setup') {
  var adminWant = prop_('ADMIN_SECRET') || 'daremogamewoubawareteikukimihakanpekidekyukyokunoidol';
  if (String(p.secret || '') !== adminWant) return jsonOut_({ ok: false, error: 'bad_secret' });
  var mig = migrateHeaders_();
  setupTrigger();
  var handlers = ScriptApp.getProjectTriggers().map(function (t) { return t.getHandlerFunction(); });
  return jsonOut_({ ok: true, version: GAS_VERSION, migrated: mig, triggers: handlers });
}
```

設計判断:
- `migrate_headers` は既に無認証公開なので、実害のある新規公開は「トリガー再作成」のみ。
  冪等 (delete→create) で連打されても壊れないが、実行クォータ浪費防止にソフト鍵で門番する
- ADMIN_SECRET プロパティを設定すればそちらが優先 (任意・推奨)。未設定でも動く
  (ソフト鍵は既にリポジトリ公開されている値なので「秘密」ではなく「いたずら避け」)
- **この変更自体の初回反映も clasp で行える** (ブートストラップ完了後の初回 deploy に含める)。
  手動コピペは今回が最後にもならない＝一度も要らない
- GAS_VERSION を必ずバンプすること (例: `2026-07-0XH（admin_setup追加=GAS自動反映対応）`)

### 6.3 `scripts/deploy_gas.mjs` (メイン)

依存なし Node スクリプト。処理フロー (擬似コード):

```
const cfg = readJson('scripts/gas_deploy_config.json')
  // { scriptId, deploymentId, execUrl, adminSecret }
  // 無ければ: 「先に bootstrap_gas.mjs を実行してください」と案内して exit 1

const localVer = /var GAS_VERSION = '([^']+)'/.exec(read('gas/コード.gs'))[1]
  // パース失敗 → exit 1「GAS_VERSION が見つからない」

const live = await fetchJson(cfg.execUrl + '?ping=1')   // リダイレクト追従必須 (下記注意)
if (live.version === localVer && !argv.includes('--force'))
  exit 1 「稼働中と同じ GAS_VERSION です。コード.gs の GAS_VERSION を上げてから実行」

writeJson('.clasp.json', { scriptId: cfg.scriptId, rootDir: './gas' })

run('npx @google/clasp push -f')                        // 対話なし
run(`npx @google/clasp deploy -i ${cfg.deploymentId} -d "auto ${today} ${localVer先頭20字}"`)

// 反映待ちポーリング: 5秒間隔・最大 24回 (120秒)
loop {
  const v = (await fetchJson(cfg.execUrl + '?ping=1')).version
  if (v === localVer) break
}
// タイムアウト → exit 1「デプロイは実行したが反映を確認できず。?ping=1 を手動確認して」

const setup = await fetchJson(cfg.execUrl + '?action=admin_setup&secret=' + encodeURIComponent(cfg.adminSecret))
// setup.ok を確認。triggers 配列に refreshClicks / refreshEngagement / snapshotStats が
// 揃っているかチェックして表示

print サマリ:
  ✅ GAS反映完了
     バージョン: <localVer>
     トリガー: refreshClicks, refreshEngagement, snapshotStats
     移行: <setup.migrated の要約>
```

実装上の注意:
- **GAS の exec URL は 302 リダイレクトを返す**。Node の fetch は既定で追従するが、
  `redirect: 'follow'` を明示し、レスポンスが JSON でない場合 (HTMLログインページ等) は
  「Web App のアクセス設定が『全員』になっていない可能性」とエラー表示する
- clasp 実行は `child_process.execSync`/`spawnSync` で。**clasp v3 系はコマンド名が
  v2 から一部変わっている**ため、実装時に `npx @google/clasp --help` で
  `push` / `deploy` のオプション表記を必ず確認する (`-i/--deploymentId`, `-d/--description`)
- 終了コード: 成功 0 / 検証失敗・設定不足 1。bat 側で `if errorlevel 1 pause`
- `--check` オプション: push せず「ローカル版 vs 稼働版」の比較だけ表示する dry-run

### 6.4 `GASを反映.bat` (リポジトリ直下)

「未収録作品を取得.bat」と同じ流儀 (cp932事故を避けるため chcp 65001):

```bat
@echo off
chcp 65001 >nul
cd /d "%~dp0"
node scripts\deploy_gas.mjs %*
if errorlevel 1 pause
```

### 6.5 `scripts/bootstrap_gas.mjs` (初回だけ実行)

初回セットアップの機械化できる部分を担う:

```
1. scripts/gas_deploy_config.json が既にあれば「設定済み」と表示して終了
2. 対話入力 (または引数) で scriptId を受け取る
3. .clasp.json を一時生成し、**一時ディレクトリ (scratchpad) に clasp pull**
   ※ gas/ に直接 pull すると ローカルの新しい コード.gs が
     クラウドの古い版で上書きされる (絶対禁止・最重要の落とし穴)
4. temp-pull の結果から:
   - appsscript.json を gas/appsscript.json へコピー (無ければエラー)
   - クラウド側のファイル一覧を表示し、リポジトリの gas/ と突き合わせ:
     ・クラウドにあってローカルに無い .gs → gas/ へコピーして .claspignore に追加
       (push のミラー動作で消してしまわないため)
     ・「snapshot」有無を判定して .claspignore を確定
5. exec URL の入力を受け取り、URL 中の AKfycb… トークンをデプロイIDとして抽出
6. ?ping=1 を叩いて疎通確認 (ok:true と version が返ること)
7. scripts/gas_deploy_config.json を書き出し
8. 「次は GASを反映.bat を実行」と案内
```

### 6.6 `.gitignore` 追記

```
# GAS自動反映のローカル設定 (scriptId・デプロイID・adminSecret を含むためコミットしない)
.clasp.json
scripts/gas_deploy_config.json
```

※ `~/.clasprc.json` (Google OAuth リフレッシュトークン) はホームディレクトリに置かれ
リポジトリ外なので gitignore 不要。**絶対にリポジトリへコピーしない**こと。

---

## 7. 実装者向け・落とし穴集 (必読)

1. **`clasp pull` を gas/ に対して実行しない**。ローカルの最新コード.gs がクラウドの
   古い版で上書きされる。pull は bootstrap の temp ディレクトリでのみ行う
2. **`clasp push` はミラー同期** — クラウドにあってローカル (rootDir + claspignore 通過分) に
   無いファイルは削除される。bootstrap の突き合わせ (§6.5-4) を必ず先に行う
3. **`.claspignore` はホワイトリスト必須**。無いと gas/ 内のガイドHTML
   (再デプロイ手順.html / snapshot-guide.html) が GAS プロジェクトに追加されてしまう
4. **`clasp deploy` を素で叩かない** — 新規デプロイが作られ**別の exec URL** になる。
   必ず `-i <既存デプロイID>` を付ける。デプロイIDは exec URL の AKfycb… トークン
5. **appsscript.json は手書きしない** — webapp の executeAs/access 設定が実物と食い違うと
   再デプロイでアクセス権が壊れる (アプリの JSONP が全滅する)。temp-pull の実物を使う
6. **GAS_VERSION バンプの強制** — deploy_gas.mjs は「稼働版 == ローカル版」なら push 前に
   エラー終了する。Claude はコード.gs を編集したら必ず GAS_VERSION を上げる (既存慣習)
7. **反映の伝播遅延** — deploy 直後の ?ping=1 は旧版を返すことがある。ポーリング必須
8. **スクリプトプロパティは API で設定不可** — SHEET_ID / YT_API_KEY / ADMIN_SECRET は
   初回に手動設定 (既存の GAS自動記録_設定ガイド.html がカバー)。デプロイでは消えない
9. **clasp v3 系のコマンド差異** — v2 の記事が多いので `--help` で実物を確認する。
   認証情報は `~/.clasprc.json` (v3 でも同じ)
10. **非ASCIIファイル名 (コード.gs)** — clasp は UTF-8 で扱うため通常問題ないが、
    push 後に GAS エディタでファイル名が文字化けした場合のフォールバックとして
    「クラウド・ローカル両方で code.gs へ改名」を許容する (機能影響なし)
11. **exec URL の fetch は 302 追従＋JSON検証** — HTML が返ったらアクセス設定異常を疑う
12. **秘密の扱い** — gas_deploy_config.json / .clasp.json / ~/.clasprc.json は
    コミット禁止。エラー表示やログに adminSecret・scriptId を丸出しにしない
    (先頭6文字＋… のようにマスクして表示)

---

## 8. ユーザーの初回セットアップ手順 (1回だけ・ガイド化する内容)

実装完了後、以下をユーザーに案内する (既存のクリーム色ガイドHTMLと同じ流儀で、
URL はフル記載・コピー可能なコードブロックにする):

1. **Apps Script API を有効化** (Googleアカウント単位・1回だけ)
   - 開く: `https://script.google.com/home/usersettings`
   - 「Google Apps Script API」を **オン**
2. **clasp ログイン** (PC で 1回だけ)
   - PC で `GAS初期設定.bat` を実行 (内部で `npx @google/clasp login` → ブラウザが開く)
   - john.mori8k@gmail.com で承認
3. **スクリプトID の確認**
   - 開く: `https://script.google.com/home` → recorder プロジェクトを開く
   - 左の歯車 (プロジェクトの設定) → 「スクリプト ID」をコピー
4. **bootstrap 実行**
   - `GAS初期設定.bat` が続けて scriptId と exec URL を聞くので貼り付ける
   - exec URL は既知: `https://script.google.com/macros/s/AKfycbyQlrWuud5WfE3YMjoYzX2WhstTyWw_sOxVCaT8EfaFMXwi_WZzWIBKarHdtXVsY3Fj/exec`
5. (推奨・任意) スクリプトプロパティに `ADMIN_SECRET` を追加
   - プロジェクトの設定 → スクリプト プロパティ → 追加
   - 未設定でも動く (ソフト鍵にフォールバック)

以後は不要。Claude が編集→`GASを反映.bat`→自動反映。

※ `GAS初期設定.bat` = 「clasp login → bootstrap_gas.mjs」を連続実行する bat。実装対象に含める。

---

## 9. CLAUDE.md への追記内容 (運用ルール)

```markdown
## GAS の反映 (自動化済み)
- gas/コード.gs を編集したら必ず GAS_VERSION をバンプする (日付+英字サフィックス)
- 編集後は「GASを反映.bat」(= node scripts/deploy_gas.mjs) を実行して反映する。
  手動コピペ・手動再デプロイの案内はしない
- deploy_gas.mjs は push→デプロイID固定で再デプロイ→?ping=1で検証→admin_setup
  (トリガー/移行) まで自動実行する。失敗したら出力のエラーメッセージに従う
- clasp pull を gas/ に対して実行してはならない (ローカルが正)
```

---

## 10. テスト計画と受け入れ条件

### テスト手順 (実装者が実施)

1. **bootstrap**: `GAS初期設定.bat` → config 生成・appsscript.json 取得・疎通OKを確認
2. **無変更ガード**: バンプせずに `GASを反映.bat` → 「GAS_VERSIONを上げて」で止まること
3. **本番反映**: コード.gs に admin_setup を実装し GAS_VERSION をバンプ →
   `GASを反映.bat` → 以下を確認:
   - exec URL が変わっていない (config の execUrl のまま ping が新バージョンを返す)
   - `?ping=1` の version がローカルと一致
   - admin_setup 応答の triggers に refreshClicks / refreshEngagement / snapshotStats
   - スプレッドシートの既存データが無傷 (migrate は冪等なので列が壊れない)
4. **アプリ動作**: アプリの投稿履歴タブ・デルタ表示 (deltas) が従来どおり動く
5. **--check**: dry-run がバージョン比較のみ行い、push しないこと

### 受け入れ条件

- [ ] コード.gs 編集→bat 実行だけで、ユーザー操作ゼロでクラウド反映が完了する
- [ ] exec URL が絶対に変わらない (アプリ側 localStorage の GAS URL 修正が不要)
- [ ] 反映成否がバージョン比較で機械判定され、失敗時は原因が日本語で表示される
- [ ] トリガー3本とヘッダ移行が反映のたびに冪等で保証される
- [ ] 秘密 (clasprc / config / scriptId) がコミットされていない (`git status` で確認)
- [ ] 既存の手動ガイド (GAS自動記録_設定ガイド.html) は削除せず「予備手順」として残す

---

## 11. フェーズ2 (任意・今回は実装しない): GitHub Actions 自動反映

コード.gs の変更が Claude の PC セッション以外でも起きるようになったら検討:

- ワークフロー: `on: push` (paths: `gas/コード.gs`) → Node セットアップ →
  Secrets から `~/.clasprc.json` を復元 → deploy_gas.mjs を CI モードで実行
- 必要な Actions Secrets: `CLASPRC_JSON` / `GAS_SCRIPT_ID` / `GAS_DEPLOYMENT_ID` /
  `GAS_EXEC_URL` / `GAS_ADMIN_SECRET`
- 留意: 公開リポジトリだが Secrets は暗号化され PR からは参照不可。ただし
  Google アカウントのリフレッシュトークンを GitHub に預けることになるため、
  プライバシー重視の本プロジェクトでは**必要になるまで見送り**

---

## 12. 実装タスクリスト (Opus/Sonnet 向け・この順で)

| # | タスク | 完了条件 |
|---|---|---|
| T1 | `.gitignore` 追記 (+ example config 作成) | §6.6 のとおり。example に全キーのダミー値 |
| T2 | `gas/コード.gs` に admin_setup 追加 + GAS_VERSION バンプ | §6.2 のコード。node --check は .gs に使えないので目視＋後続テストで検証 |
| T3 | `scripts/bootstrap_gas.mjs` + `GAS初期設定.bat` | §6.5 の8ステップ。temp-pull は scratchpad を使用 |
| T4 | `.claspignore` 作成 | T3 の突き合わせ結果を反映したホワイトリスト |
| T5 | `scripts/deploy_gas.mjs` + `GASを反映.bat` | §6.3 のフロー・§7 の落とし穴対応・--check 実装 |
| T6 | CLAUDE.md 追記 | §9 の内容 |
| T7 | エンドツーエンドテスト | §10 のテスト手順を全部通す (T2 の反映が初回実運用を兼ねる) |
| T8 | ユーザー向け初回セットアップガイド (クリーム色HTML・任意) | §8 の内容。既存ガイドHTMLのデザイン踏襲・URLはコピー可能なコードブロック |
| T9 | commit & push | 秘密が含まれないことを git status / git diff で確認してから |

備考:
- T3/T7 は実行時にユーザーのブラウザ承認 (clasp login) が1回必要。Claude が bat を起動し、
  ユーザーに「ブラウザで承認してください」と声かけする段取りにする
- 全スクリプトは依存パッケージなし (npm install 不要) で書く。clasp は npx 経由で使う
