# link-worker セットアップ手順（自前URL短縮）

TinyURL等の「Preview（中間）ページ」を完全に排除するため、**自分の Cloudflare Worker で短縮リンクを発行**します。
開くと 302 で即リダイレクト＝中間ページは出ません。クリック数も自前で計測できます（将来 Bitly を置換可能）。

> 既に `drive-worker/` をデプロイできているなら、同じ要領・同じ Cloudflare アカウントで5分です。

---

## 0. これは何をするか

- `POST /api/shorten` … 宛先URL（Blueskyの投稿URL）を渡すと短縮コードを発行して KV に保存し、短縮URLを返す。
- `GET /:code` … 保存先へ **302 即リダイレクト**（中間ページなし）。アクセス毎にクリックを概算カウント。
- `GET /api/stats?code=…&secret=…` … クリック数を返す（管理用）。

安全策（drive-worker と同方針の多層防御）：
- **宛先ホスト制限**（既定 `bsky.app,bsky.social`）。万一ソフト鍵が漏れても Bluesky 以外へ飛ばす踏み台にならない。
- 発行は **Origin制限＋共有シークレット＋日次レート制限**。
- `u:<code>`（コード→URL）は **不変**。既存の短縮リンクが後から書き換わることはない。
- 秘密の本体（`SHARED_SECRET`）は **Worker Secrets** のみ。コード/レスポンス/ログに出さない。

---

## 1. 前提

- Cloudflare アカウント（drive-worker と同じでOK）
- Node.js（`npx wrangler` を使う）

```bash
cd link-worker
npx wrangler login        # ブラウザでCloudflareにログイン（drive-workerと同じアカウント）
```

---

## 2. KV 名前空間を作成して id を貼る

コード→URL・クリック数・レート制限を **1つの KV** にまとめます。

```bash
npx wrangler kv namespace create LINKS
```

出力に表示される `id = "xxxxxxxx..."` を、`wrangler.toml` の以下へ貼り付け：

```toml
[[kv_namespaces]]
binding = "LINKS"
id = "PASTE_KV_NAMESPACE_ID"   # ← ここを置き換える
```

---

## 3. 共有シークレット（ソフト鍵）を登録

フロント（`bluesky.js` の `SHORT.SHARED_SECRET`）と**同じ値**にします。
drive-worker と同じ値を使い回してもOK（ソフト鍵のため）。別の値にしたい場合は両方を合わせること。

```bash
npx wrangler secret put SHARED_SECRET
# プロンプトに値を貼り付け（例：drive-worker と同じ文字列）
```

---

## 4. 設定の確認（wrangler.toml）

```toml
name = "go5-short"                          # ← フロント既定 URL が go5-short.<アカウント>.workers.dev 前提
ALLOWED_ORIGIN = "https://john-mori.github.io"
ALLOWED_HOSTS  = "bsky.app,bsky.social"     # FANZA等も短縮したいなら ,video.dmm.co.jp を足す／全許可は "*"
DAILY_LIMIT    = "500"
```

> `name` を変えた場合、または別アカウントの場合は、発行されるURL（`<name>.<アカウント>.workers.dev`）に合わせて
> フロント `bluesky.js` の `SHORT.WORKER_URL` も直すこと（または端末の localStorage `short_worker_url` で上書き）。

---

## 5. デプロイ

```bash
npx wrangler deploy
```

成功すると `https://go5-short.<アカウント>.workers.dev` が払い出されます。

### 動作確認

```bash
# ヘルス
curl https://go5-short.<アカウント>.workers.dev/            # → go5-short ok

# 短縮（Origin と Secret が必要）
curl -X POST https://go5-short.<アカウント>.workers.dev/api/shorten \
  -H "Origin: https://john-mori.github.io" \
  -H "X-Shared-Secret: <SHARED_SECRET>" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  --data-urlencode "url=https://bsky.app/profile/xxx.bsky.social/post/abc"
# → {"ok":true,"code":"...","short":"https://go5-short.../xxxxxxx","url":"..."}

# 短縮URLを開くと 302 で Bluesky へ即リダイレクト（中間ページなし）
curl -I https://go5-short.<アカウント>.workers.dev/xxxxxxx   # → HTTP/2 302, location: https://bsky.app/...
```

---

## 6. フロント側を合わせる（bluesky.js）

`bluesky.js` の短縮設定（`shortenUrl` 直前の `SHORT`）：

```js
var SHORT = {
  WORKER_URL: "https://go5-short.trustsignalbot.workers.dev",  // ← 実際の払い出しURLに合わせる
  SHARED_SECRET: "（Worker の SHARED_SECRET と同じ）",
};
```

- 既定値のまま（`name=go5-short`・同アカウント・同シークレット）なら **編集不要**でそのまま動きます。
- 変更後は `index.html` の `?v=` を1つ上げて push（GitHub Pages へ反映）。

> 未デプロイでも安全：Worker への接続に失敗したら自動で is.gd → cleanuri → 長いURL の順にフォールバックします。

---

## 7. クリック数の確認

```bash
curl "https://go5-short.<アカウント>.workers.dev/api/stats?code=xxxxxxx&secret=<SHARED_SECRET>"
# → {"ok":true,"code":"xxxxxxx","exists":true,"clicks":12}
```

※KVカウンタは概算（厳密な同時加算ではない）。個人運用の規模なら十分です。
将来、この値を GAS の記録シートへ流し込めば Bitly を置き換えられます（別タスク）。

---

## 8. やらないこと（安全のため）

- 既存リンク（`u:<code>`）の上書き・削除APIは実装していない（壊れない設計）。
- 宛先ホストは `ALLOWED_HOSTS` 限定。許可外URLは `host_not_allowed` で拒否。
