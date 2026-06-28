# URL短縮システム 汎用仕様書（link-worker / Cloudflare Workers）

> **このドキュメントの目的（for AI / 開発者）**
> 自前URL短縮システム「link-worker」を **任意のプロジェクトへ独立して流用**するための完全仕様書。
> このファイル1枚（＋同梱の `src/index.js`・`wrangler.toml`）だけで、新しいプロジェクト用に
> **互いに干渉しない短縮インスタンス**を一から構築・デプロイできるように書いてある。
>
> **AIへの指示**：新プロジェクトに導入するときは、まず「§4 独立性の原則」を最優先で読み、
> プロジェクトごとに必ず別にする項目（Worker名・KV・SHARED_SECRET・ALLOWED_ORIGIN・ALLOWED_HOSTS）
> を取り違えないこと。**既存プロジェクトの Worker/KV/secret を絶対に再利用・共有しない**。

---

## 1. 何をするシステムか

Cloudflare Workers（無料枠）＋ Workers KV だけで動く、**完全自前のURL短縮**。サーバー常設不要。

- **`POST /api/shorten`**：長いURLを渡すと短縮コードを発行し、短縮URLを返す（ブラウザから直接叩ける＝CORS対応）。
- **`GET /<code>`**：**302で即リダイレクト**（広告的な「中間プレビューページ」が原理的に出ない）＋クリック概算カウント。
- **`GET /api/stats`**：コード別のクリック数を返す（自前のクリック計測＝外部計測サービス不要）。
- 短縮コードは**決定的（同じURLは常に同じコード）かつ不変**（一度発行したリンクは永久に同じ宛先）。

### 主な用途
SNS投稿に貼るリンク、説明欄に載せるリンク、記録シートに残すリンクなどを **短く・自前計測付き・中間ページなし**で扱いたいとき。

---

## 2. なぜ自前か（外部サービスとの比較・採否判断）

| 方式 | 短さ | 中間ページ | 自前クリック計測 | デプロイ要否 | ブラウザCORS |
|---|---|---|---|---|---|
| **link-worker（本システム・workers.devドメイン）** | △ 長い※ | ✅ 無し(302) | ✅ あり | 要（Cloudflare） | ✅ 自前設定で確実 |
| **link-worker（独自の短いドメインを付与）** | ✅ 短い | ✅ 無し(302) | ✅ あり | 要＋ドメイン | ✅ |
| da.gd（外部・無料） | ✅ 短い(`da.gd/xxxxx`) | 無し | ✗ | 不要 | ✅（`ACObgin:*`） |
| TinyURL（外部・無料） | △ | △ プレビュー有のことあり | ✗ | 不要 | △ Origin反射＝不安定 |
| is.gd / v.gd / cleanuri | ✅/△ | 無し | ✗ | 不要 | ❌ **CORSヘッダ無し＝ブラウザ不可** |

> ※ **重要な制約**：Worker 既定ドメイン `https://<name>.<account>.workers.dev/<code>` は**約50字と長い**。
> 「URLを短くしたい」が主目的なら、(a) 外部の **da.gd** を使う、(b) link-worker に**短い独自ドメイン**を付ける、のどちらか。
> link-worker の独自価値は **「自前クリック計測」「中間ページ無し」「コード不変」「宛先制限による安全」**。

**推奨フォールバック構成（フロント側）**：`link-worker（短い独自ドメインがある時）→ da.gd → 短縮失敗なら元の長いURL`。
is.gd / cleanuri はブラウザCORS不可なのでフォールバックに使わない。

---

## 3. アーキテクチャ

### 3.1 ルート
| メソッド/パス | 役割 | 認証 |
|---|---|---|
| `POST /api/shorten` | 短縮コード発行・KV保存・短縮URL返却 | Origin制限＋`X-Shared-Secret` |
| `GET /<code>` | 宛先へ302リダイレクト＋クリック+1 | なし（公開リンク） |
| `GET /api/stats?code=&secret=` | クリック数取得 | `secret`クエリ |
| `GET /` | ヘルスチェック（`"<name> ok"` 等の文字列） | なし |

