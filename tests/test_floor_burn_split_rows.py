# -*- coding: utf-8 -*-
"""floor_burn.scan_detail が「1返答=複数行」の記録を1回だけ数えることの検査。

★背景= 記録は1つの返答を content ブロックごとに複数行へ落とし、割れた行は usage を
  丸ごと同じ値で持つ。行のまま足すと2〜4重に数える(研究室HQが quota_burn.py で発見)。
★C-053= 「壊した側」は行を消した偽物ではなく**動く別の実装**へ戻して作る。
  ここでは ①行のまま数える旧実装 ②最初の1行を採る実装(quota_burn と同じ) の2本を当て、
  どちらもこの検査で赤くなることを確かめる(=検査がザルでないことの証明)。
使い方= python tests/test_floor_burn_split_rows.py
"""
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts", "llm"))
import quota_burn as q      # noqa: E402
import floor_burn as F      # noqa: E402

NOW = datetime.now(timezone.utc)
fails = []
mf = []


def eq(name, got, want):
    if got != want:
        fails.append("%s: 期待=%r 実際=%r" % (name, want, got))


def _row(mid, cc, cc1h, cc5m, cr, minutes_ago=5, model="claude-opus-5", sub=False):
    ts = (NOW - timedelta(minutes=minutes_ago)).isoformat().replace("+00:00", "Z")
    return json.dumps({
        "type": "assistant", "timestamp": ts, "isSidechain": sub,
        "message": {"id": mid, "model": model,
                    "usage": {"cache_creation_input_tokens": cc,
                              "cache_read_input_tokens": cr,
                              "cache_creation": {"ephemeral_1h_input_tokens": cc1h,
                                                 "ephemeral_5m_input_tokens": cc5m}}},
    }, ensure_ascii=False)


