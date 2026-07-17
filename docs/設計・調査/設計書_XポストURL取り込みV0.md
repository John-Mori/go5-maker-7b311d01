# 設計書 — XポストURL取り込みV0(URLぽいっ→FANZA作品特定→候補入り)

- 作成: 2026-07-18 研究室 / Chami承認済み(research-room ch 05:19「これ実装お願い」・原案=研究室のGrok構想回答①)
- 費用: **ゼロ**(公開エンドポイントのみ・API契約なし。Grok/X APIは使わない=別案件V1)
- 実装担当: system-engineer(候補DB書き込みが持ち場のため)。X取得部は研究室が実証済みコードを提供(§4)

## 1. 何をするか

Chamiが**XのポストURLを貼るだけ**で、①ポスト本文と画像を取得 → ②リンク/本文からFANZA作品を特定 → ③候補DBへ登録(commentに出典Xポスト情報付き)までを自動化する。作品情報はXにごろごろ転がっている——それを拾う入り口を1本にする。

- 入力経路(V0): **商品選定部門ch(product-scout)へXポストURLを貼る**。鳩が拾い、処理系が反応する(既存の候補追加フローに合流)。研究室chに貼られた場合も研究室が同処理へ回してよい。

## 2. パイプライン

1. **ポスト取得**: X埋め込み用の公開エンドポイント(cdn.syndication.twimg.com/tweet-result)で本文・画像URL・外部リンクを取得。**ログイン不要・無料・実証済み**(2026-07-17に研究室が実測)。取れないもの=長文記事・鍵アカ・削除済み→「取れなかった」と正直に返す。
2. **リンク解決(Chami質問への回答=アフィ/短縮リンク対応)**:
   - **アフィリンク(al.dmm.co.jp等)**: URLパラメータ(lurl等)に元URLがエンコードされているため、**踏まずに解読**して元の作品URLを得る。※踏まない理由: 他人のアフィリンクへ機械アクセスするとクリック計測を汚す
   - **短縮リンク(t.co/bit.ly/da.gd/x.gd等)**: リダイレクト先だけをHEAD相当で解決(本文は読まない)。t.coは全ポストで必ず挟まるため常時解決
   - 多段(短縮→アフィ→作品)も再帰で解決。**最終URLがFANZAならcid=作品IDを抽出**
3. **作品特定**:
   - cid取得成功 → fanza-worker既存の作品情報取得へ
   - cid無し(リンクがFANZA外・リンク無し) → ポスト本文からタイトル候補を抽出しFANZA検索で突合。曖昧なら候補を提示して人が選ぶ(誤登録より保留)
4. **候補DB登録**: 既存の候補追加経路(go5-sync/fanza-worker)へ。出典として `x_post_url`・投稿者・取得画像URLをメモ欄へ。**重複はcidで排除**(既候補なら「既にあるよ」と返す)
   - ★**入口の等価性(Chami指定2026-07-18 05:36)**: **Discord経由でもアプリ(5s)経由でも、どちらで登録しても5sの候補タブに同一形式で表示される**こと。作品URLも候補タブ内に載せる。=登録リストの正はアプリが見る候補DBの1本(Discord側に別リストを作らない)
5. **返信**: 処理結果を発生元chへ(persona=部屋の人格)。成功=作品名+候補入りの確認/失敗=理由を正直に

## 3. 受け入れ条件

1. 通常のFANZA直リンク付きポスト → 候補入りまで自動
2. **アフィリンク付きポスト → 踏まずに解読して候補入り**(アフィ計測を汚さないことをコードで確認)
3. 短縮リンク(da.gd等)付き → 解決して候補入り
4. リンク無し本文のみ → FANZA検索突合(曖昧時は保留提示)
5. 長文記事/鍵アカ → 「取れない」と正直に返信(黙って失敗しない)
6. 同一作品の再投入 → 重複登録されない

## 4. 実証済みの取得コード(研究室→改修へ提供)

```python
import json, math, urllib.request
def fetch_x_post(tweet_id: int):
    def to36(x):
        d="0123456789abcdefghijklmnopqrstuvwxyz"; i=int(x); f=x-i; s=""
        while i: s=d[i%36]+s; i//=36
        s+="."
        for _ in range(12): f*=36; s+=d[int(f)]; f-=int(f)
        return s
    tok=to36(tweet_id/1e15*math.pi).replace("0","").replace(".","")
    url=f"https://cdn.syndication.twimg.com/tweet-result?id={tweet_id}&token={tok}&lang=ja"
    req=urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"})
    return json.loads(urllib.request.urlopen(req, timeout=30).read())
# 戻り: text / user / mediaDetails(画像) / entities.urls(展開URL)。2026-07-17実測OK
```

## 5. やらないこと(V0の境界)

- X内の検索・トレンド発掘(=Grok/X APIの領分・**有料**。V1として使用感を見てから見積り)
- Xアプリ内Grokの自動操縦(規約違反)
- ポスト画像の自動転載(取得は特定のためのみ。公開物への再利用はしない=P0規約)
