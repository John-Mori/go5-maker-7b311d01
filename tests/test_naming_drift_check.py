# -*- coding: utf-8 -*-
"""持続ドリフト検査の must-fail テスト(イージス研究室 / 2026-08-31)。

★C-053= 壊した側は**動く別実装**であること。
  「しきい値を変な値にしたら落ちた」は、判定が居ることの証明にならない。
  だからここでは、**それ自体としては正しく動く2つの素朴な実装**を並べて、
  本物だけが正解を出すことを見る:
    ① 件数だけ版 (count_only)      … 実際に動く。だが一過性の言い間違いまで拾う。
    ② 増分だけ版 (increment_only)  … 実際に動く。だが**居座っている**ドリフトを見逃す。
  この2本が外す場面で本物が当たる= しきい値3つ(件数/日数/人格数)が仕事をしている証拠。

    python tests/test_naming_drift_check.py
"""
import io
import json
import os
import sys
import tempfile

PJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PJ, "scripts", "llm"))
import naming_drift_check as ndc          # noqa: E402


def row(day, target, found, expected, persona, reason="override_allowed"):
    return {"ts": "%sT12:00:00" % day, "event": "naming", "persona": persona,
            "target": target, "found": found, "expected": expected, "reason": reason}


def ledger(rows):
    """台帳を1本その場で作る。★本物の `local/llm/naming_audit.jsonl` は読まない。"""
    fd, path = tempfile.mkstemp(suffix=".jsonl")
    with io.open(fd, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return path


# ── 素材: 本物の台帳から写した3つの形 ────────────────────────────────
# ① 居座り= 6日・7人格に散った「一ノ瀬」(トトリの実測と同じ形)
PERSISTENT = [row("2026-08-%02d" % d, "一ノ瀬怜", "一ノ瀬", ["怜"], "人格%d" % p)
              for d, p in zip(range(18, 25), range(1, 8))] + \
             [row("2026-08-24", "一ノ瀬怜", "一ノ瀬", ["怜"], "人格1")]
# ② 一過性= **同じ日・同じ人格**で9件。件数は多いが、その日で終わっている言い間違い
BURST = [row("2026-08-20", "オタコン", "オタ", ["オタコン"], "人格X") for _ in range(9)]
# ③ 鳴らせない= 実際の形が台帳に残らない敬称ドリフト(「モドリッチさん」)
UNREADABLE = [row("2026-08-%02d" % d, "ルカ・モドリッチ", "モドリッチ", ["モドリッチ"],
                  "人格%d" % d) for d in range(18, 26)]


# ── 動く別実装(壊れてはいない・視点が足りないだけ) ───────────────────
def count_only(rows, end, min_count=5):
    """件数だけ版。実際に動く= 閾値以上の (target, found) を返す。"""
    agg = {}
    for r in rows:
        agg[(r["target"], r["found"])] = agg.get((r["target"], r["found"]), 0) + 1
    return {k for k, v in agg.items() if v >= min_count}


def increment_only(rows, end, prev_end):
    """増分だけ版。実際に動く= 前回以降に**増えた**組だけ返す。"""
    before = {(r["target"], r["found"]) for r in rows if r["ts"][:10] <= prev_end}
    after = {(r["target"], r["found"]) for r in rows if prev_end < r["ts"][:10] <= end}
    return after - before


def pairs(drifts):
    return {(d["target"], d["found"]) for d in drifts}


def main():
    ok = []
    END = "2026-08-25"
    rows = ndc.load_rows(ledger(PERSISTENT + BURST + UNREADABLE))
    assert len(rows) == len(PERSISTENT + BURST + UNREADABLE), "台帳を読み落とした"

    got = pairs(ndc.scan(rows, end=END))
    ICHINOSE, OTA, MODRIC = (("一ノ瀬怜", "一ノ瀬"), ("オタコン", "オタ"),
                             ("ルカ・モドリッチ", "モドリッチ"))

    # 1) 居座りを拾う
    assert ICHINOSE in got, "持続ドリフトを拾えていない: %s" % (got,)
    ok.append("居座り(6日7人格)を拾う")

    # 2) ★must-fail: 件数だけ版は**一過性の9件**を拾ってしまう。本物は拾わない。
    assert OTA in count_only(rows, END), "前提が崩れた(件数だけ版が拾わない)"
    assert OTA not in got, "一過性の言い間違いを持続ドリフトとして鳴らしている"
    ok.append("件数だけ版が誤って拾う一過性を、本物は捨てる")

    # 3) ★must-fail: 増分だけ版は**8/24までに出ていた**居座りを「増分なし」として見逃す。
    assert ICHINOSE not in increment_only(rows, END, "2026-08-24"), \
        "前提が崩れた(増分だけ版が見逃さない)"
    ok.append("増分だけ版が見逃す居座りを、本物は鳴らし続ける")

    # 4) 直す先が読めない組は鳴らさない・ただし数は見せる
    assert MODRIC not in got, "直す先が読めない組を鳴らしている"
    un = ndc.unreadable(rows, end=END)
    assert sum(u["count"] for u in un) == len(UNREADABLE), "鳴らせない分を数え落とした"
    ok.append("鳴らせない%d件を、捨てずに数えて見せる" % len(UNREADABLE))

    # 5) 顔ぶれ版は**件数では動かない**(1件増えるたびに鳴り直さない)
    s1 = ndc.sig(ndc.scan(rows, end=END))
    s2 = ndc.sig(ndc.scan(rows + [row("2026-08-25", "一ノ瀬怜", "一ノ瀬", ["怜"], "人格9")],
                          end=END))
    assert s1 == s2 and s1, "件数が増えただけで顔ぶれ版が変わる=鳴り直す"
    ok.append("件数が増えても顔ぶれ版は動かない")

    # 6) 台帳が数日止まっても、止まる前の窓を見せる(既定の end は「今日」ではない)
    assert ICHINOSE in pairs(ndc.scan(rows)), "台帳の最終日ではなく今日を基準にしている"
    ok.append("台帳が止まっても静かに0件へ倒れない")

    print("\n".join("PASS  " + s for s in ok))
    print("%d/%d PASS" % (len(ok), len(ok)))
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    sys.exit(main())
