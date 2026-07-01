# アフィリエイトID 活用と有効化（設計・手順）

作成：Claude Code
結論：**「IDを活かす構造」はすでに実装済み**。必要なのは**値の投入だけ**。値はチャットに載せず、下記の場所/コマンドで入れれば即有効化される。

---

## 0. まず「どっちのID？」を切り分け

このプロジェクトには**2種類のFANZA系ID**があり、用途も投入場所も違う。コンサルからもらったIDがどちらか（または両方か）で作業が変わる。

| 種類 | 用途 | 形式の例 | 投入場所 | 現状 |
|---|---|---|---|---|
| **① アフィID（af_id）** | 投稿に貼る**アフィリエイトリンク**の識別子。`al.fanza.co.jp/?...&af_id=◯◯&...` | `yourname-001` 等 | アプリ「🔗 AFIリンク」タブ「① あなたのアフィID」欄 | 構造完成・**値の入力待ち** |
| **② DMM API資格情報** | FANZAの**商品情報(題名/価格/レビュー)を自動取得**するDMM公式API。fanza-workerが使用 | API_ID＝英数長い / AFFILIATE_ID＝`xxxx-990`等 | Cloudflare fanza-worker の**Secret** | 構造完成・**未設定**（`SHARED_SECRET`のみ設定済） |

> 見分け方：`al.fanza.co.jp` のリンクに入れる短い識別子＝①。DMMの開発者API用（api_id と対）＝②。
> ②は **API_ID と AFFILIATE_ID の2つで1組**。もし片方（AFFILIATE_IDだけ）なら、API_IDもコンサルに要求が必要。

---

## 1. すでにある「活かす構造」（実装済み・確認済み）

### ① af_id の構造（リンク生成）
- 保存先：`localStorage: fanza_af_id`（全アカウント共通）。設定エクスポート（鍵を除いて）にも**含まれる＝バックアップ対象**。
- 使用箇所（すべて `buildAffiliateLink(url, af_id)` 経由で一貫）：
  - 🔗AFIリンクタブの手動リンク生成（affiliate.js）
  - **投稿時のアフィリンク自動付与**（bluesky.js：作品URL→`al.fanza.co.jp/...&af_id=...` を本文に付与）
  - 🦋投稿タブ 作品URLのアフィリンク・プレビュー
  - ウィザードのリンク生成
- af_id 未入力時は `af_id=【アフィID】` の構造プレビューになる（＝入れれば全部に反映）。

### ② DMM API の構造（商品情報取得）
- fanza-worker が `env.FANZA_API_ID` と `env.FANZA_AFFILIATE_ID` の**両方が設定されていればDMM公式APIを優先**（`fetchViaApi`）。未設定ならスクレイピング（FANZA同人はログイン要求で失敗＝題名が「ログイン - FANZA」になる原因）。
- 取得した商品情報は → 投稿履歴の作品名表示、スプレッドシートのFANZA価格スナップショット列（元値/割引後/割引率/レビュー等）に反映される（この配線も実装済み）。

**→ つまり、コードとしての「活かす構造」は①②とも完成している。**

---

## 2. 有効化の手順（値を入れるだけ）

### ① af_id を入れる（リンク用・非機密）
1. アプリの「🔗 AFIリンク」タブを開く
2. 「① あなたのアフィID」欄に、もらった af_id を入力（自動保存される）
3. 以後、投稿時のアフィリンク・AFIリンクタブ・プレビューすべてに自動反映

### ② DMM API を有効化する（機密・端末のコマンド）
> APIキーはチャットに貼らない。あなたのPCの端末で下記を実行（fanza-workerフォルダ・wranglerはこのPCで認証済み）。

```
cd <リポジトリ>/fanza-worker
npx wrangler secret put FANZA_API_ID          # ← DMMのAPI IDを貼ってEnter（画面に表示されないのが正常）
npx wrangler secret put FANZA_AFFILIATE_ID    # ← FANZAアフィリエイトID（xxxx-990等）を貼ってEnter
npx wrangler deploy                            # 反映
```
確認：`npx wrangler secret list` に `FANZA_API_ID` `FANZA_AFFILIATE_ID` が並べばOK。
その後、作品URLを入れて商品名が「ログイン - FANZA」でなく実タイトルで出れば成功。

> もし値をClaude Codeに任せたい場合：**af_id（非機密）はチャットで渡してOK→私が反映**。**API_ID（機密）はこのコマンドを自分で実行**、が安全。どうしても私に任せるなら、その旨を明示してくれれば私が `wrangler secret put` まで実行する（認証済みのため可能）。

---

## 3. 補足・今後の拡張余地（今回はやらない）
- af_id をアカウント別（月詠み/宵桜で別ID）にしたい場合：`fanza_af_id__<acct>` 方式へ拡張可能（現状は共通1個）。必要になったら対応。
- 成果（クリック/成約/報酬）はDMM ItemList APIでは取れない（FANZA管理画面が正）。スプレッドシートのFANZA成約・報酬列は引き続き手入力。
