# -*- coding: utf-8 -*-
"""競合チャンネル日次ランキング分析(shorts-analyst / アーモンドアイ担当)
毎朝の運用: python scripts/analysis/competitor_daily.py
 - GAS comp_titles(速度=views/measurementDays 順)を取得
 - videoId 単位の台帳(competitor_daily_ledger.jsonl)と突合し「新規/既出」を分ける
   → 既出(=以前に分析済みの同一動画がまた上位に居る)は再解析せず事実だけ反映(Chami指示2026-08-13)
 - 伸びた(高速)/伸びてない(低速)を出し、題名を SA-H004 数字3型・SA-H005 断定/問いかけ で符号化
 - 当日レポートを docs/departments/shorts-analyst/competitor_daily/<date>.md へ
 - 新規 videoId を台帳へ追記(次回から既出扱い)
数字は測って出す(捏造しない)。速度=当日スナップの velocity 代理値。
"""
import json, re, sys, os, subprocess, datetime
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LEDGER = os.path.join(ROOT, "docs", "departments", "shorts-analyst", "competitor_daily_ledger.jsonl")
OUTDIR = os.path.join(ROOT, "docs", "departments", "shorts-analyst", "competitor_daily")

# --- 数字型分類(SA-H004 の3型・ハッシュタグ除去後に判定) ---
KANJI = "〇零一二三四五六七八九十百千万億"
DIGIT = re.compile(r"[0-9０-９" + KANJI + r"]")
HYPE = ["選", "つ", "個", "連", "ランキング", "ベスト", "TOP", "秒後", "種類", "コ目", "第", "位", "大", "つの"]
SPAN = ["週", "ヶ月", "か月", "年後", "日連続", "レベル", "分後", "たった", "わずか", "年で", "日で", "ヶ月で"]
INTR = ["歳", "回", "万円", "円", "人", "番", "点", "cm", "kg", "時", "分", "%"]

def strip_tags(t):
    return re.sub(r"#\S+", "", t).strip()

def num_type(title):
    t = strip_tags(title)
    if not DIGIT.search(t):
        return "数字なし"
    for w in SPAN:
        if w in t: return "②経過年月スパン型"
    for w in INTR:
        if w in t: return "③固有数字型"
    for w in HYPE:
        if w in t: return "①数量煽り型"
    return "保留(曖昧数量)"

def q_type(title):
    t = strip_tags(title)
    return "問いかけ" if ("？" in t or "?" in t) else "断定"

