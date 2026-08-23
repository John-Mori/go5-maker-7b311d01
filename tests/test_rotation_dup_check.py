# -*- coding: utf-8 -*-
"""世代交代の二重発火ガードの検査(2026-08-24 イージス研究室)。

材料は**実測した本物の行**(`local/llm/request_log.jsonl` から写した2件の事故)。

  ① 2026-07-30 改修部門α= 交代 → 429で新セッション作成が失敗 → 次の便が同じ判定で再挑戦。
     ★これを二重発火として数えてはいけない(数えると、転んだ交代を二度と撃てなくなる)。
  ② 2026-08-22 研究室HQ= 手動交代が同じ old / 同じ gen で10分後に再出現。間に失敗の記録なし。
     ★これは本物(交代が対応表に乗っていない=ORG-46/47の型)。

★must-fail(C-053)= 壊した側は**動く別の実装**へ差し替える。ここでは「品質管理部門が使った
  素の groupby(同一evidenceを全部二重発火と数える)」を実装として置き、①まで数えて赤くなる
  ことを実行で見せる= この検査が①と②を割れていることの証明。

実行= python tests/test_rotation_dup_check.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts", "llm"))

import rotation_dup_check as rd  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    print(("  PASS  " if cond else "  FAIL  ") + name + (("  << " + detail) if not cond else ""))


def mustfail(name, fn, expect):
    got = fn()
    check("must-fail " + name, got == expect, "got=%r want=%r" % (got, expect))


def row(ts, dept, state, ev):
    return {"ts": ts, "dept": dept, "state": state, "evidence": ev}


# ---- ① 429で転んだ交代の再挑戦(2026-07-30 改修部門α・実測を写したもの) ----
_EV_A = ("事前交代 理由=圧縮が7回積み重なった かつ 文脈176,548が120,000以上=定期リフレッシュ(K=5)"
         " tokens=176548 turns=15 compacts=7 old=8ce417dd-6398-4ff1-838c-ca724301e221")
CASE_RETRY = [
    row("2026-07-30T02:14:18", "system-engineer", "rotated", _EV_A),
    row("2026-07-30T02:14:20", "system-engineer", "running", "new session gen=16"),
    row("2026-07-30T02:14:22", "system-engineer", "failed",
        "new session失敗 rc=1 sid='496fce4e' pre_rotating=True out='…api_error_status\":429…'"),
    row("2026-07-30T02:19:26", "system-engineer", "rotated", _EV_A),
]

# ---- ② 交代が対応表に乗らず同じ引き金が再び鳴った(2026-08-22 研究室HQ・実測を写したもの) ----
_EV_B = "手動交代 reason=cli old=c27eec97-ac7c-432e-9fe3-aadeed941265 gen=16"
CASE_DUP = [
    row("2026-08-22T16:34:47", "hq", "rotated", _EV_B),
    row("2026-08-22T16:41:29", "hq", "completed",
        "session=c27eec97-ac7c-432e-9fe3-aadeed941265 gen=16 ctx=167937 turns=12 compacts=7"),
    row("2026-08-22T16:44:37", "hq", "rotated", _EV_B),
]

print("\n--- ① 転んだ交代の再挑戦は数えない ---")
_n, _h = rd.scan(rows=CASE_RETRY, days=None)
check("起点行を2本とも見ている", _n == 2, str(_n))
check("★429で転んだ後の再挑戦は二重発火ではない", _h == [], repr(_h))

print("\n--- ② 対応表に乗らなかった交代の再出現は本物 ---")
_n2, _h2 = rd.scan(rows=CASE_DUP, days=None)
check("本物を1件つかむ", len(_h2) == 1, repr(_h2))
check("つかんだ行の部屋と時刻が実物と一致",
      _h2 and _h2[0]["dept"] == "hq" and _h2[0]["first"] == "2026-08-22T16:34:47"
      and _h2[0]["dup"] == "2026-08-22T16:44:37", repr(_h2))

print("\n--- ③ 混ぜて渡しても①だけが落ちる ---")
_n3, _h3 = rd.scan(rows=CASE_RETRY + CASE_DUP, days=None)
check("起点行は4本", _n3 == 4, str(_n3))
check("本物だけ1件", len(_h3) == 1 and _h3[0]["dept"] == "hq", repr(_h3))

print("\n--- ④ 部屋をまたいだ失敗を言い訳に使わない ---")
_cross = [
    row("2026-08-22T16:34:47", "hq", "rotated", _EV_B),
    row("2026-08-22T16:35:00", "system-engineer", "failed",
        "new session失敗 rc=1 pre_rotating=True"),   # ★別の部屋の失敗
    row("2026-08-22T16:44:37", "hq", "rotated", _EV_B),
]
check("他室の失敗では免除しない", len(rd.scan(rows=_cross, days=None)[1]) == 1)

print("\n--- ⑤ 今の本番の台帳で走らせる(直近7日) ---")
_n5, _h5 = rd.scan(days=7)
check("本番の台帳を読めている(起点行が1本以上ある)", _n5 >= 1, str(_n5))
print("     直近7日= 起点行%d件 / 本物の二重発火%d件" % (_n5, len(_h5)))


# ================================================================ must-fail
def _mf_naive_groupby():
    """壊した側= **動く別の実装**「同一evidenceを全部二重発火と数える」(監査で使われた素の方法)。
    ①(429の再挑戦)まで数えるので、直しの向きを誤らせる。"""
    keep = rd.scan

    def naive(rows=None, days=7, since=None):
        rows = rows or []
        seen, hits = {}, []
        for r in rows:
            if not rd.is_start(r):
                continue
            k = (r.get("dept"), str(r.get("evidence") or ""))
            if k in seen:
                hits.append({"dept": r.get("dept"), "first": seen[k],
                             "dup": str(r.get("ts")), "evidence": k[1]})
            seen[k] = str(r.get("ts"))
        return len(seen), hits
    try:
        rd.scan = naive
        return len(rd.scan(rows=CASE_RETRY, days=None)[1])
    finally:
        rd.scan = keep


def _mf_no_start_filter():
    """壊した側= 起点行の判定を「state==rotated なら何でも」にした実装。
    交代の途中の記録(引き継ぎ生成OK 等)まで起点として数える。"""
    extra = CASE_DUP + [row("2026-08-22T16:50:00", "hq", "rotated", "引き継ぎ生成OK path=…")]
    right = rd.scan(rows=extra, days=None)[0]         # 本物= 起点は2本
    keep = rd.is_start
    try:
        rd.is_start = lambda r: r.get("state") == "rotated"
        return rd.scan(rows=extra, days=None)[0], right
    finally:
        rd.is_start = keep


print("\n--- must-fail(動く別の実装へ差し替えて、赤くなることを実行で確かめる) ---")
mustfail("素のgroupbyだと429の再挑戦まで二重発火に数える", _mf_naive_groupby, 1)
mustfail("起点行を絞らないと交代の途中行まで起点に数える(壊した側3本/本物2本)",
         _mf_no_start_filter, (3, 2))

ng = [n for n, ok in RESULTS if not ok]
print("\n===== %d件中 %d件PASS =====" % (len(RESULTS), len(RESULTS) - len(ng)))
if ng:
    print("FAIL — %d件: %s" % (len(ng), ng))
    sys.exit(1)
print("ALL PASS")