### 3.2 KVレイアウト（単一 namespace。binding 名は `LINKS`）
| キー | 値 | 性質 |
|---|---|---|
| `u:<code>` | 宛先URL | **不変**（一度書いたら上書きしない＝既存リンクが壊れない） |
| `c:<code>` | クリック数 | GET毎に+1（概算・eventually consistent） |
| `rl:<UTC日付>` | 当日の発行カウンタ | レート制限用・TTL 2日で自動失効 |

### 3.3 コード生成（決定的・冪等・不変）
- `SHA-256(url)` → 各バイトを base62 へ写像し最大12文字の候補を作る。
- 既定で先頭 **7文字**を採用（62^7 ≈ 3.5兆通り）。
- 同じURLは常に同じコード＝**重複発行されない（冪等）**。万一別URLが同コードを占有していたら1文字ずつ伸ばして再試行（最大12文字）。
- 一度 `u:<code>` に書いた宛先は**変更しない**＝発行済みリンクは恒久的に同じ場所へ飛ぶ。

### 3.4 多層防御（セキュリティ）
1. **Origin制限**：`/api/shorten` は `ALLOWED_ORIGIN` と完全一致する Origin のみ許可（ワイルドカード不可）。
2. **共有シークレット**：`X-Shared-Secret` ヘッダが `SHARED_SECRET` と一致しないと発行不可（＝ソフト鍵）。
3. **宛先ホスト制限**：`ALLOWED_HOSTS` のドメインにしか短縮を許さない。万一ソフト鍵が漏れても**オープンリダイレクタ（踏み台）にならない**。`"*"` で全許可も可能だが非推奨。
4. **日次レート制限**：`DAILY_LIMIT`（既定500）/日で発行を制限。
5. **秘密の本体は Worker Secrets**：`SHARED_SECRET` は wrangler secret に保存し、コード・レスポンス・ログに出さない。

---

## 4. ★ 独立性の原則（複数プロジェクトで干渉させないために）★

> **このシステムの「流用」とは、コードを共有してインスタンスは分けること。**
> 各プロジェクトは **専用の Worker＋専用の KV＋専用のシークレット** を持つ。
> こうすれば、あるプロジェクトの短縮コード・クリック数・設定・障害が、他プロジェクトに一切影響しない。

### 4.1 共有するもの（テンプレートとして使い回す）
- `src/index.js`（ロジック本体。原則**無改変**でコピー）
- `wrangler.toml`（**雛形**としてコピーし、下記の値を埋め替える）
- 本仕様書

### 4.2 プロジェクトごとに必ず「別」にするもの（取り違え厳禁）
| 項目 | 例（プロジェクトA / B） | なぜ別にするか |
|---|---|---|
| **Worker名**（`wrangler.toml` の `name`） | `projA-short` / `projB-short` | デプロイ先・URLが分かれる |
| **KV namespace**（`wrangler kv namespace create LINKS` を各自で作成し `id` を貼る） | 別ID / 別ID | **コードもクリック数も完全分離**（衝突・混在しない） |
| **SHARED_SECRET**（`wrangler secret put`） | 別の乱数 / 別の乱数 | 片方が漏れても他方は無事。波及しない |
| **ALLOWED_ORIGIN** | Aのフロントのorigin / Bのorigin | 他サイトから発行されない |
| **ALLOWED_HOSTS** | Aが飛ばす宛先 / Bが飛ばす宛先 | 各プロジェクトの意図した宛先だけに限定 |
| **独自ドメイン**（任意） | 別ドメイン / 別ドメイン | 短縮URLのブランドも分離 |

