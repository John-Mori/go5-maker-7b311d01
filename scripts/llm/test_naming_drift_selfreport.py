# -*- coding: utf-8 -*-
"""呼称ドリフト計器の**自己汚染**を切った所の回帰ガード(2026-09-06 イージス研究室)。

壊れていた実物(local/llm/naming_audit.jsonl・窓 2026-08-24〜09-06):
  持続ドリフトの警報は本文へ「**ルカ・モドリッチ** を「ルカ・モドリッチ」と呼んでいる」と
  **違反の形をそのまま引用して**書く。その便は dispatch で人事部門へ出る=
  投函経路の呼称ゲートC(output_gates.apply_naming_gate_only)を通り、引用のつもりの形が
  **違反として naming_audit.jsonl へ書き戻される**。翌朝それをこの見張りが読む。
  実測= 自分の本文から生まれた判定行 30(ルカ・モドリッチ10 / シャビ・アロンソ10 / 一ノ瀬10)。
  ★ただ水増しするだけではなかった= `シャビ・アロンソ>シャビ・アロンソ` は自分の行のせいで
    「判定できた行5・呼びかけ0」に達し、_all_mention() に**黙らされていた**(件41)。
    汚染を外すと判定行が3へ落ち、fail-open で鳴る側へ戻る(件31)。
    計器の自己汚染は**数字を膨らませる**だけでなく**警報を消す**方向にも効く。

規律(docs/departments/00_common/skills/test-must-fail/SKILL.md):
  - 判定は本物のまま。偽物にするのは台帳ファイル(tmpの jsonl)だけ= 外へ出る手は使わない。
  - 検査対象は毎回ソースから読み直して exec(.pyc の偽PASSを踏まない)。
  - 最後に must-fail= 実装を「動く別の実装」へ変異させ、この検査が落ちるか確かめる。

実行: python scripts/llm/test_naming_drift_selfreport.py
      python scripts/llm/test_naming_drift_selfreport.py --mutate   … 変異だけ回す
"""
import io
import json
import os
import shutil
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
PJ = os.path.dirname(os.path.dirname(HERE))
NDC = os.path.join(HERE, "naming_drift_check.py")
WATCH = os.path.join(PJ, "scripts", "_daemons", "envelope_naming_watch.py")

FAIL = []


def ok(cond, name, detail=""):
    print(("  OK   " if cond else "  FAIL ") + name + (("  " + detail) if detail else ""))
    if not cond:
        FAIL.append(name)


def load(path, name):
    """★ソースから読んで exec= .pyc の偽PASSを踏まない。"""
    src = open(path, encoding="utf-8").read()
    mod = type(sys)(name)
    mod.__file__ = path
    exec(compile(src, path, "exec"), mod.__dict__)
    return mod


