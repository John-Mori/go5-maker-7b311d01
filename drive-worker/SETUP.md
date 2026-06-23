# Google Drive 自動保存 セットアップ手順（Cloudflare Worker）

動画作成ボタンを押すと、生成した動画と元画像を **マイドライブ/AFI5秒動画/[チャンネル]/[動画名]/** に自動保存します。
スマホ・PCどちらからでも同じ動き。サーバーは Cloudflare Workers（無料枠）。

> **安全保証（このツールが絶対にしないこと）**
> Google Drive 上の既存フォルダ・ファイルを **削除・上書き・移動・改名しません**。
> 行うのは「フォルダの新規作成」「ファイルの新規アップロード」「参照（読み取り）」だけです。
> 同名があっても既存には触れず `_2, _3…` の別名で新規作成します。
> （Worker のコードに削除・上書き系 API は1つも含まれていません。`grep` で確認できます＝下記「安全確認」。）

所要時間：初回のみ 約15〜20分。2回目以降は何もせず自動です（認証画面も出ません）。

---

## 0. 用意するもの
- このフォルダ（`スマホ版/drive-worker/`）
- Node.js（`node -v` で確認。無ければ https://nodejs.org からLTSをインストール）
- Google アカウント（保存先の Drive を持っているアカウント）
- Cloudflare アカウント（無料。https://dash.cloudflare.com で作成）

---

## 1. Google Cloud：プロジェクトと Drive API

1. https://console.cloud.google.com を開く（保存先Driveと同じGoogleアカウントでログイン）。
2. 画面上部のプロジェクト選択 →「新しいプロジェクト」→ 名前 `go5-drive` →「作成」。作成後、そのプロジェクトを選択。
3. 左上「≡」メニュー →「APIとサービス」→「ライブラリ」。検索窓に `Google Drive API` →クリック →「**有効にする**」。

## 2. OAuth 同意画面（認証画面を以後出さないために「公開」する）

1. 左メニュー「APIとサービス」→「**OAuth同意画面**」。
2. User Type は「**外部**」→「作成」。
3. アプリ情報：アプリ名 `go5-drive`、ユーザーサポートメール＝自分、デベロッパー連絡先＝自分 →「保存して次へ」。
4. スコープ：ここでは何もせず「保存して次へ」（スコープはトークン取得時に要求します）。
5. テストユーザー：自分のメールを「ADD USERS」で追加 →「保存して次へ」→「ダッシュボードに戻る」。
6. ダッシュボードで「**アプリを公開**（PUBLISH APP）」→「確認」。
   - 状態が「**本番環境（In production）**」になればOK。これで refresh_token が失効しなくなります（テスト状態だと7日で切れます）。
   - スコープは `drive` のみ。Google の審査は不要（個人利用・本人アカウントのため、確認画面に「未確認アプリ」と出ても自分のアプリなので「続行」で進めます）。

## 3. OAuth クライアント（ウェブアプリ）を作成

1. 「APIとサービス」→「**認証情報**」→「**認証情報を作成**」→「**OAuth クライアント ID**」。
2. アプリケーションの種類：「**ウェブアプリケーション**」。名前 `go5-drive-local`。
3. 「**承認済みのリダイレクト URI**」→「URI を追加」→ 次を**そのまま**貼る：
   ```
   http://localhost:53682/oauth2callback
   ```
4. 「作成」→ ダイアログの「**JSON をダウンロード**」。
5. ダウンロードしたファイルを、**このフォルダ（drive-worker）** に `client_secret.json` という名前で保存。

## 4. refresh_token を取得（スクリプト1回実行）

このフォルダで（PowerShell でもターミナルでも可）：
```bash
node get-refresh-token.mjs
```
- 自動でブラウザが開きます（開かなければ表示されたURLを自分で開く）。
- 保存先Driveのアカウントを選び、「続行 / 許可」。
- 画面とターミナルに **refresh_token** が出ます。次の手順6で使うのでコピーしておく。
- `client_secret.json` と refresh_token は **絶対にコミットしない**（`.gitignore` 済み）。

## 5. 保存先フォルダの ID を調べる

Drive をブラウザで開き、各チャンネルのフォルダを開いて、アドレスバーの URL を見ます：
```
https://drive.google.com/drive/folders/1AbCdEf… ←この「folders/」の後ろがフォルダID
```
- 「月詠み色恋劇場」フォルダのID → 手順7の `FOLDER_ID_ACC1`
- 「宵桜艶帖～Yoizakura Tsuyacho～」フォルダのID → `FOLDER_ID_ACC2`
- ※ 念のため、両フォルダが **AFI5秒動画** の中にあることを確認。

## 6. Cloudflare：ログインと KV 作成

このフォルダで：
```bash
npx wrangler login          # ブラウザでCloudflareにログイン許可
npx wrangler kv namespace create RL
```
- 最後のコマンドが出力する `id = "xxxxxxxx..."` を、`wrangler.toml` の
  `[[kv_namespaces]]` の `id = "PUT_KV_ID_HERE"` に貼り替える。

## 7. `wrangler.toml` を編集（フォルダID）

`wrangler.toml` を開いて、手順5のIDを貼る：
```toml
FOLDER_ID_ACC1 = "ここに月詠み色恋劇場のID"
FOLDER_ID_ACC2 = "ここに宵桜艶帖のID"
```
`ALLOWED_ORIGIN` は `https://john-mori.github.io` のままでOK。

## 8. Secrets を登録（秘密は全部ここ。コードにもrepoにも残さない）

このフォルダで4回実行。プロンプトに値を貼り付け：
```bash
npx wrangler secret put GOOGLE_CLIENT_ID       # client_secret.json の client_id
npx wrangler secret put GOOGLE_CLIENT_SECRET   # client_secret.json の client_secret
npx wrangler secret put GOOGLE_REFRESH_TOKEN   # 手順4で取得した refresh_token
npx wrangler secret put SHARED_SECRET          # 自分で決める長いランダム文字列（例: 32文字以上）
```
- `client_id` / `client_secret` は `client_secret.json` の中（`"client_id"`, `"client_secret"`）。
- `SHARED_SECRET` は適当な長い文字列を自分で作って入れる（フロントにも同じ値を入れる＝手順10）。

## 9. デプロイ

```bash
npx wrangler deploy
```
- 成功すると `https://go5-drive-saver.xxxxx.workers.dev` のような **Worker URL** が表示されます。控える。

## 10. フロントに Worker URL と SHARED_SECRET を設定

`スマホ版/drive-upload.js` の先頭 `CFG` を編集：
```js
WORKER_URL: "https://go5-drive-saver.xxxxx.workers.dev",  // 手順9のURL
SHARED_SECRET: "手順8で決めたSHARED_SECRETと同じ値",
```
- これらは公開サイトに載る前提の「ソフトな鍵」です（本当の防御は Worker 側の Origin制限＋レート制限＋最小操作）。
- repo に秘密を置きたくない場合は、代わりにスマホ/PCのブラウザで一度だけ：
  ```js
  localStorage.setItem('drive_worker_url','https://...workers.dev');
  localStorage.setItem('drive_shared_secret','SHARED_SECRETの値');
  ```
  （ただし端末ごとに設定が必要。全端末で自動にしたいならファイルに直接書くのが簡単）

設定したら、`index.html` のアセット `?v=` を1つ上げて GitHub Pages へ push（公開反映）。

---

## 11. テスト（本番フォルダの前に、まず捨てフォルダ推奨）

1. まず Drive に「テスト用」フォルダを作り、その ID を一時的に `FOLDER_ID_ACC1` に入れて `npx wrangler deploy`。
2. サイトでアカウント①を選び、適当な画像＋タイトルで「動画を作成」。
3. テスト用フォルダ内に `タイトル/タイトル.mp4 ＋ 画像` ができることを確認。
4. もう一度同じタイトルで作成 → `タイトル_2/` が新規作成される（既存に触れない）ことを確認。
5. 問題なければ `FOLDER_ID_ACC1` を本番（月詠み）に戻して再デプロイ。

## 安全確認（破壊系APIが無いことの証明）

このフォルダで：
```bash
grep -nE "files.delete|files.update|trashed|removeParents|addParents" src/index.js
```
- **何も出なければOK**（削除・上書き・移動・改名系を一切呼んでいない）。

---

## トラブルシュート
- **refresh_token が出ない**：https://myaccount.google.com/permissions で `go5-drive` のアクセスを一度削除し、`node get-refresh-token.mjs` を再実行。
- **保存されない / 401 bad_secret**：フロントの `SHARED_SECRET` と Worker の Secret が一致しているか。
- **403 origin_not_allowed**：`ALLOWED_ORIGIN` が公開URLのOrigin（`https://john-mori.github.io`）と一致しているか。
- **400 parent_folder_not_found**：`FOLDER_ID_ACC1/2` が正しいか（URLの folders/ の後ろ）。
- **400 channel_unresolved**：サイトでアカウント①/②が選択されているか。
- **429 rate_limited**：その日の上限（既定100）。`DAILY_LIMIT` を上げて再デプロイ。
- **Service Accountは使いません**：個人Gmailのマイドライブに保存できないため、本人OAuth（refresh_token）方式です。

## 秘密情報の置き場所まとめ
| 情報 | 置き場所 | repo/フロントに出る？ |
|---|---|---|
| client_id / client_secret / refresh_token | Cloudflare Worker Secrets | 出ない |
| SHARED_SECRET | Worker Secrets ＋ フロント（ソフト鍵） | フロントには出る（許容） |
| client_secret.json | ローカルのみ（.gitignore済） | 出ない |
| フォルダID | wrangler.toml（公開しても害は小） | repoに出てよい |
