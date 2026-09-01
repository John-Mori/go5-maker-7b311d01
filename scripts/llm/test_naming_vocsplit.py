#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""呼称ゲートD: 呼びかけ/地の文の切り分け(voc)の回帰テスト。

実行:            python scripts/llm/test_naming_vocsplit.py
変異(must-fail): python scripts/llm/test_naming_vocsplit.py --mutate

★2026-09-02 新設。引き金= 人事部門ククールの検算(便6/6 msg DISPATCH-aegis-gl-1788299260538)
  「pinは効いているのに件数が動かない。計器が use/mention を数えているのでは」。
  裏取りの結果、08-31の再ピン後の5ペア34件は **呼びかけ位置0 / 地の文34**。
  そこで計器側に2つ入れた:
    ① `naming_gate._attach_hits` が台帳へ `voc`(咎めた出現のうち呼びかけ位置は何件か)を書く。
    ② `naming_drift_check._all_mention` が「地の文の言及だけの組」を**鳴らさない**。
  ★危ないのは②が静かに効きすぎることだ= 本物の誤呼称まで黙ると、計器は
    「0件=健康」を出しながら壊れる。ここで釘付けにするのは主にその境界:
      - 旧ゲートが書いた行(voc 無し)は **判定できない=鳴らす側へ倒す**(fail-open)
      - 呼びかけが1件でもあれば鳴る
      - 黙らせた分は捨てず `mentions()` に残る
"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import naming_gate as ng          # noqa: E402
import naming_drift_check as dc   # noqa: E402

results = []

RULES = {
    "honorific_required_targets": {
        "シャビ・アロンソ": {"bare_forms": ["アロンソ", "シャビ", "シャビ・アロンソ"],
                             "allowed": ["アロンソさん", "アロンソコーチ"]},
    },
}
WHO = "ケヴィン・デブライネ"


def check(name, cond):
    results.append((name, bool(cond)))
    print(("  OK  " if cond else "  NG  ") + name)


def voc_of(text):
    """ゲートが台帳へ書く `voc` の合計(判定行が無ければ None)。"""
    vs = ng.naming_verdicts(WHO, "aegis-gl", text, RULES)
    if not vs:
        return None
    return sum(int(v.get("voc") or 0) for v in vs)


def row(ts, voc=None, target="シャビ・アロンソ", found="アロンソ", persona="A"):
    r = {"ts": ts, "target": target, "found": found, "persona": persona,
         "reason": "bare", "expected": ["アロンソさん"]}
    if voc is not None:
        r["voc"] = voc
    return r


def rows(n, voc=None, days=5):
    """しきい値(件5 日3 人2)を確実に越える行を n 本。"""
    return [row("2026-09-%02dT10:0%d:00" % (1 + (i % days), i % 10),
                voc=voc, persona="人%d" % (i % 3))
            for i in range(n)]


