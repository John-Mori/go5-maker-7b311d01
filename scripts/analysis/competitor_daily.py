# -*- coding: utf-8 -*-
"""競合チャンネル日次ランキング分析(shorts-analyst / 三笘薫・アーモンドアイ担当)
毎朝の運用: python scripts/analysis/competitor_daily.py
 - GAS comp_titles(速度=views/measurementDays 順)を取得
 - videoId 単位の台帳(competitor_daily_ledger.jsonl)と突合し「新規/既出」を分ける
   → 既出(=以前に分析済みの同一動画がまた上位に居る)は再解析せず事実だけ反映(Chami指示2026-08-13)
 - 伸びた(高速)/伸びてない(低速)を出し、題名を SA-H004 数字3型・SA-H005 断定/問いかけ で符号化
 - ★順位表を貼るだけにしない(Chami指示2026-08-16「ただ表示するだけでは意味がない」)。
   日次メトリクスを competitor_daily_metrics.jsonl に貯め、多日トレンドから「所見(なぜ/次の一手)」を
   データ駆動で生成する。所見=測った値からしか書かない(捏造しない)。
 - 当日レポートを docs/departments/shorts-analyst/competitor_daily/<date>.md へ(所見を先頭に)
 - 新規 videoId を台帳へ追記(次回から既出扱い)
数字は測って出す(捏造しない)。速度=当日スナップの velocity 代理値(views/measurementDays)。
"""
import json, re, sys, os, subprocess, glob, math
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LEDGER = os.path.join(ROOT, "docs", "departments", "shorts-analyst", "competitor_daily_ledger.jsonl")
METRICS = os.path.join(ROOT, "docs", "departments", "shorts-analyst", "competitor_daily_metrics.jsonl")
OUTDIR = os.path.join(ROOT, "docs", "departments", "shorts-analyst", "competitor_daily")

# --- 数字型分類(SA-H004 の3型・ハッシュタグ除去後に判定) ---
KANJI = "〇零一二三四五六七八九十百千万億"
DIGIT = re.compile(r"[0-9０-９" + KANJI + r"]")
HYPE = ["選", "つ", "個", "連", "ランキング", "ベスト", "TOP", "秒後", "種類", "コ目", "第", "位", "大", "つの"]
SPAN = ["週", "ヶ月", "か月", "年後", "日連続", "レベル", "分後", "たった", "わずか", "年で", "日で", "ヶ月で"]
INTR = ["歳", "回", "万円", "円", "人", "番", "点", "cm", "kg", "時", "分", "%"]
NUMTYPES = ["数字なし", "①数量煽り型", "②経過年月スパン型", "③固有数字型", "保留(曖昧数量)"]

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

# 負けテンプレ候補=【話題】ラベル付き or 語尾w(草)。監視して負けが続くならコピー部へ「使うな」を渡す。
def is_waru(title):
    t = strip_tags(title)
    return ("【話題】" in t) or bool(re.search(r"[wｗ]+$", t))

def median(xs):
    xs = sorted(xs)
    n = len(xs)
    if n == 0: return 0
    return xs[n//2] if n % 2 else (xs[n//2-1]+xs[n//2])/2

def spearman(xs, ys):
    """順位相関(登録者×初速)。n<3 や分散0は None。"""
    n = len(xs)
    if n < 3: return None
    def ranks(a):
        order = sorted(range(len(a)), key=lambda i: a[i])
        r = [0]*len(a)
        for rk, i in enumerate(order): r[i] = rk
        return r
    rx, ry = ranks(xs), ranks(ys)
    mx, my = sum(rx)/n, sum(ry)/n
    cov = sum((rx[i]-mx)*(ry[i]-my) for i in range(n))
    sx = (sum((v-mx)**2 for v in rx))**0.5
    sy = (sum((v-my)**2 for v in ry))**0.5
    if sx == 0 or sy == 0: return None
    return round(cov/(sx*sy), 2)

def _norm_cdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))