def median(xs):
    xs = sorted(xs)
    n = len(xs)
    if n == 0: return 0
    return xs[n//2] if n % 2 else (xs[n//2-1]+xs[n//2])/2

def fetch():
    cfg = json.load(open(os.path.join(ROOT, "scripts", "gas_deploy_config.json")))
    url = cfg["execUrl"] + "?action=comp_titles&days=30&top=200"
    last = ""
    for attempt in range(4):  # Google が稀に interstitial HTML を挟む=同一取得のリトライで抜ける
        raw = subprocess.check_output(["curl", "-sL", "--max-time", "120", url]).decode("utf-8", "replace")
        if raw.lstrip().startswith("{"):
            return json.loads(raw)
        last = raw[:80]
    raise RuntimeError("comp_titles が4回とも JSON でない(GAS/Google側の障害): " + last)

def load_ledger():
    seen = {}
    if os.path.exists(LEDGER):
        for line in open(LEDGER, encoding="utf-8"):
            line = line.strip()
            if not line: continue
            r = json.loads(line)
            seen[r["videoId"]] = r
    return seen

def main():
    d = fetch()
    ts = d["titles"]
    snap = ts[0]["snapshotDate"] if ts else "?"
    seen = load_ledger()

    for t in ts:
        t["numType"] = num_type(t["title"])
        t["qType"] = q_type(t["title"])
        t["known"] = t["videoId"] in seen

    ts_sorted = sorted(ts, key=lambda x: x["speed"], reverse=True)
    new_items = [t for t in ts_sorted if not t["known"]]
    known_items = [t for t in ts_sorted if t["known"]]

    # チャンネル別集計
    ch = defaultdict(list)
    for t in ts: ch[t["channelName"]].append(t)
    ch_rank = sorted(ch.items(), key=lambda kv: median([x["speed"] for x in kv[1]]), reverse=True)

    os.makedirs(OUTDIR, exist_ok=True)
    out = os.path.join(OUTDIR, snap + ".md")
    L = []
    L.append("# 競合日次ランキング分析 " + snap + "(shorts-analyst)")
    L.append("")
    L.append("> データ=GAS comp_titles(days=30 top=200・速度=views/measurementDays)。"
             "台帳=competitor_daily_ledger.jsonl。既出=以前に分析済み(再解析せず事実だけ反映)。")
    L.append("")
    L.append("- 本日 %d本 / %dチャンネル / 新規%d本・既出%d本 / 速度中央値=%s・最大=%d"
             % (len(ts), len(ch), len(new_items), len(known_items), median([t["speed"] for t in ts]), ts_sorted[0]["speed"]))
    L.append("")
    L.append("## チャンネル別 伸び(速度中央値順)")
    L.append("| ch | 登録者 | 本数 | 速度中央値 | 速度最大 |")
    L.append("|---|---|---|---|---|")
    for name, vs in ch_rank:
        L.append("| %s | %d | %d | %s | %d |" %
                 (name, vs[0]["subscriberCount"], len(vs), median([x["speed"] for x in vs]), max(x["speed"] for x in vs)))
    L.append("")
    L.append("## 伸びた上位15(新規のみ深掘り・既出は既出印)")
    L.append("| # | 速度 | 型(数字) | 断/問 | ch | 題名 | 状態 |")
    L.append("|---|---|---|---|---|---|---|")
    for i, t in enumerate(ts_sorted[:15], 1):
        L.append("| %d | %d | %s | %s | %s | %s | %s |" %
                 (i, t["speed"], t["numType"], t["qType"], t["channelName"],
                  strip_tags(t["title"])[:32], "既出" if t["known"] else "新規"))
    L.append("")
    L.append("## 伸びてない下位10")
    L.append("| 速度 | 型(数字) | 断/問 | ch | 題名 |")
    L.append("|---|---|---|---|---|")
    for t in ts_sorted[-10:]:
        L.append("| %d | %s | %s | %s | %s |" %
                 (t["speed"], t["numType"], t["qType"], t["channelName"], strip_tags(t["title"])[:32]))
    L.append("")
    # 型×速度(SA-H004 検証の継続)
    L.append("## 数字型 × 速度中央値(SA-H004 継続監視)")
    L.append("| 型 | 本数 | 速度中央値 |")
    L.append("|---|---|---|")
    bytype = defaultdict(list)
    for t in ts: bytype[t["numType"]].append(t["speed"])
    for k in ["数字なし", "①数量煽り型", "②経過年月スパン型", "③固有数字型", "保留(曖昧数量)"]:
        if k in bytype:
            L.append("| %s | %d | %s |" % (k, len(bytype[k]), median(bytype[k])))
    L.append("")
    L.append("## 断定/問いかけ × 速度中央値(SA-H005 継続監視)")
    byq = defaultdict(list)
    for t in ts: byq[t["qType"]].append(t["speed"])
    L.append("| 型 | 本数 | 速度中央値 |")
    L.append("|---|---|---|")
    for k in ["断定", "問いかけ"]:
        if k in byq:
            L.append("| %s | %d | %s |" % (k, len(byq[k]), median(byq[k])))

    open(out, "w", encoding="utf-8").write("\n".join(L) + "\n")

    # 台帳追記(新規のみ)
    added = 0
    with open(LEDGER, "a", encoding="utf-8") as f:
        for t in new_items:
            f.write(json.dumps({
                "videoId": t["videoId"], "title": strip_tags(t["title"])[:60],
                "channelName": t["channelName"], "firstSeen": snap,
                "firstSpeed": t["speed"], "numType": t["numType"], "qType": t["qType"],
            }, ensure_ascii=False) + "\n")
            added += 1

    # --emit: 部屋へ流せる短いDiscord向けサマリだけを stdout に出す(毎朝の常駐が拾う用)
    if "--emit" in sys.argv:
        top = ts_sorted[0]
        lead = ch_rank[0]
        E = []
        E.append("競合ランキング %s(登録競合%dch/上位%d本・速度=1日再生・新規%d/既出%d)"
                 % (snap, len(ch), len(ts), len(new_items), len(known_items)))
        E.append("伸び頭=%s(登録%d・%d本・中央%s・最大%d「%s」)"
                 % (lead[0], lead[1][0]["subscriberCount"], len(lead[1]),
                    median([x["speed"] for x in lead[1]]), max(x["speed"] for x in lead[1]),
                    strip_tags(max(lead[1], key=lambda x: x["speed"])["title"])[:20]))
        E.append("伸びてない=%s(中央%s)・%s(中央%s)"
                 % (ch_rank[-1][0], median([x["speed"] for x in ch_rank[-1][1]]),
                    ch_rank[-2][0], median([x["speed"] for x in ch_rank[-2][1]])))
        E.append("数字型: ②スパン中央%s / ③固有中央%s / 数字なし中央%s"
                 % (median(bytype.get("②経過年月スパン型", [0])),
                    median(bytype.get("③固有数字型", [0])),
                    median(bytype.get("数字なし", [0]))))
        E.append("詳細=docs/departments/shorts-analyst/competitor_daily/%s.md" % snap)
        print("\n".join(E))
        return

    print("OUT:", out)
    print("new=%d known=%d added_to_ledger=%d" % (len(new_items), len(known_items), added))
    # 標準出力にもチャンネル別と型別サマリ
    print("--- channel(速度中央値順) ---")
    for name, vs in ch_rank:
        print("%s sub=%d n=%d med=%s max=%d" %
              (name, vs[0]["subscriberCount"], len(vs), median([x["speed"] for x in vs]), max(x["speed"] for x in vs)))
    print("--- numType ---")
    for k in ["数字なし", "①数量煽り型", "②経過年月スパン型", "③固有数字型", "保留(曖昧数量)"]:
        if k in bytype: print("%s n=%d med=%s" % (k, len(bytype[k]), median(bytype[k])))

if __name__ == "__main__":
    main()
