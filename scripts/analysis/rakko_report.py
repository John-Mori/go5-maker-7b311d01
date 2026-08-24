# -*- coding: utf-8 -*-
"""ラッコM&A 週次相場レポート(分析部門・shorts-analyst)。

公開API(認証不要・無料)を叩き、YouTube案件の相場を中央値で出す。
- 数字はこのスクリプトが確定させる(AIに計算させない)。
- 相場は平均でなく中央値。月利0以下は中央値計算から除外。
- 出力は1行1項目のプレーンテキスト(Discordのコードブロック桁揃えは使わない)。

叩く先= GET https://api.rakkoma.com/api/list/v1
 - ページングは ?page=N が有効(1ページ=10件固定・page=1と2で中身が変わる)。
 - YouTube絞りは sale_subtype=201 ではなくタイトル正規表現(HQ実測の申し送り)。
走らせ方: python scripts/analysis/rakko_report.py   (引数不要)
"""
import urllib.request, json, time, re, statistics, os, sys
from datetime import datetime, timezone, timedelta

BASE = "https://api.rakkoma.com/api/list/v1"
JST = timezone(timedelta(hours=9))
PAGE_CAP = 120  # 安全上限(1ページ10件=最大1,200件まで見る)
OUTDIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                      "local", "analysis", "rakko")

# --- YouTube判定(誤爆対策) -------------------------------------------------
# 「アカウント」単独はAmazonセラー垢等を誤爆するので入れない。
YT_POS = re.compile(r"YouTube|ユーチューブ|YouTuber|ようつべ|Vtuber|VTuber|Vチューバー|切り抜き|ショートチャンネル", re.I)
OTHER_PLATFORM = re.compile(r"Instagram|インスタ|TikTok|ティックトック|Twitch|Threads|スレッズ")

def is_youtube(title):
    if YT_POS.search(title):
        return True
    # 「チャンネル」は強いYouTube信号だが、他プラットフォーム語があれば除外
    if "チャンネル" in title and not OTHER_PLATFORM.search(title):
        return True
    return False

# --- ジャンル粗分類(タイトル語ベース・精度は粗い) --------------------------
GENRE = [
    ("アダルト/成人", re.compile(r"アダルト|成人|エロ|R18|18禁|お色気|セクシー|抜ける")),
    ("切り抜き/まとめ", re.compile(r"切り抜き|まとめ|ショート")),
    ("スポーツ", re.compile(r"野球|サッカー|MLB|NPB|格闘技|ボクシング|プロレス|バスケ|スポーツ")),
    ("ゲーム/実況", re.compile(r"ゲーム|実況|Vtuber|VTuber|マイクラ|フォートナイト|eスポーツ")),
    ("美容/コスメ", re.compile(r"美容|コスメ|化粧|スキンケア|ダイエット|痩")),
    ("恋愛/婚活", re.compile(r"恋愛|婚活|マッチング|出会い|カップル")),
    ("金融/投資", re.compile(r"投資|株|FX|仮想通貨|副業|節約|お金|マネー|資産")),
    ("料理/グルメ", re.compile(r"料理|グルメ|レシピ|飲食|食")),
    ("教育/雑学", re.compile(r"雑学|勉強|教育|学習|解説|歴史")),
]

def classify(title):
    for name, pat in GENRE:
        if pat.search(title):
            return name
    return "その他"

