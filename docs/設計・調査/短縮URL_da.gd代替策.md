# 短縮URL：da.gd が消えた時の代替策（設計・すぐ構築できる手前まで）

作成：Claude Code
前提：案A（da.gdチェーン）導入済み。`最終URL → r2短縮(計測) → da.gdで短縮(表示) → 概要欄`。
弱点：**表示に出るのは da.gd。da.gdが終了/不調だと印字済みリンクが失効**（中間のr2・最終URLは生存）。

---

## 0. 結論（現時点の実装）

**すでに「差し替え可能なプロバイダ配列」として実装済み**（bluesky.js）。da.gdが不調になっても、**配列を並べ替える／差し替えるだけ**で新規発行分を別サービスに切替できる。既存の印字済みda.gdリンクは救済不可（＝下記「恒久対策」を将来実施）。

```js
// bluesky.js
var SHARE_SHORTENERS = [
  function (u) { return shortenVia('https://da.gd/s?url=', u); },                    // 1) da.gd
  function (u) { return shortenVia('https://tinyurl.com/api-create.php?url=', u); }  // 2) tinyurl（保険）
];
// shortenShare(u): 上から順に試し、最初に成功したものを共有URLに採用。全滅ならr2URL（長いが有効）に自動フォールバック。
```

- **切替方法（即実行できる）**：da.gdが死んだら、配列の1番目を別プロバイダに変える／削除するだけ。デプロイ（GitHub push＋バージョン上げ）で反映。
- ブラウザCORS確認済み：**da.gd（`Access-Control-Allow-Origin: *`）／tinyurl（OK）**。

---

## 1. 代替プロバイダ候補（差し替え用ストック）

| 優先 | プロバイダ | 呼び出し | URL長 | ブラウザCORS | 備考 |
|---|---|---|---|---|---|
| 現1位 | da.gd | `GET https://da.gd/s?url=` テキスト返却 | `da.gd/xxxx`≈16字 | ✅ `*` | 現行。無認証 |
| 現2位 | TinyURL | `GET https://tinyurl.com/api-create.php?url=` | `tinyurl.com/xxxxxxxx`≈28字 | ✅ | 長いが安定・保険 |
| 予備 | is.gd | `GET https://is.gd/create.php?format=simple&url=` | `is.gd/xxx`≈13字 | 要確認(未確認) | 2026-07時点サーバー障害中(`database insert failed`)。復活＆CORS確認後に採用可 |
| 予備 | cleanuri | `POST https://cleanuri.com/api/v1/shorten` (form) → `{result_url}` | `cleanuri.com/xxxxx`≈27字 | 要確認 | JSON応答。CORS未確認 |
| 予備 | spoo.me | POST | 短い | ✗ | Cloudflareにフィッシング判定→不可 |

> 採用条件：**①ブラウザから直接叩ける(CORS) ②無認証 or 軽い認証 ③直リダイレクト(プレビューページ無し)**。
> v.gd は使わない（デフォルトでプレビューページを挟む）。

---

## 2. 恒久対策（印字済みリンクも死なせない・要あなたの手動ワンステップ）

チェーン方式の根本弱点（外部フロント依存）を消すには、**独自の短いホストを r2 に Custom Domain 割当**する（別mdの案B）。これなら：
- 表示URL＝`https://<あなたのホスト>/xxxxx`（あなたの資産）＝**外部短縮に依存しない**
- 中間ホップ不要・r2計測は直
- da.gd等はフォールバックにだけ残す

構築の手前まで（あなたが起きてから）：
1. 無料ドメイン取得（pp.ua＝SMS認証・WHOIS公開注意 / is-a.dev＝GitHub PR・非商用規約注意）。詳細は `短縮URL_導入設計書.md` の案B。
2. Cloudflareにzone追加 → r2ワーカーに Custom Domain 追加（ここは私が wrangler で実施可）。
3. bluesky.js の `SHARE_SHORTENERS` を **独自ホスト短縮（自前r2の別コード）に置換 or 撤去**し、`USE_DAGD_CHAIN=false`＋WORKER_URL差し替えで「チェーンなし・短い独自URL・r2直計測」に移行。

> つまり：**今はda.gd（すぐ短い）→ 将来、独自ドメインが取れたらチェーンを外して恒久化**、という二段構え。移行時のコードポイントは `USE_DAGD_CHAIN` と `SHARE_SHORTENERS` と `WORKER_URL` の3点だけ。

---

## 3. すぐできる運用アクション早見

| 事象 | 対応（コードの触る場所） |
|---|---|
| da.gdが不調 | `SHARE_SHORTENERS` の1番目をtinyurl等に入替 → push＋バージョン上げ |
| チェーン自体をやめたい | `USE_DAGD_CHAIN = false`（表示がr2URLに戻る。計測は不変） |
| 独自ドメインが取れた | Custom Domain追加＋`WORKER_URL`差替＋`USE_DAGD_CHAIN=false`＋`SHARE_SHORTENERS`撤去 |
| is.gdが復活した | CORS確認後、`SHARE_SHORTENERS` 先頭付近に `is.gd '/create.php?format=simple&url='` を追加（最短13字） |