def mannwhitney(a, b):
    """2群の速度差の有意性(Mann-Whitney U・タイ補正つき正規近似・両側p)。
    n<3 は None。中央値の見かけの差が『本物か・サンプル薄の偶然か』を分ける。"""
    na, nb = len(a), len(b)
    if na < 3 or nb < 3: return None
    comb = sorted([(v, 0) for v in a] + [(v, 1) for v in b])
    N = len(comb)
    ranks = [0.0] * N
    i = 0
    while i < N:  # タイは平均順位
        j = i
        while j + 1 < N and comb[j + 1][0] == comb[i][0]: j += 1
        avg = (i + j) / 2.0 + 1
        for k in range(i, j + 1): ranks[k] = avg
        i = j + 1
    Ra = sum(ranks[k] for k in range(N) if comb[k][1] == 0)
    Ua = Ra - na * (na + 1) / 2.0
    U = min(Ua, na * nb - Ua)
    mu = na * nb / 2.0
    counts = defaultdict(int)
    for v, _ in comb: counts[v] += 1
    tie = sum(t ** 3 - t for t in counts.values())
    sigma = math.sqrt(na * nb / 12.0 * ((N + 1) - tie / (N * (N - 1)))) if N > 1 else 0
    if sigma == 0: return None
    z = (U - mu) / sigma
    return [round(U, 1), round(2 * (1 - _norm_cdf(abs(z))), 4)]

def within_channel_norm(ts, keyfn):
    """チャンネル内zスコアで正規化してから特徴量別に平均する=『勝者チャンネルに偏っているだけ』を除く。
    各chの速度を平均0/分散1へ揃え、特徴量ごとにzの平均を出す(n>=3・分散>0のchのみ)。"""
    by_ch = defaultdict(list)
    for t in ts: by_ch[t["channelName"]].append(t)
    z_by = defaultdict(list)
    for name, items in by_ch.items():
        if len(items) < 3: continue
        sp = [x["speed"] for x in items]
        m = sum(sp) / len(sp)
        sd = (sum((v - m) ** 2 for v in sp) / len(sp)) ** 0.5
        if sd == 0: continue
        for x in items:
            z_by[keyfn(x)].append((x["speed"] - m) / sd)
    return {k: [len(v), round(sum(v) / len(v), 2)] for k, v in z_by.items()}

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

# ---------- メトリクス(多日トレンドの土台) ----------
def load_metrics():
    rows = {}
    if os.path.exists(METRICS):
        for line in open(METRICS, encoding="utf-8"):
            line = line.strip()
            if not line: continue
            r = json.loads(line)
            rows[r["date"]] = r
    return rows

def save_metrics(rows):
    with open(METRICS, "w", encoding="utf-8") as f:
        for d in sorted(rows):
            f.write(json.dumps(rows[d], ensure_ascii=False) + "\n")

def backfill_from_md(rows):
    """metrics に無い過去日は既存レポート(.md)の集計表から byQ/byType/channels を復元して種にする。
    template(負けテンプレ)は題名全体が要るので過去日は None(当日以降のみ実測)。"""
    for path in sorted(glob.glob(os.path.join(OUTDIR, "*.md"))):
        date = os.path.splitext(os.path.basename(path))[0]
        if date in rows:
            continue
        s = open(path, encoding="utf-8").read()
        byq = {}
        for k in ["断定", "問いかけ"]:
            m = re.search(r"\| %s \| (\d+) \| ([\d.]+) \|" % re.escape(k), s)
            if m: byq[k] = [int(m.group(1)), float(m.group(2))]
        byt = {}
        for k in NUMTYPES:
            m = re.search(r"\| %s \| (\d+) \| ([\d.]+) \|" % re.escape(k), s)
            if m: byt[k] = [int(m.group(1)), float(m.group(2))]
        chans = []
        blk = re.search(r"## チャンネル別[^\n]*\n(.*?)(?:\n##|\Z)", s, re.S)
        if blk:
            for line in blk.group(1).splitlines():
                cells = [c.strip() for c in line.strip().strip("|").split("|")]
                cells = [c for c in cells if c != ""]
                if len(cells) < 5: continue
                if cells[-1] == "速度最大" or cells[0] in ("ch", "---"): continue
                try:
                    subs, cnt, med, mx = int(cells[-4]), int(cells[-3]), float(cells[-2]), int(cells[-1])
                except ValueError:
                    continue
                name = " | ".join(cells[:-4])
                chans.append([name, subs, cnt, med, mx])
        hm = re.search(r"速度中央値=([\d.]+)・最大=(\d+)", s)
        if not (byq and byt): continue
        rows[date] = {
            "date": date, "n": None,
            "medAll": float(hm.group(1)) if hm else None,
            "medMax": int(hm.group(2)) if hm else None,
            "byType": byt, "byQ": byq, "channels": chans,
            "templateWaru": None,
            "spearmanSubsSpeed": spearman([c[1] for c in chans if c[2] >= 3],
                                          [c[3] for c in chans if c[2] >= 3]) if chans else None,
        }

