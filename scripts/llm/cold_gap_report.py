# -*- coding: utf-8 -*-
"""cold_gap_report — 「全書き直し(冷え)便」の**直前の便からの間隔**の分布を取り直す。

★元は使い捨ての探針(local/_work/probe_cold_gap_20260829.py)。HQ-0220 の
  「★**1日の投函数が200を超えた日が来たら、その日のうちに冷えの間隔分布を取り直す**
   ——この引き金をそっちの側の仕組みに載せてくれ(人の記憶に置くな)」
  を満たすため、**引き金から呼べる形**(text() を返す関数)にして本番の scripts/ へ移した。
  呼び口= scripts/llm/watch_triggers.py の T1。

★冷えの定義= 境目の便のうち読込が床の残骸まで落ちたもの(cache_read <= COLD_READ)。
  「書込>2万」を代理に使うと**会話が伸びただけの便**を巻き込む(前の探針の弱点)。
"""
import datetime
import glob
import io
import json
import os
import sys

COLD_READ = 20000
W_WRITE, W_READ = 2.0, 0.1
WARM_MIN = 55.0
ROOT_PROJ = os.path.expanduser("~/.claude/projects")
SKIP = ("probe-bnd", "floorprobe", "prefixlab", "pb2")

BANDS = [(0, 60, "1分未満"), (60, 300, "1〜5分"), (300, 1800, "5〜30分"),
         (1800, 3300, "30〜55分"), (3300, 3900, "★55〜65分(1時間の境)"),
         (3900, 7200, "65分〜2時間"), (7200, 21600, "2〜6時間"),
         (21600, 10 ** 9, "6時間以上")]


def _band(sec):
    for lo, hi, name in BANDS:
        if lo <= sec < hi:
            return name
    return "?"


def _tool_result_only(d):
    c = (d.get("message") or {}).get("content")
    if not isinstance(c, list) or not c:
        return False
    return all(isinstance(b, dict) and b.get("type") == "tool_result" for b in c)


def _med(v):
    v = sorted(v)
    return 0 if not v else v[len(v) // 2]


def collect(hours=168.0):
    """(gap秒, 書込, 読込, 冷えか) の並びを返す。"""
    cut = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=hours)
    rows = []
    for p in glob.glob(os.path.join(ROOT_PROJ, "**", "*.jsonl"), recursive=True):
        q = p.replace("\\", "/")
        if any(k in q for k in SKIP):
            continue
        try:
            if datetime.datetime.now().timestamp() - os.path.getmtime(p) > hours * 3600:
                continue
        except OSError:
            continue
        recs = []
        for ln in io.open(p, encoding="utf-8", errors="replace"):
            ln = ln.strip()
            if not ln:
                continue
            try:
                recs.append(json.loads(ln))
            except ValueError:
                continue
        seen = set()
        prev_t = {False: None, True: None}
        prev_model = {False: None, True: None}
        for i, d in enumerate(recs):
            msg = d.get("message") or {}
            if msg.get("role") != "assistant":
                continue
            mid = msg.get("id")
            if not mid or mid in seen or str(msg.get("model") or "") == "<synthetic>":
                continue
            seen.add(mid)
            try:
                t = datetime.datetime.fromisoformat(str(d.get("timestamp")).replace("Z", "+00:00"))
            except ValueError:
                continue
            sub = bool(d.get("isSidechain"))
            gap = None if prev_t[sub] is None else (t - prev_t[sub]).total_seconds()
            pm0, model = prev_model[sub], msg.get("model")
            prev_t[sub], prev_model[sub] = t, (model or pm0)
            kind = "境目"
            for j in range(i - 1, max(-1, i - 12), -1):
                pm = recs[j].get("message") or {}
                if pm.get("role") == "user":
                    if _tool_result_only(recs[j]):
                        kind = "途中"
                    break
                if pm.get("role") == "assistant" and pm.get("id") != mid:
                    kind = "途中"
                    break
            if kind != "境目" or gap is None or gap < 0 or t < cut:
                continue
            if pm0 and model and model != pm0:
                continue                      # モデル切替直後は必ず作り直し=別枠
            u = msg.get("usage") or {}
            rows.append((gap, u.get("cache_creation_input_tokens", 0) or 0,
                         u.get("cache_read_input_tokens", 0) or 0,
                         (u.get("cache_read_input_tokens", 0) or 0) <= COLD_READ))
    return rows


