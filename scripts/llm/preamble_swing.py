#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""preamble_swing — **前置きの長さが前便と変わった便で、キャッシュ書込が増えるか**を測る。読むだけ。

★なぜ要るか(2026-08-23 研究室HQ msg DISPATCH-aegis-gl-1787469264964)
  HQの見立て=「部屋を変えても折れる位置が同じ6か所——**それは便の中身ではなく、
  便の"前"に毎回積まれている物が動いている、という形だ。**」
  共通規律は『変わった時・圧縮直後・10便に1回は全文、それ以外は指紋1行』で長さが交互に変わる。
  全文と指紋では前置きが数千字ずれる= **その後ろが全部作り直しになる**(キャッシュの前方一致が切れる)。
  HQ原文=「測っていないから断定はしない。」→ **この道具が測る。**

★測り方(推定ではなく突き合わせ)
  ① `local/llm/request_log.jsonl` の evidence に **`規律=全文` / `規律=3行`** が実際に書かれている
     (`session_relay.py:4667` 等)。ここから「その便の前置きが全文だったか」を取る。
  ② `floor_burn.scan_detail` で **便ごとの実測キャッシュ書込**(cc)を取る。
  ③ session と時刻で突き合わせ、**前便と前置きの種別が変わった便**(swing)と
     **変わらなかった便**(same)で、書込の中央値を比べる。

★★must-fail(C-053)= ラベルだけを混ぜた対照を同時に出す。
  前置きの種別と書込に関係が無ければ、混ぜても差は変わらないはずだ。
  **本物の差と混ぜた差が同じなら、この道具は何も見ていない。**そう出たらそう書く。

    python scripts/llm/preamble_swing.py --hours 72