def _write(tmp, lines):
    """~/.claude/projects と同じ形の作業場を作る。sid は先頭8文字。"""
    d = os.path.join(tmp, "D--dummy")
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, "abcd1234-0000-0000-0000-000000000000.jsonl")
    with open(p, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return p


def run(lines, fn=None):
    """PROJECTS を作業場へ差し替えて scan_detail を通す。
    ★外へ出る手(=どのファイルを読むか)だけ偽物にし、判定と集計は本物のまま回す。"""
    tmp = tempfile.mkdtemp(prefix="floorburn_")
    try:
        _write(tmp, lines)
        old_p, old_m = q.PROJECTS, q.dept_map
        q.PROJECTS = tmp
        q.dept_map = lambda: {"abcd1234": "aegis-gl"}
        try:
            return (fn or F.scan_detail)(NOW - timedelta(hours=1))
        finally:
            q.PROJECTS, q.dept_map = old_p, old_m
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def tot(rows, k):
    return sum(r[k] for r in rows)


# --- 1. 1返答が3行に割れている(usageは全行同じ)= 1便・1回だけ数える -------------
SPLIT3 = [_row("msg_A", 30000, 30000, 0, 500000)] * 3
r = run(SPLIT3)
eq("割れた3行は1便", len(r), 1)
eq("書込は1回だけ", tot(r, "cc"), 30000)
eq("読込は1回だけ", tot(r, "cr"), 500000)
eq("1時間TTLも1回だけ", tot(r, "cc1h"), 30000)

# --- 2. 別の返答は別に数える(潰しすぎない) -------------------------------------
TWO = SPLIT3 + [_row("msg_B", 7000, 0, 7000, 90000)] * 2
r = run(TWO)
eq("2返答=2便", len(r), 2)
eq("2返答の書込", tot(r, "cc"), 37000)
eq("2返答の5分TTL", tot(r, "cc5m"), 7000)

# --- 3. ★割れた行のusageが揃っていない時は、大きい方を採る(0の行に潰されない) ---
#   実測= 直近24時間の2,725件中1件だけ、片方が全部0だった。0を先に掴むと返答が丸ごと消える。
ZERO_FIRST = [_row("msg_C", 0, 0, 0, 0), _row("msg_C", 1167, 1167, 0, 123750)]
r = run(ZERO_FIRST)
eq("0が先でも1便", len(r), 1)
eq("0が先でも書込を落とさない", tot(r, "cc"), 1167)
eq("0が先でも読込を落とさない", tot(r, "cr"), 123750)

# --- 4. 既存の除外条件を壊していない ---------------------------------------------
eq("<synthetic>は除外", len(run([_row("msg_D", 100, 100, 0, 1, model="<synthetic>")])), 0)
eq("窓の外は除外", len(run([_row("msg_E", 100, 100, 0, 1, minutes_ago=600)])), 0)
eq("assistant以外は除外",
   len(run([json.dumps({"type": "user", "timestamp": NOW.isoformat(),
                        "message": {"id": "msg_F", "usage": {"a": 1}}})])), 0)

# --- 5. idが無い行は落とさない(古い記録・fail-open) -----------------------------
NOID = [_row("", 500, 500, 0, 10), _row("", 600, 600, 0, 20)]
eq("idが無い行は潰さない", len(run(NOID)), 2)
eq("idが無い行の書込", tot(run(NOID), "cc"), 1100)

# --- 6. ファイルが違えば同じidでも別物として数える -------------------------------
#   (idはセッションを跨いで衝突しない前提だが、跨ぐなら分けて数える側が安全)
eq("sidは記録どおり", run(SPLIT3)[0]["sid"], "abcd1234")
eq("部門は名簿どおり", run(SPLIT3)[0]["dept"], "aegis-gl")


# === must-fail(C-053)= 動く別の実装2本が、この検査で赤くなるか ===================
def _mf_by_line(since_utc):
    """別実装A= 直す前の floor_burn(行のまま数える)。検査1で赤くなるはず。"""
    import glob
    dm = q.dept_map()
    out = []
    for p in glob.glob(os.path.join(q.PROJECTS, "**", "*.jsonl"), recursive=True):
        with open(p, encoding="utf-8", errors="replace") as f:
            for line in f:
                if '"usage"' not in line:
                    continue
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if d.get("type") != "assistant":
                    continue
                msg = d.get("message") or {}
                if str(msg.get("model") or "") == "<synthetic>":
                    continue
                dt = datetime.fromisoformat(str(d.get("timestamp")).replace("Z", "+00:00"))
                if dt < since_utc:
                    continue
                u = msg.get("usage") or {}
                cd = u.get("cache_creation") or {}
                out.append({"sid": os.path.basename(p)[:8],
                            "dept": dm.get(os.path.basename(p)[:8]) or "?", "dt": dt,
                            "cc": u.get("cache_creation_input_tokens", 0) or 0,
                            "cc1h": cd.get("ephemeral_1h_input_tokens", 0) or 0,
                            "cc5m": cd.get("ephemeral_5m_input_tokens", 0) or 0,
                            "cr": u.get("cache_read_input_tokens", 0) or 0,
                            "model": msg.get("model") or "?",
                            "sub": bool(d.get("isSidechain"))})
    return out


def _first_wins_by_id(since_utc):
    """別実装B= quota_burn と同じ「最初の1行を採る」。検査3で赤くなるはず。"""
    import glob
    dm = q.dept_map()
    out, seen = [], set()
    for p in glob.glob(os.path.join(q.PROJECTS, "**", "*.jsonl"), recursive=True):
        with open(p, encoding="utf-8", errors="replace") as f:
            for line in f:
                if '"usage"' not in line:
                    continue
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if d.get("type") != "assistant":
                    continue
                msg = d.get("message") or {}
                if str(msg.get("model") or "") == "<synthetic>":
                    continue
                dt = datetime.fromisoformat(str(d.get("timestamp")).replace("Z", "+00:00"))
                if dt < since_utc:
                    continue
                mid = str(msg.get("id") or "")
                if mid:
                    if mid in seen:
                        continue
                    seen.add(mid)
                u = msg.get("usage") or {}
                cd = u.get("cache_creation") or {}
                out.append({"sid": os.path.basename(p)[:8],
                            "dept": dm.get(os.path.basename(p)[:8]) or "?", "dt": dt,
                            "cc": u.get("cache_creation_input_tokens", 0) or 0,
                            "cc1h": cd.get("ephemeral_1h_input_tokens", 0) or 0,
                            "cc5m": cd.get("ephemeral_5m_input_tokens", 0) or 0,
                            "cr": u.get("cache_read_input_tokens", 0) or 0,
                            "model": msg.get("model") or "?",
                            "sub": bool(d.get("isSidechain"))})
    return out


if len(run(SPLIT3, fn=_mf_by_line)) == 1:
    mf.append("別実装A(行のまま数える)が検査1で赤くならなかった=検査がザル")
if tot(run(ZERO_FIRST, fn=_first_wins_by_id), "cc") == 1167:
    mf.append("別実装B(最初の1行を採る)が検査3で赤くならなかった=検査がザル")

if fails or mf:
    print("FAIL floor_burn の重複行つぶし")
    for x in fails + mf:
        print("  - " + x)
    sys.exit(1)
print("PASS floor_burn.scan_detail は1返答を1回だけ数える"
      "(割れた行つぶし・0行に潰されない・must-fail 2本が赤)")
