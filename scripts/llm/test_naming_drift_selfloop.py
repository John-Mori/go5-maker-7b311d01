# -*- coding: utf-8 -*-
"""呼称ドリフトの件数を膨らませていた**2つの水増し**の回帰ガード(2026-09-08 イージス研究室)。

発注= 人事部門ククール msg 1546607734349111418(【人事部門 → イージス研究室】呼称ドリフト便、
HR側は検証済み)。発注の見立ては「reason=forbidden の68%は source=dispatch=見張りの自己参照。
**集計から source=dispatch を除外**すれば数字は実態へ寄る」。
★当室で台帳を実測した結果、**除外の的が違っていた**= source=dispatch を丸ごと外すと、
  普通の便で人格が実際に裸の姓で呼んだ分まで一緒に消える(実測= dispatch の reason=forbidden
  187行のうち、呼称/ドリフトを論じている便は56行・残り131行は普通の便の地の文)。
  水増しの正体は dispatch という**送り口**ではなく、下の2つだった:

  ① 重複(同じ一箇所を関門が2度書く)
     dispatch は呼称ゲートCを2回通る(main() の同報前に1回・dispatch() の中でもう1回)。
     ゲートが**直す**違反は1回目で消えるが、大半は「警告のみ」で本文を変えない=
     2回目が同じ違反をもう一度見つけて同じ行をもう1本書く。
     ★生成側は 2026-09-06 に塞いである(dispatch.py の `already_gated`)。実測(2026-09-08)=
       09-08の dispatch 判定行 5 / 一意 5 = 重複0 で**塞がっている**。だが**台帳に既に
       書かれた分は消えない**= 窓14日は二重の行を抱えたままだ。実測(窓 08-26〜09-08)=
       判定行 621 / 一意 407 = 214行(34%)が重複。読み手を直さないと2週間ぶん膨れて出る。
     ★1回目と2回目で excerpt が違う(1回目が直した呼びかけが2回目の excerpt に映る。実物=
       「アロンソさん、」→「アロンソコーチ、」)。だから畳む鍵に excerpt を入れてはいけない。

  ② 正しいフル名を書いただけの行
     「この件は**一ノ瀬怜**へ回します。」と書くと found="一ノ瀬" の行が立つ。台帳を読むと
     「一ノ瀬怜 を **一ノ瀬** と呼んでいる」= 本文に裸の姓は1文字も無い。
     ★ゲートの誤判定ではない(allowed は「怜」なのでフル名も許可形ではない)。だが
       **裸の姓で呼んだ**のと**フル名で書いた**のは別の崩れ方で、直し方も違う。混ぜると
       人事部門は「裸の姓がN件」と読んで効かないピンを打つ。
     ★フル名を違反と呼ぶかは**人事部門の裁定**= ここでは決めない。別の棚に置いて
       `full_name_hits()` で必ず件数を見せる(裁定が「違反」なら足し戻すだけ)。

  実測の効き(本番台帳・窓14日・2026-09-08):
    合計件 513 → 340(重複を畳む) → 285(フル名を外す)。
    「一ノ瀬怜>一ノ瀬」は 127件 → 84 → **39件**。組の数は10のまま動かない。

規律(docs/departments/00_common/skills/test-must-fail/SKILL.md):
  - 判定は本物のまま。偽物にするのは台帳ファイル(tmpの jsonl)だけ= 外へ出る手は使わない。
  - 検査対象は毎回ソースから読み直して exec(.pyc の偽PASSを踏まない)。
  - 最後に must-fail= 実装を「動く別の実装」へ変異させ、この検査が落ちるか確かめる。

実行: python scripts/llm/test_naming_drift_selfloop.py
"""
import io
import json
import os
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
NDC = os.path.join(HERE, "naming_drift_check.py")

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


def row(ts, persona, target, found, near, excerpt, expected=None):
    return {"ts": ts, "dept": "aegis-gl", "event": "naming", "persona": persona,
            "target": target, "found": found, "expected": expected or ["怜"],
            "reason": "forbidden", "source": "dispatch", "msg_id": "",
            "near": near, "excerpt": excerpt, "voc": 0}