### 4.3 やってはいけない（アンチパターン）
- ❌ **複数プロジェクトで同じ KV namespace を共有**する（コード空間とクリック計測が混ざる。`u:<code>` 衝突で別プロジェクトの宛先が出る事故）。
- ❌ **1つの Worker を複数プロジェクトで使い回す**（Origin/宛先制限が両立できず、片方の都合で他方が壊れる）。
- ❌ **SHARED_SECRET を複数プロジェクトで共用**する（1つ漏れると全滅）。
- ✅ 正解＝**1プロジェクト = 1 Worker = 1 KV = 1 secret**。コードだけ共通。

---

## 5. API リファレンス

### POST /api/shorten
- ヘッダ：`X-Shared-Secret: <SHARED_SECRET>`（必須）、`Origin: <ALLOWED_ORIGIN>`（ブラウザは自動付与）
- ボディ：`application/x-www-form-urlencoded` の `url=<長いURL>`（推奨＝プリフライト回避） or JSON `{"url":"..."}`
- 成功(200)：`{ "ok": true, "code": "ZAXJ9bt", "short": "https://.../ZAXJ9bt", "url": "<元URL>" }`
- 失敗：`origin_not_allowed`(403) / `bad_secret`(401) / `host_not_allowed`(400) / `rate_limited`(429) / `bad_input`(400) / `kv_unbound`(500)

### GET /<code>
- 200ではなく **302** を返し、`Location: <宛先URL>`、`Cache-Control: no-store`。存在しないコードは404。

### GET /api/stats?code=<code>&secret=<SHARED_SECRET>
- 成功(200)：`{ "ok": true, "code": "...", "exists": true, "clicks": 12 }`
- 失敗：`bad_secret`(401) / `missing_code`(400) / `kv_unbound`(500)

### GET /
- `200` ＋本文 `"<name> ok"`（ヘルスチェック）

---

## 6. 新プロジェクトへのデプロイ手順（パラメータ化）

> プレースホルダ：`<PROJECT>`＝プロジェクト識別子、`<WORKER_NAME>`＝`<PROJECT>-short` 等、
> `<FRONTEND_ORIGIN>`＝そのプロジェクトの公開サイトorigin、`<ALLOWED_HOSTS>`＝短縮を許す宛先（カンマ区切り）。

### 前提
- Node.js、Cloudflare アカウント。`npx wrangler login`（ブラウザで認可）。

### 手順
1. **`link-worker/` フォルダを新プロジェクトへコピー**（`src/index.js` は無改変でOK）。
2. `wrangler.toml` を編集（§付録B 雛形参照）：
   - `name = "<WORKER_NAME>"`
   - `ALLOWED_ORIGIN = "<FRONTEND_ORIGIN>"`（例 `https://example.github.io`）
   - `ALLOWED_HOSTS = "<ALLOWED_HOSTS>"`（例 `youtube.com,youtu.be`。**計測を壊したくない宛先＝アフィリエイト等は入れない**＝後述§8）
   - `DAILY_LIMIT` は必要に応じて
3. **専用KVを作成**して `id` を貼る（**プロジェクトごとに新規作成**）：
   ```bash
   npx wrangler kv namespace create LINKS
   # 出力された id を wrangler.toml の [[kv_namespaces]] id に貼る
   ```
4. **デプロイ**：
   ```bash
   npx wrangler deploy
   # → https://<WORKER_NAME>.<account>.workers.dev が表示される（控える）
   ```
5. **専用シークレットを登録**（プロジェクトごとに別の乱数）：
   ```bash
   # 乱数生成例：
   node -e "console.log(require('crypto').randomBytes(24).toString('base64url'))"
   # 登録（対話 or パイプ）：
   echo "<生成した値>" | npx wrangler secret put SHARED_SECRET
   ```
