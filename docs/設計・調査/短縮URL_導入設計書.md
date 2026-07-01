# 短縮URL 短縮化：導入設計書（すぐ着手できる状態）

前提：比較・検証は `短縮URL_3AI比較と検証結果.md` を参照。
方針：**既存 r2 ワーカーの計測は温存し、入口URLだけを短くする**。

本書は2案を「コード差分レベル / 手順レベル」で用意する。あなたのGoサインで即着手できる。

---

## 案A：da.gd チェーン（今夜テスト合格・私だけで即実装可）

### 概要
`最終URL` → **r2で短縮（計測担当・内部保持）** → その r2URL を **da.gd でさらに短縮（表に出す入口＝16字）**。
- クリックは `da.gd/xxx → r2/xxxxx(+1計測) → 最終` の順に流れ、**計測は既存r2機構のまま**（実測で 0→2 増加を確認済み）。
- YouTube概要欄・コピーには **da.gd URL** を出す。クリック数の読み取りは **内部の r2 URL** から行う（既存ロジック不変）。

### データモデル変更
履歴アイテムに1フィールド追加：
- `shortUrl`（既存）＝ r2 URL … **クリック計測用（変更なし）**
- `shareUrl`（新規）＝ da.gd URL … **表示・コピー・概要欄挿入・シート記録用**
- `shareUrl` が無い場合は `shortUrl` を表示（後方互換）

### 変更ファイルと差分（実装指示）

**1) bluesky.js — 短縮フローで da.gd 入口を生成**
- `shortenUrl(longUrl)` 系を2段に：
  1. `r2short = shortenViaWorker(longUrl)`（既存・計測用）
  2. `share = r2short ? (daGdShorten(r2short) || r2short) : (既存の da.gd/tinyurl フォールバック)`
     - 既存に `shortenVia('https://da.gd/s?url=', url)` があるので流用（無認証・実測OK）
  3. 返り値を `{ shortUrl: r2short||share, shareUrl: share }` に拡張
- `shortenAndShow()` / `setShareOutputs()`：**概要欄・コピー・表示は shareUrl を使う**
- `histAdd`：`entry.shareUrl = rec.shareUrl || ''` を保存
- `recordToSheet`：payload に `shareUrl` を追加

**2) yt-clicks.js — 表示は shareUrl、計測は shortUrl**
- render の `bskyHref` と「🔗」表示・コピーを `it.shareUrl || it.shortUrl` に
- クリック数の `codeOf(it.shortUrl)` は **shortUrl(r2)のまま**（変更しない）
- sync payload に `shareUrl` を追加

**3) GAS（コード.gs）— 共有URL列を追加**
- `EXTRA_HEADERS` に `'共有URL'` を追加（migrate_headersで既存シートに付与）
- `writeRecord_`：`putIf('共有URL', f.shareUrl || '')`
- **短縮URL列は r2 のまま**（毎時 refreshClicks の codeFromShort_ が動作継続）。共有URL列に da.gd を併記
- doPost / syncHistory_ で `shareUrl` を中継

**4) index.html**：バージョン上げ（v116等）

### メリット / デメリット
- ○ 今すぐ・私だけで実装可（外部登録一切不要）／ 16字 ／ 計測維持 ／ 個人情報の露出なし
- △ **印字リンクが da.gd 依存**（da.gd終了＝印字リンク死）。r2(中間)と最終は生きるが、YouTube概要欄の見た目リンクは失効
- △ 二段リダイレクトで +0.35s程度／共有短縮はSNSで評価が下がる可能性（ただし現状も一部 da.gd 使用中で新規悪化ではない）

### ロールバック
- `shareUrl` を使わず `shortUrl` を表示に戻すだけ（1フラグで切替可能に実装する）。既存 r2 リンクは常に生存。

---

## 案B：独自の無料短いドメイン + r2 に Custom Domain（本命・要あなたの手動ワンステップ）

### 概要
無料の短いホスト名を Cloudflare の zone にして、**既存 r2 ワーカーに Custom Domain として割り当てる**。
`https://<短いホスト>/xxxxx` になり、**チェーン不要・1ホップ・計測はr2直**（最もクリーン）。

### B-1：pp.ua 版（手順は簡単／ただしWHOIS公開の重大注意）
> ⚠️ **pp.ua は WHOIS に登録者の氏名・電話・住所が完全公開**される。匿名運用には不向き。許容できる場合のみ。

