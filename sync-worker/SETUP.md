# sync-worker セットアップ手順（全端末クラウド同期の土台）

このworkerは「素材(候補)・設定・投稿履歴・暗号化した鍵」を全端末で同期するための保管庫です。
状態JSONは **KV**、画像(漫画ページ等)は **R2** に置きます。`/api/*` は **X-Sync-Token** で保護します。

> ★ 鍵(アプリPW等)は**クライアント側でパスフレーズ暗号化してから**送られます。このworkerは
>   平文の鍵を一切扱いません＝SYNC_TOKEN が漏れても暗号文しか取れません。

## 前提
- Cloudflareアカウント（既存 link-worker / drive-worker と同じでOK）
- `wrangler` CLI（既存workerで導入済みのはず）

## 手順

### 1. このフォルダへ移動
```
cd sync-worker
```

### 2. KV namespace を作成 → id を wrangler.toml に貼る
```
wrangler kv namespace create SYNC
```
出力の `id = "……"` を `wrangler.toml` の `[[kv_namespaces]] binding = "SYNC"` の `id` に貼り付ける。

### 3. R2 バケットを作成
```
wrangler r2 bucket create go5-sync-images
```
（`wrangler.toml` の `bucket_name` と一致していること）

### 4. 同期トークンを登録（クライアントに入れる値と同じにする）
十分に長いランダム文字列を1つ決めて登録：
```
wrangler secret put SYNC_TOKEN
```
※この値は後で アプリの「⚙詳細設定 → クラウド同期」に入れます。

### 5. 許可Originを確認（必要なら編集）
`wrangler.toml` の `ALLOWED_ORIGINS`。本番だけなら `https://john-mori.github.io`。
ローカル検証もするなら `https://john-mori.github.io,http://localhost:8124` のように足す。

### 6. デプロイ
```
wrangler deploy
```
払い出しURL（例 `https://go5-sync.<サブドメイン>.workers.dev`）を控える。

### 7. 動作確認
```
curl https://go5-sync.<サブドメイン>.workers.dev/            # → go5-sync ok
curl -H "X-Sync-Token: <登録した値>" https://go5-sync.<...>.workers.dev/api/pull
# → {"ok":true,"empty":true,"version":0}
```

## アプリ側の設定（クライアント実装後）
「⚙詳細設定 → クラウド同期」に：
- 同期worker URL（手順6のURL）
- 同期トークン（手順4の値）
- パスフレーズ（鍵の暗号化用。全端末で同じ文字列を入力＝鍵はこれで復号される）

を入れると、その端末が自動同期に参加します。

## 設計メモ
- 状態は KV `state:doc`（blob）＋ `state:meta`（version/updatedAt/device）。
  push は `baseVersion` を送り、現行versionと不一致なら `conflict` を返す＝クライアントが再pull→マージ→再push（後勝ち＋候補はcidマージ）。
- 画像は sha256(hex) キー。`PUT /api/img/:key` は既存なら再保存しない（冪等）。表示は `GET /img/:key`（トークン不要・不変・長期キャッシュ）。
- レート制限は KV 日次カウンタ（`DAILY_CAP`）。
- **このworkerは非破壊寄り**：状態は上書き保存（versionで安全化）、画像は作成のみ・削除APIなし。