6. **（任意）短い独自ドメインを付与**：Cloudflareにそのドメインを追加 → Workers のカスタムドメイン/ルートに `<WORKER_NAME>` を割当。これで短縮URLが `https://<短いドメイン>/<code>` になる。
7. **スモークテスト**（`<U>`=Worker URL、`<S>`=SHARED_SECRET、`<O>`=ALLOWED_ORIGIN）：
   ```bash
   curl -s "<U>/"                                                   # → "<WORKER_NAME> ok"
   curl -s -X POST -H "Origin: <O>" -H "X-Shared-Secret: <S>" \
        -F "url=https://<許可ホストのURL>" "<U>/api/shorten"        # → {"ok":true,"short":...}
   curl -s -X POST -H "Origin: <O>" -F "url=..." "<U>/api/shorten"  # → bad_secret(401)
   curl -s -X POST -H "Origin: <O>" -H "X-Shared-Secret: <S>" \
        -F "url=https://非許可ホスト/" "<U>/api/shorten"            # → host_not_allowed(400)
   curl -s -o /dev/null -D - "<U>/<発行されたcode>" | grep -i location  # → 302 + Location
   ```

---

## 7. フロント連携（ブラウザからの利用）

### 7.1 設定値の置き場所
- `WORKER_URL`（＝Worker URL）と `SHARED_SECRET` は**フロントに置く前提のソフト鍵**（公開されても、宛先制限＋Origin制限＋レート制限で実害を抑える設計）。
- 端末ごとに上書きしたい場合は `localStorage` 経由でも可。

### 7.2 短縮関数（フォールバック付き・コピペ可）
```js
// link-worker優先 → da.gd（CORS確実な外部・短い）→ 失敗なら元URL。
// WORKER_URL/SECRET 未設定や非許可ホストのときは自動でda.gdへ。
async function shortenUrl(longUrl, cfg) {
  if (!longUrl) return '';
  cfg = cfg || {};
  // 1) 自前 link-worker（設定がある時だけ）
  if (cfg.workerUrl && cfg.secret) {
    try {
      const r = await fetch(cfg.workerUrl.replace(/\/$/, '') + '/api/shorten', {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded', 'X-Shared-Secret': cfg.secret },
        body: 'url=' + encodeURIComponent(longUrl)
      });
      const j = await r.json();
      if (j && j.ok && j.short) return j.short;
    } catch (e) { /* fallthrough */ }
  }
  // 2) da.gd（ACAO:* で全ブラウザ確実・結果が短い）
  try {
    const r = await fetch('https://da.gd/s?url=' + encodeURIComponent(longUrl));
    const t = (await r.text()).trim();
    if (/^https?:\/\//.test(t)) return t;
  } catch (e) { /* fallthrough */ }
  // 3) 最後は元URL（リンク自体は有効）
  return longUrl;
}
```

### 7.3 CORS要件
- `/api/shorten` は **`Content-Type: application/x-www-form-urlencoded`** か `application/json`。`X-Shared-Secret` を付けるため**プリフライト(OPTIONS)が飛ぶ**が、Workerが204で許可を返す（実装済）。
- Originは `ALLOWED_ORIGIN` と**完全一致**必須（`http://localhost:...` で試すなら一時的に許可するか da.gd 経由でテスト）。

---

## 8. セキュリティ・不変条件（流用時も厳守）

1. **`u:<code>` は不変**：発行済みコードの宛先を書き換えない（既存の短縮リンクが別の場所へ飛ぶ事故を防ぐ）。コード上も「既存があれば上書きしない」実装。
2. **`ALLOWED_HOSTS` を最小に**：踏み台（オープンリダイレクタ）防止。`"*"` は避け、本当に飛ばす宛先だけ列挙。
3. **計測・トラッキング付きURLは短縮しない**：アフィリエイトリンク等、URL自体にトラッキングIDが入るものは**生のまま使う**（短縮や改変で計測が壊れる）。→ そういう宛先は `ALLOWED_HOSTS` に**入れない**ことで二重に防ぐ。
4. **SHARED_SECRET はソフト鍵**：本当の防御はOrigin＋宛先制限＋レート制限。漏れたら `wrangler secret put` で**ローテーション**（既存リンクは無影響＝発行APIの鍵が変わるだけ）。
5. **秘密をコミットしない**：`SHARED_SECRET` は Worker Secrets のみ。`.gitignore` に `.wrangler/` 等。KV id は秘密ではない（公開toml可）。

