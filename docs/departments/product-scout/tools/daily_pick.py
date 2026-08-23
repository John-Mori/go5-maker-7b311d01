#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""daily_pick.py — 商品候補選定部門の毎朝ピック生成(十王星南/クラウディア)
候補プール(D1 candidate_pool)から source 別に評価可能な作品を採点し、
「全候補5 / 手動追加5」を《狙い》一語ラベル付き(C-034)で出力する。

出力は UTF-8 の markdown を stdout へ。★このスクリプトは"生成"だけ。
Discordへの投稿・毎朝8時のスケジュールは基盤(プラットフォームSE/イージス研究室)が
このstdoutをそのまま部屋へ流す形で配線する(C-015: 常駐/スケジュールは基盤の領分)。

前提:
- カレントに関係なく fanza-worker で wrangler を叩く(D1 読み取りのみ)。
- works.info_json が入っているのは現状 source='main' がほぼ全部。list/circle は未取得=評価不可。
  → 未取得分は「見えていない」として明示する(Chami 2026-08-13「見えてない場合は改修αに伝えて」)。
"""
import json, io, os, subprocess, sys

WORKER_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", "fanza-worker")
WORKER_DIR = os.path.abspath(WORKER_DIR)

def d1(sql):
    """D1をJSONで読む。titleのCP932化けを避けるため、wranglerのstdoutをbytesで受けてUTF-8で復号。"""
    p = subprocess.run(["npx", "wrangler", "d1", "execute", "go5_fanza", "--remote", "--json",
                        "--command", sql], cwd=WORKER_DIR, capture_output=True, shell=True)
    out = p.stdout.decode("utf-8", "replace")
    # wrangler は前後にログを混ぜることがあるので最初の '[' から末尾の ']' まで
    i, j = out.find("["), out.rfind("]")
    return json.loads(out[i:j+1])[0]["results"]

def num(x):
    try: return int(str(x).replace(",", ""))
    except: return None

def sample_n(info):
    """動画生成用のサンプル画像(コマ)の枚数。無ければ0=動画化の素材が無い。"""
    si = info.get("sampleImageURL") or {}
    if isinstance(si, dict):
        for k in ("sample_l", "sample_s"):
            im = (si.get(k) or {}).get("image")
            if im: return len(im)
    return 0

EXCLUDE_DAYS = 3      # ★除外窓(日)。Chami 2026-08-23 裁定Aで 21→3 に緩和(下記docstring)。
EXCLUDE_RECENT_N = 10 # ★OR第2条件=直近この件数の投稿に含まれるcidも除外(Chami 2026-08-23。K=10で確定=裁定A/option1)。
                      #   実測ペース≈5本/日=直近10件は"直近ほぼ2日ぶん"。体調等で投稿が空くと日数だけでは
                      #   3日クリアで直近作品が復活してしまう=順番として直近の物を守る安全網。

def posted_recent(days=EXCLUDE_DAYS):
    """直近 days 日にいずれかのchへ投稿済みのcid集合(除外用・第1ゲート)。
    ★取得失敗時は空集合=除外しない(fail-open・可用性優先)。source=posted_log(改修α実装・commit aa30bf1)。
    ★窓は 21→3 日へ緩和(Chami 2026-08-23 裁定A)。狙い=『作品はどっちのchでも可・片chから3日経ったら
      もう片方で投稿できる物量』=投稿から3日経てば別chへ回す候補として再浮上する。旧= 2026-08-15
      『両chで3週間以内に投稿していないこと』(=物量が足りず last_posted 表示も死ぬため裁定Aで置換)。"""
    try:
        rows = d1("SELECT cid, MAX(posted_at) AS last_posted FROM posted_log "
                  f"WHERE posted_at >= datetime('now','-{int(days)} days') GROUP BY cid")
        return {r["cid"] for r in rows if r.get("cid")}
    except Exception:
        return set()

def posted_recent_by_count(n=EXCLUDE_RECENT_N):
    """直近 n 件の投稿(post events)に含まれるcid集合(除外用・第2ゲート)。
    ★体調不良等で投稿間隔が空いても"順番として直近"の作品を除外し続ける安全網(Chami 2026-08-23)。
    取得失敗は空集合(fail-open)。"""
    try:
        rows = d1(f"SELECT cid FROM posted_log ORDER BY posted_at DESC LIMIT {int(n)}")
        return {r["cid"] for r in rows if r.get("cid")}
    except Exception:
        return set()

def excluded_cids():
    """除外集合=『直近3日に投稿』∪『直近10件の投稿に含まれる』(Chami裁定=日数 OR 件数)。
    ★OR=どちらか一方でも該当すれば除外(Chami 2026-08-23『andじゃなくてor条件だったね』)。
    ★候補に"表示される"のは両条件のどちらにも該当しない物だけ。片方が空(fail-open)でももう片方は効く。"""
    return posted_recent() | posted_recent_by_count()

def parse(rows):
    out = []
    for r in rows:
        try: info = json.loads(r["info_json"])
        except: continue
        pr = info.get("prices") or {}
        price, lp = num(pr.get("price")), num(pr.get("list_price"))
        disc = round((lp - price) / lp * 100) if (price is not None and lp) else None
        rev = info.get("review") or {}
        rc = num(rev.get("count"))
        try: avg = float(rev.get("average")) if rev.get("average") not in (None, "") else None
        except: avg = None
        it = (info.get("iteminfo") or {}).get("author") or []
        author = (it[0].get("name", "") if it else "")
        out.append(dict(cid=r["cid"], title=r["title"], price=price, disc=disc, rc=rc,
                        avg=avg, sales=r.get("sales_n"), author=author, imgs=sample_n(info),
                        src=r.get("source")))
    return out

def score(x):
    s = 0.0
    if x["rc"] and x["avg"]: s += min(x["rc"], 300) / 30.0 * (x["avg"] / 5.0)
    if x["disc"]: s += x["disc"] / 25.0
    if x["price"] is not None: s += max(0, (1500 - x["price"])) / 1500.0 * 2
    if x["sales"]: s += min(x["sales"], 2000) / 500.0
    return round(s, 2)

def line(x):
    p = f"{x['price']}円" if x["price"] is not None else "価格?"
    dd = f" {x['disc']}%off" if x["disc"] else ""
    rr = (f" rc{x['rc']} {x['avg']}" if (x["rc"] and x["avg"]) else (f" rc{x['rc']}" if x["rc"] else " レビュー無"))
    sl = f" 実売{x['sales']}" if x["sales"] else ""
    au = f"({x['author']})" if x["author"] else ""
    im = f" 画像{x['imgs']}枚" if x.get("imgs") else " 画像なし"
    tab = {"main": "手動", "list": "リスト", "circle": "サークル"}.get(x.get("src"), "")
    tg = f" [{tab}]" if tab else ""
    return f"{x['cid']} {x['title']}{au} / {p}{dd}{rr}{sl}{im}{tg}"

def main():
    w = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    # source別の可視性(評価可能=info_jsonあり)
    cov = d1("SELECT cp.source src, COUNT(*) tot, SUM(CASE WHEN w.info_json IS NOT NULL AND w.info_json<>'' THEN 1 ELSE 0 END) vis "
             "FROM candidate_pool cp LEFT JOIN works w ON w.cid=cp.cid GROUP BY cp.source")
    covmap = {r["src"]: (r["tot"], r["vis"]) for r in cov}
    # ★除外=『直近3日に投稿』∪『直近10件の投稿に含まれる』の二重ゲート(Chami 2026-08-23)。取得失敗/履歴空なら空集合=除外なし。
    posted = excluded_cids()
    # 手動追加=source='main'のうち動画生成用サンプル画像があるもの限定(Chami 2026-08-15「画像もあるやつをチョイスして」)
    mainrows = parse(d1("SELECT cp.cid, cp.source, w.title, w.info_json, w.sales_n FROM candidate_pool cp JOIN works w ON w.cid=cp.cid "
                        "WHERE cp.source='main' AND w.info_json IS NOT NULL AND w.info_json<>''"))
    for x in mainrows: x["score"] = score(x)
    withimg_all = [x for x in mainrows if x.get("imgs")]
    withimg = sorted([x for x in withimg_all if x["cid"] not in posted], key=lambda x: -x["score"])
    excl_main = len(withimg_all) - len(withimg)
    w.write(f"**■ 手動追加(💡)おすすめ5**(画像あり・3日内投稿除外後の母集団{len(withimg)}/{len(mainrows)}件)\n")
    for x in withimg[:5]: w.write("- " + line(x) + "\n")
    noimg = len(mainrows) - len(withimg_all)
    if noimg: w.write(f"(画像なし{noimg}件は動画化の素材が無いので手動追加からは外した)\n")
    if excl_main: w.write(f"(直近3日/直近10件のいずれかで投稿済み{excl_main}件も除外)\n")
    # 全候補=全ソース(main+list+circle)から。★動画生成用の画像(sampleImageURL.sample_l=作品のコマ)が
    #   あるものだけに限定(Chami 2026-08-15「ソース集団はサンプル画像じゃなくて動画生成用の画像があるもののみ」)。
    #   ここで数える imgs は sample_l のコマ枚数=そのまま5秒動画の素材。imgs=0(表紙しか無い)は動画化できないので除外。
    allparsed = parse(d1("SELECT cp.cid, cp.source, w.title, w.info_json, w.sales_n FROM candidate_pool cp JOIN works w ON w.cid=cp.cid "
                         "WHERE w.info_json IS NOT NULL AND w.info_json<>''"))
    allrows_img = [x for x in allparsed if x.get("imgs")]
    allrows = [x for x in allrows_img if x["cid"] not in posted]
    excl_all = len(allrows_img) - len(allrows)
    for x in allrows: x["score"] = score(x)
    allrows.sort(key=lambda x: -x["score"])
    invis = []
    for s in ("list", "circle"):
        tot, vis = covmap.get(s, (0, 0))
        if tot - vis > 0: invis.append(f"{s} {tot-vis}件")
    dropimg = len(allparsed) - len(allrows_img)
    w.write(f"\n**■ 全候補おすすめ5**(全ソース・動画生成用の画像ありに限定・3日内投稿除外後の母集団{len(allrows)}/{len(allparsed)}件)\n")
    if dropimg:
        w.write(f"(画像なし{dropimg}件=表紙しか無く動画化の素材が無いので除外)\n")
    if excl_all:
        w.write(f"(直近3日/直近10件のいずれかで投稿済み{excl_all}件も除外)\n")
    if invis:
        w.write(f"(★{' / '.join(invis)} はまだ情報未取得=評価不可。改修αへ依頼中)\n")
    for x in allrows[:5]: w.write("- " + line(x) + "\n")
    w.flush()

if __name__ == "__main__":
    main()
