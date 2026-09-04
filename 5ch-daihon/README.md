# 5ch台本(cut_list)編集システム — 止血版

Chamiがスマホ/PCのブラウザから、5chスクレイパ由来の動画台本(cut_list.yaml)の
`caption_text` / `narration_text` / `reaction_text` を編集・保存できる最小構成。

**この止血版でできること**: コマ一覧の表示(cut_id / image_file / phase / cut_type)＋
上記3フィールドの編集・保存だけ。**できないこと**: AI生成・VOICEVOX試聴・字幕トグルの新設・
並べ替え・画像差し替え(すべて次の本実装で)。

構成は `worker/`(Cloudflare Worker・R2バックのCRUD API)と `public/`(Cloudflare Pages・編集UI)の2つ。
この文書は**まだ何もデプロイしていない前提**でChamiがダッシュボードでやる手順を書く。
★このAIエージェントは `wrangler deploy` 等の実デプロイ・R2バケット作成を一切実行していない
(権限が無い/CLAUDE.mdの鉄の掟で禁止)。すべてChami(または承認された司令塔)の手番。

---

## 0. 事前に直しておくこと(★重要・実データのバグを発見)

実物の cut_list を確認した際、`local/5ch/projects/holodri_noel/holodri_noel_cutlist.yaml` の
`work.output` フィールド(56行目)に **YAML仕様上不正なエスケープシーケンス** が見つかった:

```yaml
output: "D:\SougouStartFolder\5SecMovieMaker\local\5ch\projects\holodri_noel\output\holodri_noel_test.ymmp"
```

ダブルクォート文字列の中で `\S` `\5` `\l` 等はYAMLの正規のエスケープではない(`\\`と書く必要がある)。
このWorkerが使う `yaml` パッケージの `parseDocument` はこれを解析エラーとして記録し、
**保存(`doc.toString()`)しようとすると例外で落ちる**(読み取り専用の一覧表示は best-effort で
動く可能性があるが未検証)。

同じファイル内の他のパス(`image_file` 等)は `"D:\\SougouStartFolder\\..."` と正しく `\\` で
エスケープされているので、`output` フィールドだけの問題。**このツールでこの台本を編集する前に、
`output:` の値を `\\` に直すか、シングルクォート `'...'` に変えるかしてください**
(シングルクォート内はバックスラッシュのエスケープが不要)。

★このAIエージェントは既存ファイルを書き換えない方針のため、この修正はしていない。
根拠= `5ch-daihon/worker/test_roundtrip.mjs` のコメントに実測結果を記載、実際に
`node -e "require('yaml').parseDocument(...)"` でエラー8件(すべて `output:` 行由来)を確認済み。

---

## 1. R2バケットを作成する

1. Cloudflareダッシュボード → R2 → 「バケットを作成」。
2. バケット名 = `go5-5ch-daihon`(この名前は `worker/wrangler.toml` の `bucket_name` と一致させる必要がある)。
3. **パブリックアクセスは有効化しない**(r2.devの公開URLをONにしない)。このシステムはR2に直接アクセスさせず、
   常にWorker経由でのみ読み書きする設計。

未検証: R2バケットの作成手順そのものはCloudflareダッシュボードの標準操作のため大きくは変わらないはずだが、
実際の画面文言は確認できていない。

---

## 2. 既存の cut_list を R2 へ投入する

キー規約 = `projects/<プロジェクト名>/cutlist.yaml`(例 `projects/holodri_noel/cutlist.yaml`)。
`GET /api/projects` はこの `projects/` プレフィックス配下の `.yaml`/`.yml` を列挙するので、
この規約から外れると一覧に出ない。

`worker/` フォルダで(§0のバグ修正を済ませてから):

```bash
cd 5ch-daihon/worker
npx wrangler r2 object put go5-5ch-daihon/projects/holodri_noel/cutlist.yaml \
  --file="../../local/5ch/projects/holodri_noel/holodri_noel_cutlist.yaml"
```

複数プロジェクトがあれば `projects/<name>/cutlist.yaml` の形で同様に put する。

---

## 3. Worker をデプロイする

`worker/wrangler.toml` を開いて次を編集:

- `[vars] ALLOWED_ORIGIN` を、手順5で作るPagesの配信ドメイン(例 `https://xxxx.pages.dev` や独自ドメイン)に置き換える。
  ワイルドカードは使えない(1オリジンのみ)。