def shoken(rows, snap):
    """所見=多日メトリクスから、測った値だけで『なぜ/次の一手』を生成する。"""
    dates = sorted(rows)
    today = rows[snap]
    L = []

    # 1) 問いかけ vs 断定(連続で勝っているか)
    def q_win(r):
        bq = r.get("byQ", {})
        return ("断定" in bq and "問いかけ" in bq and bq["問いかけ"][1] > bq["断定"][1])
    streak = 0
    for d in reversed(dates):
        if q_win(rows[d]): streak += 1
        else: break
    bq = today.get("byQ", {})
    if "断定" in bq and "問いかけ" in bq:
        toi, dan = bq["問いかけ"], bq["断定"]
        ratio = round(toi[1]/dan[1], 2) if dan[1] else 0
        if q_win(today):
            L.append("・問いかけ型(？付き)が断定を%s倍(問%s/断%s)。直近%d日連続で？型が上=偶然ではない。"
                     "ただしn=%d本と薄い→次バッチで？型を1-2本、断定と1要素だけ変えて試すのが手堅い。"
                     % (ratio, toi[1], dan[1], streak, toi[0]))
        else:
            L.append("・今日は断定(%s)≧問いかけ(%s)。連勝が止まった=？型の優位はサンプル次第。断定を主軸に戻す。"
                     % (dan[1], toi[1]))
    # 1b) 見かけの差は有意か(Mann-Whitney)=n薄の偶然と本物を分ける
    mw = today.get("mwQ")
    if mw:
        p = mw[1]
        if p < 0.05:
            L.append("・その？型優位はMann-Whitney検定で有意(p=%s<0.05)=本数が薄くても偶然ではない。動かしてよい。" % p)
        elif p < 0.10:
            L.append("・ただし検定はp=%s(0.05に未達・傾向どまり)=断言はまだ。次バッチで本数を足して再検定。" % p)
        else:
            L.append("・ただしMann-Whitney検定ではp=%s=有意でない=中央値の差はサンプルのブレの範囲。全面採用は待つ。" % p)
    # 1c) チャンネル交絡を除いても？型は効くか(チャンネル内zスコア)
    znq = today.get("znQ") or {}
    if "断定" in znq and "問いかけ" in znq:
        zt, zd = znq["問いかけ"][1], znq["断定"][1]
        if zt - zd >= 0.15:
            L.append("・チャンネル差を補正(各ch内zスコア)しても？型z=%s>断定z=%s=勝者chの偏りでなく型そのものが効いている。" % (zt, zd))
        elif zd - zt >= 0.15:
            L.append("・チャンネル補正すると？型z=%s<断定z=%s=見えていた差の実体は"
                     "『？型を使うchが元々強い』=型でなくch効果。素材選びの方を見直す。" % (zt, zd))
        else:
            L.append("・チャンネル補正すると？型z=%s≒断定z=%s=差はほぼ消える。検定のp値と合わせ"
                     "『？型に初速の押し上げ効果はほぼ無い』と読む。優先度は下げる。" % (zt, zd))

    # 2) 数字は効くか(固有の上振れ・曖昧煽りの沈み)
    bt = today.get("byType", {})
    if "数字なし" in bt:
        base = bt["数字なし"][1]
        def lows(r):  # 曖昧数量が最下位付近か
            t = r.get("byType", {})
            if "保留(曖昧数量)" not in t or "数字なし" not in t: return False
            return t["保留(曖昧数量)"][1] < t["数字なし"][1]
        low_streak = 0
        for d in reversed(dates):
            if lows(rows[d]): low_streak += 1
            else: break
        koyu = bt.get("③固有数字型", [0, 0])[1]
        edge = round(koyu/base, 2) if base else 0
        vague = bt.get("保留(曖昧数量)", [0, 0])[1]
        L.append("・数字は初速のレバーになっていない(中央値ベース)。固有数字%s÷数字なし%s=%s倍(≒等倍=上乗せ無し)。"
                 "曖昧な数量煽りは%s(数字なしの%d%%)で%d日連続の最下位圏。○選・たった○週間・ランキングは不要。"
                 % (koyu, base, edge, vague, int(vague/base*100) if base else 0, low_streak))
        # 2b) チャンネル補正zで検算=中央値が交絡で隠していた符号を拾う
        znt = today.get("znType") or {}
        zk = znt.get("③固有数字型", [0, 0])[1]
        zn = znt.get("数字なし", [0, 0])[1]
        zv = znt.get("保留(曖昧数量)", [0, 0])[1]
        if "③固有数字型" in znt and zk >= 0.15 and zk > zn:
            L.append("・ただしチャンネル補正zで見ると固有数字z=%s>数字なしz=%s=中央値が隠していたが"
                     "『歳・回・円・番』等の固有数字は自ch平均より速い=交絡を除くと効く。数量煽りとは別物として扱う。" % (zk, zn))
        if "保留(曖昧数量)" in znt and zv <= -0.15:
            L.append("・曖昧数量煽りはチャンネル補正zでも%s(最下位)=中央値と符号一致=どの角度からも効かない。確定で外す。" % zv)

    # 3) 負けテンプレ(当日実測がある時のみ)
    tw = today.get("templateWaru")
    if tw and tw[0] >= 3 and today.get("medAll"):
        pct = int(tw[1]/today["medAll"]*100)
        if pct < 80:
            L.append("・【話題】〜w型(n=%d 中央%s)は全体中央%sの%d%%=負けテンプレ。うちのコピーでは避ける。"
                     % (tw[0], tw[1], today["medAll"], pct))

    # 4) 登録者数は初速を予測するか
    rho = today.get("spearmanSubsSpeed")
    if rho is not None:
        if abs(rho) < 0.4:
            L.append("・登録者数×初速の順位相関ρ=%s=ほぼ無相関。規模でなく1本のフックで決まる=小規模でも上位を取れる(追い風)。" % rho)
        elif rho >= 0.4:
            L.append("・登録者数×初速ρ=%s=規模がやや効く。フック単独では跳ねにくい局面。" % rho)
        else:
            L.append("・登録者数×初速ρ=%s=規模が大きいほど初速が鈍い逆相関。新規/中堅のフックが刺さっている。" % rho)

    return L

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

    bytype = defaultdict(list)
    for t in ts: bytype[t["numType"]].append(t["speed"])
    byq = defaultdict(list)
    for t in ts: byq[t["qType"]].append(t["speed"])

    # 負けテンプレ(当日コーパス実測)
    waru = [t["speed"] for t in ts if is_waru(t["title"])]

    # 今日のメトリクスを組み立て → 多日トレンドへ
    chans = [[name, vs[0]["subscriberCount"], len(vs),
              median([x["speed"] for x in vs]), max(x["speed"] for x in vs)] for name, vs in ch_rank]
    metrics = load_metrics()
    backfill_from_md(metrics)
    metrics[snap] = {
        "date": snap, "n": len(ts),
        "medAll": median([t["speed"] for t in ts]), "medMax": ts_sorted[0]["speed"],
        "byType": {k: [len(bytype[k]), median(bytype[k])] for k in NUMTYPES if k in bytype},
        "byQ": {k: [len(byq[k]), median(byq[k])] for k in ["断定", "問いかけ"] if k in byq},
        "channels": chans,
        "templateWaru": [len(waru), median(waru)] if waru else None,
        "spearmanSubsSpeed": spearman([c[1] for c in chans if c[2] >= 3],
                                      [c[3] for c in chans if c[2] >= 3]),
        # 多角的検証(Chami指示2026-08-16「多角的視点で」)=見かけの差の有意性とチャンネル交絡の除去
        "mwQ": mannwhitney(byq.get("問いかけ", []), byq.get("断定", [])),
        "znQ": within_channel_norm(ts, lambda x: x["qType"]),
        "znType": within_channel_norm(ts, lambda x: x["numType"]),
    }
    save_metrics(metrics)
    sho = shoken(metrics, snap)

    os.makedirs(OUTDIR, exist_ok=True)
    out = os.path.join(OUTDIR, snap + ".md")
    L = []
    L.append("# 競合日次ランキング分析 " + snap + "(shorts-analyst)")
    L.append("")
    L.append("> データ=GAS comp_titles(days=30 top=200・速度=views/measurementDays)。"
             "台帳=competitor_daily_ledger.jsonl。既出=以前に分析済み(再解析せず事実だけ反映)。")
    L.append("")
    L.append("## 所見(なぜ/次の一手・多日トレンドから自動生成)")
    if sho:
        L.extend(sho)
    else:
        L.append("・トレンド蓄積中(所見は複数日そろってから出る)。")
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
    L.append("## 伸びた上位10(新規のみ深掘り・既出は既出印)")
    L.append("| # | 速度 | 型(数字) | 断/問 | ch | 題名 | 状態 |")
    L.append("|---|---|---|---|---|---|---|")
    for i, t in enumerate(ts_sorted[:10], 1):
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
    for k in NUMTYPES:
        if k in bytype:
            L.append("| %s | %d | %s |" % (k, len(bytype[k]), median(bytype[k])))
    L.append("")
    L.append("## 断定/問いかけ × 速度中央値(SA-H005 継続監視)")
    L.append("| 型 | 本数 | 速度中央値 |")
    L.append("|---|---|---|")
    for k in ["断定", "問いかけ"]:
        if k in byq:
            L.append("| %s | %d | %s |" % (k, len(byq[k]), median(byq[k])))
    L.append("")
    # 多角的検証(Chami指示2026-08-16)=中央値の見かけを、有意性とチャンネル交絡で二重に検算する
    m = metrics[snap]
    L.append("## 多角的検証(有意差・チャンネル補正)")
    if m.get("mwQ"):
        L.append("- 問いかけ vs 断定 の速度差 Mann-Whitney U=%s / p=%s(両側・タイ補正)"
                 "%s" % (m["mwQ"][0], m["mwQ"][1], "=有意(p<0.05)" if m["mwQ"][1] < 0.05 else
                         ("=傾向(p<0.10)" if m["mwQ"][1] < 0.10 else "=有意でない")))
    L.append("")
    L.append("### チャンネル内zスコア平均(各ch内で平均0・分散1に揃えてから比較=規模/勝者chの偏りを除去)")
    L.append("| 断/問 | 本数(補正対象) | z平均 |")
    L.append("|---|---|---|")
    for k in ["断定", "問いかけ"]:
        if k in m.get("znQ", {}):
            L.append("| %s | %d | %s |" % (k, m["znQ"][k][0], m["znQ"][k][1]))
    L.append("")
    L.append("| 数字型 | 本数(補正対象) | z平均 |")
    L.append("|---|---|---|")
    for k in NUMTYPES:
        if k in m.get("znType", {}):
            L.append("| %s | %d | %s |" % (k, m["znType"][k][0], m["znType"][k][1]))
    L.append("")
    L.append("> z平均>0=そのchの平均より速い / <0=遅い。中央値表と符号が食い違う型は"
             "『チャンネル効果を型の効果と見間違えていた』サイン。")

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

    # --emit: 部屋へ流せる短いDiscord向けサマリ(所見を先頭に=表示でなく分析を運ぶ)
    if "--emit" in sys.argv:
        E = []
        E.append("競合ランキング分析 %s(登録競合%dch/上位%d本・速度=1日再生・新規%d/既出%d)"
                 % (snap, len(ch), len(ts), len(new_items), len(known_items)))
        E.append("【所見】")
        E.extend(sho if sho else ["・トレンド蓄積中(複数日そろってから所見が出る)。"])
        lead = ch_rank[0]
        E.append("【地力】伸び頭=%s(登録%d・%d本・中央%s・最大%d「%s」)"
                 % (lead[0], lead[1][0]["subscriberCount"], len(lead[1]),
                    median([x["speed"] for x in lead[1]]), max(x["speed"] for x in lead[1]),
                    strip_tags(max(lead[1], key=lambda x: x["speed"])["title"])[:20]))
        E.append("詳細=docs/departments/shorts-analyst/competitor_daily/%s.md" % snap)
        print("\n".join(E))
        return

    print("OUT:", out)
    print("new=%d known=%d added_to_ledger=%d" % (len(new_items), len(known_items), added))
    print("--- 所見 ---")
    for s in sho: print(s)
    print("--- channel(速度中央値順) ---")
    for name, vs in ch_rank:
        print("%s sub=%d n=%d med=%s max=%d" %
              (name, vs[0]["subscriberCount"], len(vs), median([x["speed"] for x in vs]), max(x["speed"] for x in vs)))
    print("--- numType ---")
    for k in NUMTYPES:
        if k in bytype: print("%s n=%d med=%s" % (k, len(bytype[k]), median(bytype[k])))

if __name__ == "__main__":
    main()