---

## 9. 運用・制限の目安
- **Workers/KV 無料枠**：個人運用には十分（KV読み書き・Worker呼び出しに日次上限あり）。大量になれば有料へ。
- **クリック数は概算**：KVは結果整合性。GET毎に+1するがエッジ分散のため厳密ではない。傾向把握用。
- **短縮URLの長さ**：workers.devは長い（§2※）。短くしたいなら独自ドメイン or da.gd。
- **コード衝突**：SHA-256ベースで実質ほぼ無い。発生しても自動で桁を伸ばす。

---

## 付録A. 完全ソース `src/index.js`
> このまま新プロジェクトへコピーしてよい（**ロジックは無改変が原則**。設定は wrangler.toml/secret 側で行う）。
> 実体は同梱の `link-worker/src/index.js` を参照（本仕様書と同じフォルダ）。要点：
> ルート分岐 → `handleShorten`（secret/レート/入力/host/コード発行）→ `handleRedirect`（302）→ `handleStats`。
> ヘルパ：`codeFor`(SHA-256→base62)、`hostAllowed`、`bumpClick`、`rateLimited`、CORS群。

## 付録B. `wrangler.toml` 雛形
```toml
name = "<WORKER_NAME>"            # 例: projX-short （プロジェクトごとに別）
main = "src/index.js"
compatibility_date = "2024-11-01"

[vars]
ALLOWED_ORIGIN = "<FRONTEND_ORIGIN>"        # 例: https://example.github.io（完全一致・ワイルドカード不可）
ALLOWED_HOSTS  = "<ALLOWED_HOSTS>"          # 例: youtube.com,youtu.be （"*"は非推奨／トラッキングURLは入れない）
DAILY_LIMIT    = "500"

[[kv_namespaces]]
binding = "LINKS"
id = "<KV_NAMESPACE_ID>"                     # `wrangler kv namespace create LINKS` で発行（プロジェクトごとに別）

# Secrets（コマンドで登録・ここには書かない）:
#   wrangler secret put SHARED_SECRET        # プロジェクトごとに別の乱数
```

## 付録C. 新プロジェクト導入チェックリスト（AI/人間共通）
- [ ] `link-worker/` をコピーした（`src/index.js` 無改変）
- [ ] `name` をこのプロジェクト専用に変えた
- [ ] **専用KVを新規作成**して `id` を貼った（他プロジェクトのKVを使い回していない）
- [ ] `ALLOWED_ORIGIN` をこのプロジェクトの公開originにした
- [ ] `ALLOWED_HOSTS` を最小化した（トラッキング/アフィリエイトURLは入れない）
- [ ] `npx wrangler deploy` 成功・URL控えた
- [ ] **専用の SHARED_SECRET（別乱数）** を `wrangler secret put` した
- [ ] スモークテスト（健康/発行/bad_secret/host_not_allowed/302）全通過
- [ ] フロントに WORKER_URL＋SHARED_SECRET を設定（§7）／フォールバックに da.gd
- [ ] （任意）短い独自ドメインを割当
- [ ] **他プロジェクトの Worker/KV/secret を共有していない**ことを再確認（§4）

---

### 参考：このシステムの初出インスタンス（5秒動画メーカー）
- Worker：`go5-short`（`https://go5-short.<account>.workers.dev`）／KV binding `LINKS`／`ALLOWED_HOSTS=bsky.app,bsky.social,youtube.com,youtu.be`。
- 同プロジェクトでは **link-worker を一次（primary）短縮として採用**（YouTube説明欄リンク等の開封数を自前計測）／**da.gd を保険フォールバック**に置く構成（§7.2 のパターン）。GitHub Actions で Worker を自動デプロイ。
- この実例の固有値（URL/secret/KV id）は**このプロジェクト専用**。流用時は §4 の通り全て別物を用意すること。最新の実状はリポジトリの `STATUS.md` を参照。