# 実物の形(2026-09-05 の便から)。裸の姓で呼んだ側=数える。
BARE_NEAR = "この件は一ノ瀬へ回す。手が空いているのは"
# 実物の形。フル名を正しく書いただけ=別の棚へ。
FULL_NEAR = "'この件は一ノ瀬怜へ回します。' → 'この件は怜へ回します。' dept_ref_fix=0"
# 1回目/2回目で excerpt が変わる実物の形(呼びかけだけ直っている)。
EX1 = "[ケヴィン・デブライネ]\nアロンソさん、着手前の一声です。"
EX2 = "[ケヴィン・デブライネ]\nアロンソコーチ、着手前の一声です。"


def fixture(tmp):
    """裸の姓2件(別々の日)+ 同じ一箇所の重複1組 + フル名2件。"""
    rows = [
        # ① 裸の姓・別々の便(数える側)。同じ関門を2回通った形= excerpt だけ違う。
        row("2026-09-02T10:00:00", "オタコン", "一ノ瀬怜", "一ノ瀬", BARE_NEAR, EX1),
        row("2026-09-02T10:00:00", "オタコン", "一ノ瀬怜", "一ノ瀬", BARE_NEAR, EX2),
        row("2026-09-04T10:00:00", "トトリ", "一ノ瀬怜", "一ノ瀬", BARE_NEAR, EX1),
        # ② 同じ本文の**別の箇所**(near が違う)= 畳まない。
        row("2026-09-04T10:00:00", "トトリ", "一ノ瀬怜", "一ノ瀬",
            "追記。一ノ瀬の分は明日でいい", EX1),
        # ③ フル名を書いただけ(別の棚へ)。これも2度書かれている。
        row("2026-09-03T09:00:00", "ククール", "一ノ瀬怜", "一ノ瀬", FULL_NEAR, EX1),
        row("2026-09-03T09:00:00", "ククール", "一ノ瀬怜", "一ノ瀬", FULL_NEAR, EX2),
    ]
    return write_audit(tmp, rows)


# ------------------------------------------------------------------ T1 判定の側
def t1(n):
    print("[1] is_full_name_hit= フル名を書いただけの行を見分ける")
    ok(n.is_full_name_hit({"target": "一ノ瀬怜", "found": "一ノ瀬", "near": FULL_NEAR}),
       "1a 実物『一ノ瀬怜へ回します』= フル名の中に埋まっている")
    ok(not n.is_full_name_hit({"target": "一ノ瀬怜", "found": "一ノ瀬", "near": BARE_NEAR}),
       "1b 裸の姓= フル名ではない(数える側)")
    ok(not n.is_full_name_hit({"target": "一ノ瀬怜", "found": "一ノ瀬",
                               "near": "一ノ瀬怜へ回す。だが一ノ瀬は今日休みだ"}),
       "1c フル名と裸の姓が**同じ現場に混ざる**= 1つでも外に出ていれば数える(fail-open)")
    ok(not n.is_full_name_hit({"target": "一ノ瀬怜", "found": "一ノ瀬"}),
       "1d near が無い行= 判定できない=数える側へ倒す(fail-open)")
    ok(not n.is_full_name_hit({"target": "一ノ瀬怜", "found": "一ノ瀬", "near": ""}),
       "1e near が空= 同じく数える側へ倒す")
    ok(not n.is_full_name_hit({"target": "ルカ・モドリッチ", "found": "ルカ・モドリッチ",
                               "near": "ルカ・モドリッチ、進捗を頼む"}),
       "1f found==target(フル名そのものが禁止形)= 外さない・これは本物の違反")