def summary(hours=168.0):
    """(本文, 数字の辞書) を返す。台帳へ積むのは辞書のほう。"""
    rows = collect(hours)
    cold = [r for r in rows if r[3]]
    warm = [r for r in rows if not r[3]]
    L = ["■ 冷え(全書き直し)便の間隔分布 / 直近 %g時間 / 境目 %d本(冷え %d・温 %d)"
         % (hours, len(rows), len(cold), len(warm)),
         "  冷えの定義= 読込 <= %s(前置きが生き残っていない)" % f"{COLD_READ:,}",
         "",
         "  %-22s %6s %8s" % ("間隔", "本数", "割合")]
    for _, _, name in BANDS:
        g = [r for r in cold if _band(r[0]) == name]
        if g:
            L.append("  %-22s %6d %7.1f%%" % (name, len(g), 100.0 * len(g) / max(1, len(cold))))
    n_over = sum(1 for r in cold if r[0] >= 3600)
    pct_over = 100.0 * n_over / max(1, len(cold))
    L.append("  → 冷え便のうち **1時間以上あいていたもの= %d/%d (%.1f%%)**"
             % (n_over, len(cold), pct_over))

    cc_c, cr_c = _med([r[1] for r in cold]), _med([r[2] for r in cold])
    cc_w, cr_w = _med([r[1] for r in warm]), _med([r[2] for r in warm])
    cost_c = cc_c * W_WRITE + cr_c * W_READ
    cost_w = cc_w * W_WRITE + cr_w * W_READ
    extra = cost_c - cost_w
    pulse = cr_w * W_READ + 1000 * W_WRITE
    # ★分岐は「脈の本数」と「間隔の時間」の2つの顔を持つ。写像は1本だけ置いて
    #   本文と台帳の両方がこれを見る(同じ数を2箇所で計算しない)。
    be_pulses = (extra / pulse) if pulse else 0.0
    be_sec = (be_pulses + 1) * WARM_MIN * 60.0 if pulse else 0.0
    n_over_be = sum(1 for r in cold if r[0] >= be_sec) if pulse else 0
    L += ["",
          "  冷え1回の追加コスト(重み付き)= %s / 保温1脈= %s" % (f"{extra:,.0f}", f"{pulse:,.0f}"),
          "  ★分岐= 保温 %.2f回まで(= 間隔 %.1f時間まで)" % (be_pulses, be_sec / 3600.0),
          "  → 冷え便のうち **分岐を越えていたもの= %d/%d (%.1f%%)**"
          % (n_over_be, len(cold), 100.0 * n_over_be / max(1, len(cold)))]
    d = {"hours": hours, "n": len(rows), "cold": len(cold), "warm": len(warm),
         "over1h": n_over, "over1h_pct": round(pct_over, 1),
         "cold_write_med": cc_c, "cold_read_med": cr_c,
         "warm_write_med": cc_w, "warm_read_med": cr_w,
         "extra": round(extra), "pulse": round(pulse),
         "breakeven_pulses": round(be_pulses, 2) if pulse else None,
         # ★次に測り直した時、行と行だけで裁定の向きを比べられるようにする。
         #   2026-09-02の比較で、分布(bands)と分岐の越え数が行に無くて突き合わせられなかった。
         "breakeven_hours": round(be_sec / 3600.0, 2) if pulse else None,
         "over_breakeven": n_over_be,
         "over_breakeven_pct": round(100.0 * n_over_be / max(1, len(cold)), 1),
         "bands": {name: sum(1 for r in cold if _band(r[0]) == name)
                   for _, _, name in BANDS}}
    return "\n".join(L), d


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(summary(float(sys.argv[1]) if len(sys.argv) > 1 else 168.0)[0])
