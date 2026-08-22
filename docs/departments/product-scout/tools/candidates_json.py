#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""candidates_json.py — 提案決定ページ用の候補JSON(comments以外)を実データで出す(十王星南)。
正本schema= docs/設計・調査/提案決定ページ_設計書.md §2。
出力= local/teian/candidates_YYYY-MM-DD.json(改修αのページが読む)。

★このツールは"候補の選定と根拠(metrics)"だけを埋める。comments は空配列(visionが後で埋める)。
採点は daily_pick.py の score/posted_recent を再利用=部門の選定軸を1本に保つ(single-source)。
- 動画生成用の画像(sampleImageURL.sample_l のコマ)が無い作品は動画化できない=候補から除外。
- 両CHいずれか直近3週間に投稿済みの作品は除外(posted_log・fail-open)。
- Books(cid が d_ 以外)で info_json が無い物は「未収録」=推測で埋めず books_uncovered へ cid 直書きで明示。
"""
import json, io, os, sys, math, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import daily_pick as dp

def revenue_rate(cid):
    """還元率(payout)= Books 0.70 / 同人 0.35(設計書§2)。"""
    return 0.35 if cid.startswith("d_") else 0.70

def rank_score(cid, sales):
    """★ページの並び順の正=分析(shorts-analyst)確定式 score = revenue_rate × log1p(sales_n)。
    候補を分けるのは需要(sales_n)と還元率だけ=再生/変換は素材/導線に支配され候補を分けない(指標定義 commit 4588d7f)。"""
    return round(revenue_rate(cid) * math.log1p(sales or 0), 4)

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", "local", "teian")
OUT_DIR = os.path.abspath(OUT_DIR)

def images_of(info):
    """挿入画像=フルカラーのコマ(sample_l 優先)。URL配列を返す。"""
    si = info.get("sampleImageURL") or {}
    if isinstance(si, dict):
        for k in ("sample_l", "sample_s"):
            im = (si.get(k) or {}).get("image")
            if im: return [u for u in im if u]
    return []

def platform_of(cid):
    return "doujin" if cid.startswith("d_") else "books"

def posted_by_channel():
    """{cid: set(channel)} 直近3週間に投稿済み。取得失敗/空なら空dict(fail-open)。"""
    try:
        rows = dp.d1("SELECT cid, channel FROM posted_log WHERE posted_at >= datetime('now','-21 days')")
        m = {}
        for r in rows:
            if r.get("cid") and r.get("channel"):
                m.setdefault(r["cid"], set()).add(r["channel"])
        return m
    except Exception:
        return {}

def review_of(info):
    rev = info.get("review") or {}
    c = dp.num(rev.get("count"))
    try: a = float(rev.get("average")) if rev.get("average") not in (None, "") else None
    except: a = None
    if c is None and a is None: return None
    return {"count": c, "average": a}

def main():
    w = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    today = datetime.date.today().isoformat()
    posted_any = dp.posted_recent()          # 両CHまとめ(除外用)
    posted_ch = posted_by_channel()          # CH別(推奨ch決定用)

    rows = dp.d1("SELECT cp.cid, cp.source, w.title, w.info_json, w.sales_n FROM candidate_pool cp "
                 "JOIN works w ON w.cid=cp.cid WHERE w.info_json IS NOT NULL AND w.info_json<>''")
    cand = []
    for r in rows:
        try: info = json.loads(r["info_json"])
        except: continue
        cid = r["cid"]
        imgs = images_of(info)
        if not imgs: continue                # 動画化の素材が無い=除外
        if cid in posted_any: continue       # 直近3週間に両CHいずれか投稿済み=除外
        pr = info.get("prices") or {}
        price, lp = dp.num(pr.get("price")), dp.num(pr.get("list_price"))
        disc = round((lp - price) / lp * 100) if (price is not None and lp) else None
        rev = review_of(info)
        x = dict(cid=cid, title=r.get("title") or "", price=price, disc=disc,
                 rc=(rev or {}).get("count"), avg=(rev or {}).get("average"),
                 sales=r.get("sales_n"), imgs=len(imgs), src=r.get("source"),
                 _images=imgs, _review=rev, _platform=platform_of(cid))
        x["select_score"] = dp.score(x)                       # 候補入りの選定軸(価格/割引/実売/レビュー)
        x["rank_score"] = rank_score(cid, r.get("sales_n"))   # ★ページの並び順の正(分析確定式)
        cand.append(x)

    # ★並び順は分析 score(revenue_rate×log1p(sales_n))を正とする(設計書§3)。
    cand.sort(key=lambda x: (-x["rank_score"], -x["select_score"]))
    top = cand[:10]

    # 推奨ch=直近投稿の無い側を優先、無ければ負荷を均すため交互(★暫定=採算/テーマの本判定は分析待ち)
    out_candidates = []
    alt = 0
    for i, x in enumerate(top):
        recent = posted_ch.get(x["cid"], set())
        if "acc1" in recent and "acc2" not in recent: ch = "acc2"
        elif "acc2" in recent and "acc1" not in recent: ch = "acc1"
        else:
            ch = "acc1" if alt % 2 == 0 else "acc2"; alt += 1
        out_candidates.append({
            "id": f"cand-{i+1:03d}",
            "cid": x["cid"],
            "platform": x["_platform"],
            "title": x["title"],
            "channel": ch,
            "channel_provisional": True,      # ★暫定=採算/テーマ本判定(分析)で上書きされる
            "images": x["_images"],
            "metrics": {
                "sales_n": x["sales"],
                "review": x["_review"],       # FANZA実データ(有れば)。★並び順には使わない(分析確定)
                "price": x["price"], "discount_pct": x["disc"],
                "revenue_rate": revenue_rate(x["cid"]),
                "score": x["rank_score"],     # ★ページの並び順の正=分析式 revenue_rate×log1p(sales_n)
                "select_score": x["select_score"],  # 商品選定の候補入り選定軸(価格/割引/実売/レビュー)
                "past_similar_recovery": None # ★成約は観測不可=分析が null 固定と確定
            },
            "manual": (x["src"] == "main"),
            "comments": []                    # visionが後で3択を埋める
        })

    # Books未収録(info_jsonが無い=title/販売数が引けない)を穴として明示(推測で埋めない)
    uncov = dp.d1("SELECT cp.cid FROM candidate_pool cp LEFT JOIN works w ON w.cid=cp.cid "
                  "WHERE cp.cid NOT LIKE 'd\\_%' ESCAPE '\\' AND (w.info_json IS NULL OR w.info_json='')")
    books_uncovered = [r["cid"] for r in uncov if r.get("cid")]

    doc = {
        "date": today,
        "generated_by": "product-scout/candidates_json.py",
        "note": ("並び順の正=分析 score(revenue_rate×log1p(sales_n))降順(設計書§3)。"
                 "select_score は商品選定の候補入り選定軸で、並び順には使わない。"
                 "channel は暫定(採算/テーマ本判定は分析待ち・channel_provisional=true)。"
                 "past_similar_recovery は成約が観測不可=分析が null 固定と確定。comments は vision が後埋め。"),
        "candidates": out_candidates,
        "books_uncovered": books_uncovered,   # DB未収録のBooks cid(推測で埋めていない穴)
    }

    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, f"candidates_{today}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
    w.write(f"wrote {path}\n候補{len(out_candidates)}件 / Books未収録{len(books_uncovered)}件 / 母集団{len(cand)}件\n")
    w.flush()

if __name__ == "__main__":
    main()