def t2(n):
    print("[2] dedupe= 同じ一箇所だけを畳む")
    a = {"ts": "T", "source": "dispatch", "dept": "d", "persona": "p",
         "target": "一ノ瀬怜", "found": "一ノ瀬", "near": BARE_NEAR, "excerpt": EX1}
    b = dict(a, excerpt=EX2)
    c = dict(a, near="別の現場で一ノ瀬と書いた")
    e = dict(a, ts="T2")
    ok(len(n.dedupe([a, b])) == 1, "2a excerpt だけ違う2本= 同じ一箇所=1本へ畳む")
    ok(len(n.dedupe([a, c])) == 2, "2b near が違う= 同じ本文の別の箇所=畳まない")
    ok(len(n.dedupe([a, e])) == 2, "2c ts が違う= 別の便=畳まない")
    ok(n.dedupe([a, b])[0]["excerpt"] == EX1, "2d 残るのは先に書かれた方(順序を保つ)")
    ok("excerpt" not in n.DEDUPE_KEY,
       "2e ★畳む鍵に excerpt を入れない(1回目が直した分が2回目の excerpt に映るため)")


# ------------------------------------------------------------ T3 台帳を通した数
def t3(n, tmp):
    print("[3] 台帳を通した数= 重複が畳まれ、フル名が別の棚へ行く")
    p = fixture(tmp)
    raw = n._read(p)
    kept = n.load_rows(p)
    ok(len(raw) == 6, "3a 素の判定行6", "実測%d" % len(raw))
    ok(len(kept) == 3, "3b 既定で3行(重複1・フル名2が落ちる)", "実測%d" % len(kept))
    ok(all(r["near"] != FULL_NEAR for r in kept), "3c 残った行にフル名の行が無い")
    ok(len(n.load_rows(p, keep_full_name=True)) == 4,
       "3d keep_full_name=True なら4行(フル名2→畳んで1が戻る)",
       "実測%d" % len(n.load_rows(p, keep_full_name=True)))
    c = {(d["target"], d["found"]): d for d in n.counts(kept, end="2026-09-04")}
    k = ("一ノ瀬怜", "一ノ瀬")
    ok(c[k]["count"] == 3, "3e 件数 6→3", "実測%d" % c[k]["count"])
    ok(c[k]["days"] == 2, "3f 日数= 09-02/09-04 の2日(フル名だけの 09-03 が消える)",
       "実測%d" % c[k]["days"])
    fn = n.full_name_hits(p, end="2026-09-04")
    ok(sum(f["count"] for f in fn) == 1, "3g 外したフル名を full_name_hits() が見せる", str(fn))
    dp = n.duplicates(p, end="2026-09-04")
    ok(sum(d["count"] for d in dp) == 1, "3h 畳んだ分を duplicates() が見せる", str(dp))


# --------------------------------------------------- T4 黙って消さない(表示側)
def t4():
    print("[4] 除外は**画面に出す**= 静かに減らさない")
    src = open(NDC, encoding="utf-8").read()
    ok("畳んだ %d件" in src, "4a main() に『畳んだ N件』の行が在る")
    ok("フル名を違反と呼ぶかは人事部門の裁定" in src,
       "4b フル名の棚は『裁定は人事部門』と明記して出す(当室が呼称を決めない)")
    ok(src.count("_show_drops(") == 3,
       "4c 通常表示と --since の**両方**で呼ぶ(定義1+呼び出し2)",
       "実測%d" % src.count("_show_drops("))


# --------------------------------------------------------- T5 本番台帳での実測
def t5(n):
    print("[5] 本番台帳での実測= 数を口で言わない")
    if not os.path.exists(n.AUDIT):
        ok(True, "5a 台帳が無い環境= 飛ばす")
        return
    raw = len(n._read())
    kept = len(n.load_rows())
    ok(raw > kept, "5a 本番台帳でも水増しが在る(=この修理は空振りではない)",
       "素 %d → %d" % (raw, kept))
    dp = n.duplicates()
    fn = n.full_name_hits()
    print("      窓14日で畳んだ重複= %d件 / 外したフル名= %d件"
          % (sum(d["count"] for d in dp), sum(f["count"] for f in fn)))
    print("      フル名の内訳= " +
          ("、".join("%s>%s×%d" % (f["target"], f["found"], f["count"]) for f in fn)
           or "なし"))