```bash
cd 5ch-daihon/worker
npm install        # 初回のみ(yaml パッケージを取得)
npx wrangler login # 未ログインなら
npx wrangler deploy
```

成功すると `https://go5-5ch-daihon.<subdomain>.workers.dev` のようなWorker URLが表示される。
これを `public/app.js` 先頭の `API_BASE` に貼って(§5で反映)。

秘密(APIキー等)はこの止血版には無い(認証はCloudflare Access任せ・§4参照)。

---

## 4. Cloudflare Access(Zero Trust)で保護する(★これが主防御)

このWorkerとPagesは、コード側では「Cf-Access-Jwt-Assertionヘッダの存在チェック」しかしていない
(署名検証はしていない・止血版の既知の弱点)。**実際の防御はCloudflare Access(Zero Trust)がedgeで
未認証リクエストを弾くこと**に懸かっている。

1. Cloudflare ダッシュボード → Zero Trust → Access → Applications → 「アプリケーションを追加」。
2. アプリケーションタイプ = 「セルフホスト型」。
3. ドメイン欄に、Workerのドメイン(`go5-5ch-daihon.<subdomain>.workers.dev` またはカスタムドメイン)と、
   Pagesのドメイン(手順5)の両方をそれぞれ別アプリケーションとして登録する(2つ作る)。
4. ポリシー: 「許可(Allow)」、ルールの条件 = 「Emails」→ Chamiのメールアドレスのみ。
5. 認証方法 = 「One-time PIN」(メールにワンタイムPINが届く方式。追加のIDプロバイダ設定が不要)。
6. 保存すると、Worker/PagesのURLへ最初にアクセスした時にCloudflareのログイン画面(PIN入力)が挟まる。

未検証: Workers(workers.dev サブドメイン)にCloudflare Accessを直接適用できるか、
それともカスタムドメイン経由でないと適用できないかは、このAIエージェントの権限では確認できていない。
`workers.dev` に直接Accessが掛からない場合は、Workerに独自ドメイン(CloudflareでDNS管理しているドメインの
サブドメイン等)を割り当ててから、そのカスタムドメインにAccessアプリケーションを作る必要がある可能性がある。
Chami側でCloudflareダッシュボードの実画面を見て確認してほしい。

---

## 5. Pages(public/)を配信する

1. Cloudflareダッシュボード → Workers & Pages → 「アプリケーションを作成」→「Pages」→
   「直接アップロード」(Gitリポジトリ連携でもよいが、この5ch-daihonは5秒動画メーカーと同じrepoの
   サブフォルダなので、Git連携する場合はビルド出力ディレクトリを `5ch-daihon/public` に指定する)。
2. プロジェクト名は任意(例 `go5-5ch-daihon`)。
3. デプロイ後に表示される `https://xxxx.pages.dev` のドメインを、
   `worker/wrangler.toml` の `ALLOWED_ORIGIN` に反映して `npx wrangler deploy` を再実行(手順3)。
4. `public/app.js` 先頭の `API_BASE` 定数を、手順3で控えたWorker URLに書き換えてから再デプロイする。

独自ドメインを使う場合はPages側のカスタムドメイン設定を使う(手順は標準のPages機能・未検証)。

---

## 6. 動作確認

1. PagesのURLを開く → Cloudflare Accessのログイン(PIN)が出ることを確認。
2. ログイン後、プロジェクト選択のドロップダウンに手順2で投入したプロジェクトが出ることを確認。
3. コマ一覧が表示され、caption_text等を編集して「保存」→ 「保存しました」と出ることを確認。
4. R2の中身(`npx wrangler r2 object get go5-5ch-daihon/projects/<name>/cutlist.yaml --file=-`)を見て、
   編集した値が反映され、かつ冒頭・末尾のコメントが消えていないことを確認。

---

## 7. 既知の制約(止血版・次の本実装で解消する項目)

- Cf-Access-Jwt-Assertion ヘッダの**存在チェックのみ**(署名/aud/exp の完全検証はしていない)。
  主防御はCloudflare Accessのedge遮断。
- レート制限・監査ログは無い。
- 同時編集の競合検知は無い(最後に保存した内容で上書きされる)。
- `output:` フィールドのようなYAMLエスケープ不正があるcut_listは保存(setIn→toString)時に例外になる
  (§0参照)。読み込み専用の一覧表示は未検証。