# --- 取得 -------------------------------------------------------------------
def page(p, tries=4):
    for _ in range(tries):
        try:
            req = urllib.request.Request(f"{BASE}?page={p}", headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                d = json.loads(r.read().decode())
            dat = d.get("data")
            if isinstance(dat, list) and dat:
                return dat
        except Exception:
            pass
        time.sleep(1.2)
    return []

def fetch_all():
    seen = {}
    last = 0
    for p in range(1, PAGE_CAP + 1):
        items = [x for x in page(p) if isinstance(x, dict)]
        if not items:
            break
        keys = [(x.get("site_url") or x.get("project_title")) for x in items]
        if all(k in seen for k in keys):
            break  # 新規なし=末尾
        for x in items:
            seen[x.get("site_url") or x.get("project_title")] = x
        last = p
        time.sleep(0.35)
    return list(seen.values()), last

def med(xs):
    return int(round(statistics.median(xs))) if xs else None

def build():
    rows, last_page = fetch_all()
    now = datetime.now(JST).strftime("%Y-%m-%d %H:%M JST")
    yt = [x for x in rows if is_youtube(str(x.get("project_title", "")))]

    def num(x, k):
        v = x.get(k)
        try:
            return int(v)
        except Exception:
            return None

    prices = [num(x, "site_price") for x in yt]
    prices = [v for v in prices if v is not None and v > 0]
    # 月利0以下は中央値から除外
    profit_rows = [(num(x, "site_price"), num(x, "site_profit"), x) for x in yt]
    profit_rows = [(pr, pf, x) for pr, pf, x in profit_rows if pf is not None and pf > 0 and pr]
    profits = [pf for pr, pf, x in profit_rows]
    months = [pr / pf for pr, pf, x in profit_rows]  # 回収月数

    genre_cnt = {}
    genre_price = {}
    for x in yt:
        g = classify(str(x.get("project_title", "")))
        genre_cnt[g] = genre_cnt.get(g, 0) + 1
        pv = num(x, "site_price")
        if pv:
            genre_price.setdefault(g, []).append(pv)

    L = []
    L.append("■ラッコM&A 週次相場(YouTube案件) 集計 " + now)
    L.append("母数: 市場全体 %d件(page1-%d取得)/ うちYouTube案件 %d件 / 月利>0で回収計算に使えた案件 %d件"
             % (len(rows), last_page, len(yt), len(profit_rows)))
    L.append("① 件数(YouTube案件) = %d件" % len(yt))
    L.append("② 売り価格の中央値 = %s円" % ("{:,}".format(med(prices)) if prices else "算出不可"))
    L.append("③ 月利の中央値 = %s円 (月利>0のみ・n=%d)" % (("{:,}".format(med(profits)) if profits else "算出不可"), len(profits)))
    L.append("④ 回収月数の中央値 = %s ヶ月 (price÷月利・月利>0のみ・n=%d)"
             % (("%.1f" % statistics.median(months)) if months else "算出不可", len(months)))
    L.append("― ジャンル別(YouTube案件・件数 / 価格中央値) ―")
    for g in sorted(genre_cnt, key=lambda k: -genre_cnt[k]):
        pm = med(genre_price.get(g, []))
        L.append("・%s: %d件 / 価格中央値 %s円" % (g, genre_cnt[g], ("{:,}".format(pm) if pm else "―")))
    L.append("― 価格上位10件(価格 / 月利 / タイトル) ―")
    top = sorted([x for x in yt if num(x, "site_price")], key=lambda x: -num(x, "site_price"))[:10]
    for x in top:
        pr = num(x, "site_price"); pf = num(x, "site_profit")
        L.append("%s円 / 月利%s円 / %s"
                 % ("{:,}".format(pr), ("{:,}".format(pf) if pf else "非公開/0"),
                    str(x.get("project_title", ""))[:60]))
    L.append("― 注記(取れないもの) ―")
    L.append("・登録者数・正確なジャンル(タイトル語の粗い代理)・チャンネルURLは取れない。site_profitは直近月利で振れる。")
    L.append("・YouTube判定はタイトル正規表現(切り抜き/チャンネル/VTuber等)。他プラットフォーム(Instagram/TikTok)は除外。")
    return "\n".join(L), now

def main():
    text, now = build()
    print(text)
    os.makedirs(OUTDIR, exist_ok=True)
    date = datetime.now(JST).strftime("%Y-%m-%d")
    with open(os.path.join(OUTDIR, "rakko_report_%s.txt" % date), "w", encoding="utf-8") as f:
        f.write(text + "\n")
    with open(os.path.join(OUTDIR, "rakko_report_latest.txt"), "w", encoding="utf-8") as f:
        f.write(text + "\n")
    return 0

if __name__ == "__main__":
    sys.exit(main())