"""
import argparse
import collections
import io
import json
import os
import random
import re
import sys
from datetime import datetime, timedelta, timezone

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)

import floor_burn as fb              # noqa: E402
import quota_burn as q               # noqa: E402

JST = timezone(timedelta(hours=9))
UTC = timezone.utc
REQ_LOG = os.path.join(ROOT, "local", "llm", "request_log.jsonl")
_DISC = re.compile(r"規律=(全文|3行)")
_SESS = re.compile(r"session=([0-9a-f-]{8,})")


def median(xs):
    xs = sorted(xs)
    if not xs:
        return 0
    n = len(xs)
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) // 2


def load_requests(since_jst):
    """[(dt_utc, sid8, dept, '全文'|'3行')] を古い順で返す。★書かれている物だけを読む。"""
    out = []
    if not os.path.exists(REQ_LOG):
        return out
    for line in io.open(REQ_LOG, encoding="utf-8", errors="replace"):
        if "規律=" not in line:
            continue
        try:
            r = json.loads(line)
        except ValueError:
            continue                       # 壊れた行は数えない
        ev = str(r.get("evidence") or "")
        md, ms = _DISC.search(ev), _SESS.search(ev)
        if not md or not ms:
            continue                       # sessionが取れない行は突き合わせできない=捨てる
        try:
            dt = datetime.fromisoformat(str(r.get("ts"))).replace(tzinfo=JST)
        except ValueError:
            continue
        if dt < since_jst:
            continue
        out.append((dt.astimezone(UTC), ms.group(1)[:8], r.get("dept") or "?", md.group(1)))
    out.sort(key=lambda x: x[0])
    return out


def attach_writes(reqs, msgs):
    """各便に「その便の**最初の**assistant応答の書込」を貼る。

    ★最初の1本だけを見る理由= 前置きの作り直しは**便の頭**で起きる。
      同じ便の2本目以降は前置きが既にキャッシュへ載っているので、混ぜると薄まる。
    """
    per = collections.defaultdict(list)
    for m in msgs:
        per[m["sid"]].append(m)
    for v in per.values():
        v.sort(key=lambda m: m["dt"])
    bysid = collections.defaultdict(list)
    for i, (dt, sid, dept, disc) in enumerate(reqs):
        bysid[sid].append((dt, i, disc))
    out = {}
    for sid, items in bysid.items():
        items.sort()
        for k, (dt, i, _disc) in enumerate(items):
            nxt = items[k + 1][0] if k + 1 < len(items) else None
            got = [m for m in per.get(sid, [])
                   if m["dt"] >= dt and (nxt is None or m["dt"] < nxt)]
            if got:
                out[i] = got[0]["cc"]      # ★その便の最初の応答=前置きが作り直された所
    return out


def split(reqs, writes):
    """(前置きが前便から変わった便の書込, 変わらなかった便の書込)。"""
    prev = {}
    swing, same = [], []
    for i, (_dt, sid, _dept, disc) in enumerate(reqs):
        p = prev.get(sid)
        prev[sid] = disc
        if i not in writes or p is None:
            continue                       # 突き合わない便・その部屋の初便は数えない
        (swing if p != disc else same).append(writes[i])
    return swing, same


def show(label, swing, same):
    if not swing or not same:
        print("  %s= 片側が0本=比べられない(swing %d / same %d)" % (label, len(swing), len(same)))
        return None
    ms, mm = median(swing), median(same)
    ratio = (ms / mm) if mm else 0
    print("  %-10s swing %4d本 中央値 %8d / same %4d本 中央値 %8d → **%.2f倍**"
          % (label, len(swing), ms, len(same), mm, ratio))
    return ratio


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=72.0)
    ap.add_argument("--dept", default=None, help="部門で絞る(カンマ区切り)")
    a = ap.parse_args()

    since_jst = datetime.now(JST) - timedelta(hours=a.hours)
    reqs = load_requests(since_jst)
    want = {s.strip() for s in a.dept.split(",")} if a.dept else None
    if want:
        reqs = [r for r in reqs if r[2] in want]
    print("== 前置きの振れ と キャッシュ書込 / 直近%.0f時間%s ==" % (
        a.hours, (" / 部門= " + ",".join(sorted(want))) if want else ""))
    print("読んだ物= request_log.jsonl の『規律=全文/3行』 と 生の transcript の usage(実測)")
    if not reqs:
        print("この窓に『規律=』を持つ便が無い= 測れない(そう書く)")
        return
    kinds = collections.Counter(r[3] for r in reqs)
    print("  便 %d本(全文 %d / 3行 %d)" % (len(reqs), kinds["全文"], kinds["3行"]))

    msgs = fb.scan_detail(since_jst.astimezone(UTC))
    writes = attach_writes(reqs, msgs)
    print("  うち書込を突き合わせられた便= %d本" % len(writes))
    if len(writes) < 20:
        print("★標本が20本未満= 判定しない(数えたことにしない)")
        return

    print()
    swing, same = split(reqs, writes)
    real = show("実測", swing, same)

    # ★★must-fail= ラベルだけ混ぜる。関係が無ければ実測と同じ値が出るはずだ。
    print()
    print("== ★対照(ラベルだけ混ぜた偽物・C-053) ==")
    rnd = random.Random(20260823)
    shuffled = [(r[0], r[1], r[2], d) for r, d in
                zip(reqs, rnd.sample([r[3] for r in reqs], len(reqs)))]
    fs, fm = split(shuffled, writes)
    fake = show("混ぜ物", fs, fm)

    print()
    if real is None or fake is None:
        print("★片側が0本= 結論を出さない。")
    elif abs(real - 1.0) < 0.15:
        print("★**差が出ていない**(実測 %.2f倍)= 前置きの振れは書込の主因ではない。"
              "HQの見立ては、この窓のこの数え方では**支持されない**。" % real)
    elif abs(real - 1.0) <= abs(fake - 1.0):
        print("★実測 %.2f倍 に対し**混ぜ物でも %.2f倍**= この道具は何も見ていない。"
              "数え方を直すまで結論に使うな。" % (real, fake))
    else:
        print("★実測 **%.2f倍**・混ぜ物 %.2f倍= 前置きが前便と変わった便は書込が実際に重い。"
              "**HQの見立ての向きに合う。**" % (real, fake))
    print("  ★断り= これは相関で、原因の証明ではない。全文になる場面(圧縮直後・新セッション)は"
          "そもそも書込が多い=**交絡している**。切り分けは『変更なしの3行が続く区間だけ』で測り直す。")


if __name__ == "__main__":
    main()