# ------------------------------------------------------------------- MUST-FAIL
def must_fail(tmp):
    print("MUST-FAIL 実装を『動く別の実装』へ変異させて、この検査が落ちるか")
    red = 0
    total = 0

    def mutant(name, old, new):
        p = os.path.join(tmp, name + ".py")
        s = open(NDC, encoding="utf-8").read()
        if old not in s:
            return None
        open(p, "w", encoding="utf-8").write(s.replace(old, new, 1))
        return load(p, name)

    p = fixture(tmp)

    # 変異①= 畳みを外す(2026-09-06〜09-08 の実装。動きはする)。
    total += 1
    m = mutant("mut_nodedupe", "    return dedupe(out)", "    return out")
    if m is None:
        ok(False, "変異①の変異点が見つからない(検査が古い)")
    else:
        got = len(m.load_rows(p))
        ok(got == 4, "変異①(畳みを外す)= [3b]が落ちる(3→4)", "実測%d" % got)
        red += 1 if got == 4 else 0

    # 変異②= 畳む鍵に excerpt を足す(「厳密なほど安全」に見えるが、1回目と2回目で
    #   excerpt が変わるので**重複が1本も畳まれない**)。動きはする。
    total += 1
    m = mutant("mut_excerptkey",
               'DEDUPE_KEY = ("ts", "source", "dept", "persona", "target", "found", "near")',
               'DEDUPE_KEY = ("ts", "source", "dept", "persona", "target", "found",'
               ' "near", "excerpt")')
    if m is None:
        ok(False, "変異②の変異点が見つからない(検査が古い)")
    else:
        got = len(m.load_rows(p))
        ok(got == 4, "変異②(鍵に excerpt を足す)= [2e/3b]が落ちる(3→4)", "実測%d" % got)
        red += 1 if got == 4 else 0

    # 変異③= 発注どおり **source=dispatch を丸ごと外す**(動きはする・数字は下がる)。
    #   ★これが赤になることが、発注へ「的が違う」と返す根拠だ= 裸の姓で呼んだ行まで消える。
    total += 1
    m = mutant("mut_dropdispatch",
               "        if not keep_full_name and is_full_name_hit(r):\n"
               "            continue\n",
               "        if not keep_full_name and is_full_name_hit(r):\n"
               "            continue\n"
               '        if r.get("source") == "dispatch":\n'
               "            continue\n")
    if m is None:
        ok(False, "変異③の変異点が見つからない(検査が古い)")
    else:
        got = len(m.load_rows(p))
        ok(got == 0, "変異③(source=dispatch を丸ごと外す)= 裸の姓3行まで消えて[3b]が落ちる",
           "実測%d(裸の姓が0件になる)" % got)
        red += 1 if got == 0 else 0

    # 変異④= フル名の判定を「target が near に在れば外す」へ緩める(動きはする)。
    #   裸の姓とフル名が同じ現場に混ざった行まで消える= [1c]が落ちる。
    total += 1
    m = mutant("mut_loosefull",
               "    spans = [(m.start(), m.end()) for m in re.finditer(re.escape(target), near)]",
               "    return True\n"
               "    spans = [(m.start(), m.end()) for m in re.finditer(re.escape(target), near)]")
    if m is None:
        ok(False, "変異④の変異点が見つからない(検査が古い)")
    else:
        got = m.is_full_name_hit({"target": "一ノ瀬怜", "found": "一ノ瀬",
                                  "near": "一ノ瀬怜へ回す。だが一ノ瀬は今日休みだ"})
        ok(got, "変異④(near に target が在れば外す)= [1c]が落ちる(混在行まで消える)")
        red += 1 if got else 0

    print("  変異 %d件中%d件が狙いどおり赤" % (total, red))
    if red != total:
        FAIL.append("must-fail(変異が赤にならない)")


def main():
    tmp = tempfile.mkdtemp(prefix="ndc_selfloop_")
    n = load(NDC, "ndc_real")
    t1(n)
    t2(n)
    t3(n, tmp)
    t4()
    t5(n)
    must_fail(tmp)
    print("\n結果: %s%s" % ("PASS" if not FAIL else "FAIL",
                            "" if not FAIL else " (失敗 %d件)" % len(FAIL)))
    for f in FAIL:
        print("  - " + f)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