def main():
    print("=== 呼称ゲートD: 呼びかけ/地の文の切り分け ===")

    print("\n[1] ゲートが voc を書く")
    check("呼びかけ: 行頭の「アロンソ、」は voc=1",
          voc_of("アロンソ、この件は任せる。") == 1)
    check("地の文: 「アロンソとオタコンで詰めた」は voc=0",
          voc_of("この件はアロンソとオタコンで詰めた。") == 0)
    check("台帳に voc の欄が必ず載る(0でも欠かさない)",
          all("voc" in v for v in
              ng.naming_verdicts(WHO, "aegis-gl", "アロンソに渡した。", RULES)))

    print("\n[2] 地の文だけの組は鳴らさない")
    ds = dc.scan(rows(9, voc=0), window=14)
    check("voc=0 の新行9本 → 持続ドリフトに出さない", not ds)
    mt = dc.mentions(rows(9, voc=0), window=14)
    check("黙らせた分は mentions() に残る(捨てない)",
          len(mt) == 1 and mt[0]["count"] == 9 and mt[0]["judgeable"] == 9)

    print("\n[3] 呼びかけが混じれば鳴る")
    # ★比率で黙らせない= 19本が地の文でも**呼びかけ1本**で鳴らす。
    #   「ほとんど地の文だから」で落とすと、本物の誤呼称が多数の言及に埋もれる。
    mix = rows(19, voc=0) + rows(1, voc=1)
    check("19本が地の文でも1本でも呼びかけがあれば鳴る",
          len(dc.scan(mix, window=14)) == 1)

    print("\n[4] 旧ゲートの行は判定できない= 鳴らす側へ倒す(fail-open)")
    old = rows(9, voc=None)
    check("voc を持たない行だけの組は今までどおり鳴る",
          len(dc.scan(old, window=14)) == 1)
    check("voc 無しは voc=0 として数えない(judgeable=0)",
          dc.counts(old, window=14)[0]["judgeable"] == 0)
    check("旧行は mentions() にも入れない(黙らせた扱いにしない)",
          not dc.mentions(old, window=14))

    print("\n[5] 判定できた行が少なすぎる時も鳴らす")
    few = rows(4, voc=0) + rows(5, voc=None)
    check("判定行4本(<件5)では黙らせない", len(dc.scan(few, window=14)) == 1)

    print("\n[6] 鳴らせない(直す先が読めない)組との住み分け")
    unread = [dict(r, found="アロンソさん", expected=["アロンソさん"])
              for r in rows(9, voc=0)]
    check("unreadable な組は mentions() に二重計上しない",
          not dc.mentions(unread, window=14) and len(dc.unreadable(unread, window=14)) == 1)

    ng_bad = sum(1 for _, c in results if not c)
    print("\n%d件中 %d件OK / %d件NG" % (len(results), len(results) - ng_bad, ng_bad))
    return 0 if ng_bad == 0 else 1


# --- must-fail 変異(C-053: 壊れた実装ではなく「もっともらしく動く別実装」を入れる) ---

def _mut_voc_only():
    """`judgeable` を見ずに voc==0 だけで黙らせる。
    ★動きはする(新しい行だけの台帳なら同じ結果)。だが**旧ゲートの行を
      「呼びかけ0」と読む**= 台帳が古いほど静かに全部黙る。"""
    dc._all_mention = lambda a, min_count=dc.MIN_COUNT: a.get("voc", 0) == 0


def _mut_ratio():
    """件数に対する割合で黙らせる(voc が全体の1割未満なら地の文扱い)。
    ★これも動く。だが**呼びかけが混じっても黙る**= 本物を1件取りこぼす。"""
    dc._all_mention = (lambda a, min_count=dc.MIN_COUNT:
                       a.get("judgeable", 0) >= min_count
                       and a.get("voc", 0) * 10 < a.get("judgeable", 0))


def _mut_gate_all():
    """ゲート側: 咎めた出現を**全部**呼びかけとして数える(voc=hits)。
    ★動く。だが地の文しか無い便も voc>0 になり、②が永久に効かない。"""
    orig = ng._is_vocative
    ng._is_vocative = lambda s, i, end: True
    return orig


MUTANTS = (
    ("voc==0 だけで黙らせる(judgeable を見ない)", _mut_voc_only,
     "voc を持たない行だけの組は今までどおり鳴る"),
    ("割合で黙らせる(呼びかけ1割未満)", _mut_ratio,
     "19本が地の文でも1本でも呼びかけがあれば鳴る"),
    ("ゲート: 全出現を呼びかけと数える", _mut_gate_all,
     "地の文: 「アロンソとオタコンで詰めた」は voc=0"),
)


def mutate():
    bad = 0
    saved_dc = dc._all_mention
    saved_ng = ng._is_vocative
    for name, fn, want_red in MUTANTS:
        del results[:]
        fn()
        try:
            print("\n=== %s ===" % name)
            try:
                main()
            except Exception as e:
                print("  (検査が例外で止まった: %s)" % e)
        finally:
            dc._all_mention = saved_dc
            ng._is_vocative = saved_ng
        red = [n for n, c in results if not c]
        hit = want_red in red
        print("  → 狙った1件が赤か: %s  (赤=%d件)" % ("OK" if hit else "NG", len(red)))
        if not hit:
            bad += 1
    print("\n変異 %d件中 %d件が狙いどおり赤" % (len(MUTANTS), len(MUTANTS) - bad))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(mutate() if "--mutate" in sys.argv else main())
