---
paths:
  - "bluesky*.js"
  - "gas/**"
  - "link-worker/**"
  - "scheduler.js"
  - "integration.js"
---

> ★この章は `CLAUDE.md` から移した。**内容は変えていない**(2026-08-29・研究室HQ)。
> 毎便の固定費(床)を下げるため、上の `paths` に当たるファイルを触る時だけ読み込まれる。

# 投稿(§9)と記録・クリック集計(§10)の要点

### Bluesky 投稿(§9 機能)の要点(★現運用では非経路=上の注記参照。アプリ機能仕様として残置)
- 完全クライアントサイド。`https://bsky.social` の XRPC を直接叩く(CORS対応・サーバー不要)。認証は**アプリパスワード**(通常PWではない／revoke 可能)。
- フロー：`app.js` の `make()` 成功時に `video-created` を dispatch → `bluesky.js` が購読 → 確認ダイアログ → `#cv` の最終フレームを JPEG 圧縮(≤約950KB)→ `blueskyPostWithImage()`。
- 画像 embed(`app.bsky.embed.images`)と外部リンクカードは併用不可のため、**作品URLは本文に richtext#link facet 付きで入れる**(facet の index は **UTF-8 バイトオフセット**)。
- 設定の localStorage キー：`bsky_enable` / `bsky_text`(本文1ボックス) / `bsky_handle` / `bsky_app_pw` / `bsky_gas_url` / `bsky_gas_secret`。位置調整は `preview_*`(`preview_band_pad`・`preview_row_gap` を追加)。
- 投稿は `BlueskyCore.blueskyPostRaw({identifier,appPassword,text,imageBlob,alt})`＝本文そのまま投稿＋`detectFacets` で本文中URLを自動リンク化。旧 `buildBlueskyPost`/`blueskyPostWithImage` も残置(互換・テスト用)。
- 秘匿情報(アプリパスワード・af_id・シークレット)は **console に出さない**(既存方針を踏襲)。

### 投稿記録＆クリック集計(§10 機能)の要点
- **クリック数＝投稿の短縮URLの開封数**(★Bitlyは全廃・現在は自前 link-worker＝2026-07-20確認)。本文の作品リンク/セール会場リンクは**どちらも最終投稿時には短縮リンク**(★旧記述「生のまま(無改変)」は誤り)。作品リンクは編集中は生アフィリンク表示だが、**投稿直前に `measureWorkLink_` が短縮へ差し替える**(今すぐ/予約/無人予約/動画後自動の全経路)。短縮は302素通し(Locationに完全URL)なので **af_id は保持され計測は壊れない**。アフィリンクのクリック実数は取得不可(FANZA 管理画面が正)。
- 投稿の共有URLは `at://…/<rkey>` から `https://bsky.app/profile/<handle>/post/<rkey>` を組み立て(`bluesky-core.js`)。
- クライアントは GAS Web App へ `{channel,title,postUrl,affiliateUrl,workUrl,hashtags,postUri}` を **Content-Type無指定の POST**(＝simple request でプリフライト回避)。★共有URLの短縮は**クライアント側**(`shortenAndShow`→`makeShortAndShare`)が投稿直後に行い、GASへは**短縮済みの値**を送る。GASはシート追記が主で、短縮値が来なかった時だけ `daGdShorten_()`(da.gdのみ)でフォールバック短縮する副経路が残る。
- **記録は2チャンネル別シート**：GAS(`gas/コード.gs` v2)が `channel`(acc1/acc2)に応じて **`記録_ch1`/`記録_ch2`** へ**列名マッピング**で自動記入(記録先は「動画記録分析テンプレート.xlsx」を取り込んだスプレッドシート前提＝`設定`/`Holidays`/`集計` 含む)。`refreshClicks`(Bitly)＋`refreshEngagement`(Bluesky公開API いいね/リポスト/返信)を毎時更新。分析テンプレ＝プロジェクト直下 `記録分析テンプレート/`。
- ★**Bitlyは全廃**(`gas/コード.gs` 冒頭コメントに明記)。短縮は自前 Cloudflare Worker(`link-worker`)＝**チャンネル別独自ドメイン**(月詠み `5mgl.com` / 宵桜艶帖 `yoz2.com`)。Worker失敗時のみ da.gd→TinyURL へフォールバック、全滅時は元URLのまま。シートの「Bitly_ID」「Bitlyクリック」列名は互換のため残置だが、中身は **link-worker の開封数**。
- X(旧Twitter)はこの構成では不可(OAuth＋サーバー必須・直投稿はCORS不可)。