あなたがやる（10〜20分）：
1. nic.ua で `xxx.pp.ua`（短い名前）を無料登録。**携帯SMS/Telegram @ppuabot で認証**（30日3個まで、3〜63字）。
2. Cloudflareで「サイトを追加」→ `xxx.pp.ua`。“not a registered domain”で弾かれたら、先に中間DNS(HE.net等)でNS/SOAを設定して名前解決させてから再試行。
3. 割り当てられた Cloudflare の NS 2つを nic.ua 側に設定 → zoneがActiveになるまで待つ。

私がやる（あなたが上記完了後・数分）：
4. `wrangler`（認証済み）で r2 ワーカーに Custom Domain `xxx.pp.ua`（or `s.xxx.pp.ua`）を追加、SSL自動発行。
5. bluesky.js の `WORKER_URL` と GAS `SHORT_WORKER_URL` を新ホストに変更（旧 r2 URL も併存維持）。
6. 通しテスト（短縮→リダイレクト→計測）。

### B-2：is-a.dev + Cloudflare for SaaS 版（プライバシー保護・手順は複雑）
> ✅ WHOISはGitHub名/メールのみ。ただし **is-a.dev は「非商用・開発関連」限定＝アダルトアフィリは規約抵触で剥奪リスク**。

必要要素：フォールバック用にアクティブな Cloudflare zone が1つ要る（pp.ua を“表に出さず”受信用に使う等）。
あなたがやる：
1. フォールバック zone（例 pp.ua を1つ）を Cloudflare に用意。
2. Cloudflare「SSL/TLS → Custom Hostnames（Cloudflare for SaaS・無料100個）」を有効化。
3. GitHub `is-a-dev/register` を fork → `domains/<name>.json` に CNAME(→フォールバックのCustom Hostname) + `proxied:false` を書いて **PR提出 → マージ待ち（数時間〜数日）**。
4. マージ後、Cloudflare側で Custom Hostname `<name>.is-a.dev` を追加、提示された TXT を is-a.dev の JSON に追記して再PR → 検証Active。

私がやる：Worker紐付け・URL差し替え・テスト（上のB-1の4〜6と同様）。

> 手順の複雑さ・規約リスク・SSL更新時のTXT再検証の継続性（要検証）から、**B-2は「pp.uaのWHOISが嫌 かつ 規約リスクを許容できる」場合の上級者向け**。

### メリット / デメリット（案B共通）
- ○ チェーン不要・1ホップ・計測はr2直・見た目も短い（14〜20字前後）
- △ **取得はあなたの手動ワンステップが必須**（今夜は不可）／無料ドメイン提供元の存続に依存（④は完全ではない）
- pp.ua＝プライバシー×、is-a.dev＝規約×、というトレードオフ

---

## 併記：将来の堅牢化（今回はやらない・頭出しのみ）
- **KV書き込み1,000/日 上限**：日1,000クリック超で計測が落ちる。伸びたら **D1(10万/日)** にカウンタ移設（Cloudflare無料内）。
- **OSS Sink への移行**：OGP差し替え等の機能拡張が要るときの候補。短さ自体は解決しない。

---

## 推奨と意思決定フロー

```
今すぐ短くしたい？
├─ はい → 【案A da.gd チェーン】を即実装（私だけで可）。④の弱さは許容。
│         （＝短さを優先、印字リンクはda.gd依存を受け入れる）
└─ いいえ、多少待ってもクリーンにしたい
    ├─ 匿名性を最優先 → 【案B-2 is-a.dev】（ただし規約リスク）or 現状r2維持
    ├─ WHOIS公開OK    → 【案B-1 pp.ua】（手順は最簡単）
    └─ 全部が気になる  → 【現状 r2 維持】（長いが最も安全・恒久・匿名）も合理的
```

**Claude Codeの推奨**：
1. **まず案A(da.gdチェーン)を入れて“短さ”を即獲得**（ロールバック容易・私だけで実装可）。並行して、
2. **本命は案B**だが、pp.ua(プライバシー×)/is-a.dev(規約×)の弱点があるため、**あなたの価値観（匿名性 vs 手間）次第**。
3. どうしても割り切れないなら **現状r2維持**も十分アリ（長いだけで、無料・計測・恒久・匿名の4つは満たしている）。

→ 起きたら「案Aを入れる／案Bのどれで進める／現状維持」を選んでくれれば、そこから即着手する。
