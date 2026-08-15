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
                        avg=avg, sales=r.get("sales_n"), author=author, imgs=sample_n(info)))
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
    return f"{x['cid']} {x['title']}{au} / {p}{dd}{rr}{sl}{im}"

def main():
    w = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    # source別の可視性(評価可能=info_jsonあり)
    cov = d1("SELECT cp.source src, COUNT(*) tot, SUM(CASE WHEN w.info_json IS NOT NULL AND w.info_json<>'' THEN 1 ELSE 0 END) vis "
             "FROM candidate_pool cp LEFT JOIN works w ON w.cid=cp.cid GROUP BY cp.source")
    covmap = {r["src"]: (r["tot"], r["vis"]) for r in cov}
    rows = parse(d1("SELECT cp.cid, w.title, w.info_json, w.sales_n FROM candidate_pool cp JOIN works w ON w.cid=cp.cid "
                    "WHERE cp.source='main' AND w.info_json IS NOT NULL AND w.info_json<>''"))
    for x in rows: x["score"] = score(x)
    rows.sort(key=lambda x: -x["score"])
    # 手動追加=動画生成用のサンプル画像があるもの限定(Chami 2026-08-15「画像もあるやつをチョイスして」)
    withimg = [x for x in rows if x.get("imgs")]
    w.write(f"**■ 手動追加(💡)おすすめ5**(画像ありに限定・母集団{len(withimg)}/{len(rows)}件)\n")
    for x in withimg[:5]: w.write("- " + line(x) + "\n")
    noimg = len(rows) - len(withimg)
    if noimg: w.write(f"(画像なし{noimg}件は動画化の素材が無いので手動追加からは外した)\n")
    invis = []
    for s in ("list", "circle"):
        tot, vis = covmap.get(s, (0, 0))
        if tot - vis > 0: invis.append(f"{s} {tot-vis}件")
    w.write("\n**■ 全候補おすすめ5**\n")
    if invis:
        w.write(f"(★{' / '.join(invis)} は works に情報未取得=評価不可で、評価できる母集団が手動追加と同一。"
                f"よって現状の全候補は手動追加と中身が重なる。分離には改修αのバックフィルが要る=依頼中)\n")
    for x in rows[:5]: w.write("- " + line(x) + "\n")
    w.flush()

if __name__ == "__main__":
    main()