def write_audit(tmp, rows, name="naming_audit.jsonl"):
    p = os.path.join(tmp, name)
    with io.open(p, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return p


def row(ts, persona, target, found, excerpt, voc=0, expected=None, reason="override_allowed"):
    return {"ts": ts, "dept": "aegis-gl", "event": "naming", "persona": persona,
            "target": target, "found": found, "expected": expected or ["モドリッチさん"],
            "reason": reason, "source": "dispatch", "msg_id": "", "excerpt": excerpt,
            "voc": voc}


# 本物の警報本文の頭(2026-09-06 の実物 excerpt をそのまま)。
REAL_HEAD = ("【イージス研究室(無人の見張り) → 人事部門】呼称の**持続ドリフト**が 9件 居座っている\n\n"
             "`local/llm/naming_audit.jsonl` の直近14日を読んだ。")
# 人格が実際に誤って呼んだ便(=数えるべき側)。
USE_HEAD = "[オタコン]\nルカ・モドリッチ、そっちの計器の件だが──"
# 他室が**この警報を引用して**返した便(=頭が違う=数える側へ残すのが正しい)。
QUOTE_HEAD = ("[ククール]\nデブライネさんの便"
              "「【イージス研究室(無人の見張り) → 人事部門】呼称の**持続ドリフト**」を読んだ。")


def fixture(tmp):
    """実物と同じ形の小さな台帳。自分の警報3日ぶん+人格の実使用+他室の引用。"""
    rows = []
    for d in ("2026-09-02", "2026-09-04", "2026-09-06"):
        for _ in range(2):          # dispatch は同じ便で2回書く(main と dispatch() の2関門)
            rows.append(row(d + "T04:38:35", "ケヴィン・デブライネ",
                            "ルカ・モドリッチ", "ルカ・モドリッチ", REAL_HEAD, voc=0))
    for i, d in enumerate(("2026-09-01", "2026-09-03", "2026-09-05")):
        rows.append(row(d + "T10:00:0%d" % i, "オタコン",
                        "ルカ・モドリッチ", "ルカ・モドリッチ", USE_HEAD, voc=1))
    rows.append(row("2026-09-03T11:00:00", "ククール",
                    "ルカ・モドリッチ", "ルカ・モドリッチ", QUOTE_HEAD, voc=0))
    # 数えない行(既存の挙動が変わっていないことの確認用)
    rows.append({"ts": "2026-09-03T12:00:00", "event": "naming_fix", "persona": "オタコン",
                 "target": "ルカ・モドリッチ", "found": "ルカ", "excerpt": USE_HEAD})
    return write_audit(tmp, rows)


# ------------------------------------------------------------------ T1 判定の側
def t1(ndc):
    print("[1] is_self_report= 見張り自身の本文だけを見分ける")
    ok(ndc.is_self_report({"excerpt": REAL_HEAD}), "1a 実物の警報本文= 自己汚染と判る")
    ok(ndc.is_self_report({"excerpt": "\n  " + REAL_HEAD}),
       "1b 頭に空白/改行が付いても判る(lstrip)")
    ok(not ndc.is_self_report({"excerpt": USE_HEAD}), "1c 人格の実使用= 自己汚染ではない")
    ok(not ndc.is_self_report({"excerpt": QUOTE_HEAD}),
       "1d 他室が**引用**した便= 頭が違う=数える側に残す(C-035=広げない)")
    ok(not ndc.is_self_report({"excerpt": ""}), "1e excerpt が空= 数える側へ倒す(fail-open)")
    ok(not ndc.is_self_report({}), "1f excerpt キーが無い行= 数える側へ倒す(fail-open)")


# ------------------------------------------- T2 見張りの本文と除外が**離れない**
def t2(ndc):
    print("[2] ★輪を閉じる= 見張りが今日出す本文が、今日の除外に引っかかるか")
    w = load(WATCH, "watch_real")
    drifts = [{"target": "ルカ・モドリッチ", "found": "ルカ・モドリッチ",
               "expected": ["モドリッチさん"], "count": 9, "days": 4,
               "personas": ["オタコン", "ククール"], "first": "2026-09-01T00:00:00",
               "last": "2026-09-06T00:00:00", "reasons": {"override_allowed": 9}}]
    body = w.build_drift_body(ndc, drifts, [])
    ok(ndc.is_self_report({"excerpt": body[:200]}),
       "2a build_drift_body() の実本文が is_self_report で外れる", body[:44].replace("\n", "⏎"))
    ok("ndc.SELF_REPORT_HEAD +" in open(WATCH, encoding="utf-8").read(),
       "2b 見張りは見出しを定数から組む(同じ文字列を2箇所に置かない)")
    ok("【イージス研究室(無人の見張り) → 人事部門】呼称の**持続ドリフト**"
       not in open(WATCH, encoding="utf-8").read(),
       "2c 見出しの直書きが残っていない")


# ------------------------------------------------------------ T3 台帳を通した数
def t3(ndc, tmp):
    print("[3] 台帳を通した数= 自分の6行が消え、他は1件も減らない")
    p = fixture(tmp)
    all_rows = ndc.load_rows(p, keep_self=True)
    kept = ndc.load_rows(p)
    # ★2026-09-08 10→7= load_rows() が重複を畳むようになった(DEDUPE_KEY)。この治具の
    #   自分の警報6行は「同じ日・同じ ts・同じ組」を2本ずつ書いた形= 3本へ畳まれる。
    #   ここは**畳みが効いていることの目盛り**を兼ねる(7に戻らなくなったら畳みが外れた)。
    ok(len(all_rows) == 7, "3a keep_self=True で判定行7(重複を畳んだ後・naming_fix は元から除外)",
       "実測%d" % len(all_rows))
    ok(len(kept) == 4, "3b 既定で4行(自分の6行だけ落ちる)", "実測%d" % len(kept))
    ok(all(not ndc.is_self_report(r) for r in kept), "3c 残った行に自己汚染が1つも無い")
    ok(sum(1 for r in kept if r["persona"] == "オタコン") == 3, "3d 人格の実使用3行は全部残る")
    ok(sum(1 for r in kept if r["persona"] == "ククール") == 1, "3e 引用便の1行も残る")
    c = {(d["target"], d["found"]): d for d in ndc.counts(kept, end="2026-09-06")}
    k = ("ルカ・モドリッチ", "ルカ・モドリッチ")
    ok(c[k]["count"] == 4, "3f 件数 10→4", "実測%d" % c[k]["count"])
    ok(c[k]["days"] == 3, "3g 日数 6→3(自分だけが出した日 09-02/04/06 が消える)",
       "実測%d" % c[k]["days"])
    ok(c[k]["personas"] == ["オタコン", "ククール"],
       "3h 人格から『ケヴィン・デブライネ』(=見張り自身)が消える", str(c[k]["personas"]))
    sr = ndc.self_reports(p, end="2026-09-06")
    ok(sum(s["count"] for s in sr) == 3,
       "3i 外した分を self_reports() が3件で見せる(6行→重複を畳んで3)", str(sr))


# --------------------------------------------------- T4 黙って消さない(表示側)
def t4(ndc, tmp):
    print("[4] 除外は**画面に出す**= 静かに減らさない")
    src = open(NDC, encoding="utf-8").read()
    ok("外した %d件" in src, "4a main() に『外した N件』の行が在る")
    ok("self_reports(window=ns.days)" in src, "4b 通常表示で self_reports を必ず呼ぶ")
    ok("self_reports(window=ns.days, since=ns.since)" in src,
       "4c --since(是正後モード)でも呼ぶ")


# --------------------------------------------------------- T5 本番台帳での実測
def t5(ndc):
    print("[5] 本番台帳(local/llm/naming_audit.jsonl)での実測= 数を口で言わない")
    if not os.path.exists(ndc.AUDIT):
        ok(True, "5a 台帳が無い環境= 飛ばす")
        return
    allr = ndc.load_rows(keep_self=True)
    kept = ndc.load_rows()
    n = len(allr) - len(kept)
    ok(n > 0, "5a 本番台帳にも自己汚染が在る(=この修理は空振りではない)",
       "判定行 %d→%d(外した %d)" % (len(allr), len(kept), n))
    sr = ndc.self_reports()
    print("      窓14日の内訳= " +
          "、".join("%s>%s×%d" % (s["target"], s["found"], s["count"]) for s in sr))


# ------------------------------------------------------------------- MUST-FAIL
def must_fail(tmp):
    print("MUST-FAIL 実装を『動く別の実装』へ変異させて、この検査が落ちるか")
    src = open(NDC, encoding="utf-8").read()
    wsrc = open(WATCH, encoding="utf-8").read()
    red = 0
    total = 0

    def mutant(path, name, old, new):
        p = os.path.join(tmp, name + ".py")
        s = open(path, encoding="utf-8").read()
        if old not in s:
            return None
        open(p, "w", encoding="utf-8").write(s.replace(old, new, 1))
        return load(p, name)

    # 変異①= 除外そのものを外す(2026-08-31〜09-06 の実装。動きはする)。
    total += 1
    # ★2026-09-08 変異点の字下げが変わった(load_rows が _read() へ分かれた)。
    m1 = mutant(NDC, "mut_no_exclude",
                "        if not keep_self and is_self_report(r):\n"
                "            continue\n", "")
    if m1 is None:
        ok(False, "変異①の変異点が見つからない(検査が古い)")
    else:
        p = fixture(tmp)
        got = len(m1.load_rows(p))
        ok(got == 7, "変異①(除外を外す)= [3]の数え方が落ちる(4→7)", "実測%d" % got)
        red += 1 if got == 7 else 0

    # 変異②= 頭一致ではなく**どこかに在れば**外す(広げた実装。動きはする)。
    total += 1
    m2 = mutant(NDC, "mut_contains",
                'return str(r.get("excerpt") or "").lstrip().startswith(SELF_REPORT_HEAD)',
                'return SELF_REPORT_HEAD in str(r.get("excerpt") or "")')
    if m2 is None:
        ok(False, "変異②の変異点が見つからない(検査が古い)")
    else:
        bad = m2.is_self_report({"excerpt": QUOTE_HEAD})
        ok(bad, "変異②(部分一致へ広げる)= [1d]引用便まで消えて落ちる")
        red += 1 if bad else 0

    # 変異③= 見張りが見出しを直書きへ戻す(文言が1文字ずれた形。動きはする)。
    total += 1
    m3 = mutant(WATCH, "mut_hardcoded_head",
                "lines = [ndc.SELF_REPORT_HEAD + ",
                "lines = ['【イージス研究室(無人の見張り) → 人事部門】呼称ドリフト' + ")
    if m3 is None:
        ok(False, "変異③の変異点が見つからない(検査が古い)")
    else:
        ndc = load(NDC, "ndc_for_mut3")
        body = m3.build_drift_body(ndc, [{"target": "ルカ・モドリッチ", "found": "ルカ・モドリッチ",
                                          "expected": ["モドリッチさん"], "count": 9, "days": 4,
                                          "personas": ["オタコン"], "first": "2026-09-01T00:00:00",
                                          "last": "2026-09-06T00:00:00", "reasons": {}}], [])
        leaked = not ndc.is_self_report({"excerpt": body[:200]})
        ok(leaked, "変異③(見出しを直書きへ戻す)= [2a]輪が開いて落ちる",
           body[:40].replace("\n", "⏎"))
        red += 1 if leaked else 0

    print("  変異 %d件中%d件が狙いどおり赤" % (total, red))
    if red != total:
        FAIL.append("must-fail(変異が赤にならない)")
    _ = (src, wsrc)


if __name__ == "__main__":
    only_mut = "--mutate" in sys.argv
    tmp = tempfile.mkdtemp(prefix="ndc_self_")
    try:
        ndc = load(NDC, "ndc_real")
        if not only_mut:
            t1(ndc)
            t2(ndc)
            t3(ndc, tmp)
            t4(ndc, tmp)
            t5(ndc)
        must_fail(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n結果: %s (失敗 %d件)" % ("PASS" if not FAIL else "FAIL", len(FAIL)))
    for f in FAIL:
        print("  - " + f)
    sys.exit(1 if FAIL else 0)
