# -*- coding: utf-8 -*-
"""話し手名の同形異字(ホモグリフ)を、呼称ゲートCが規則を引く**前**に正名へ寄せる回帰ガード。

壊れていた実物(2026-09-06 実測・イージス研究室):
  local/llm/naming_audit.jsonl に `persona="ККール"`(キリル К U+041A ×2)の判定行が **9行**。
  2026-09-04T09:55:36 / dept=hr-room / source=dispatch。呼称ルール.json の
  `speaker_target_overrides` は話し手名の**文字列一致**で引くので、化けた名前では
  「ククール→ケヴィン・デブライネ= 呼び捨てOK」の特例が当たらない= **別人として裁かれる**。
  実際その9行には `naming_fix target=ケヴィン・デブライネ` が入っている=
  ククールの**正しい呼び捨てを「デブライネさん」へ書き換えていた**(誤爆)。
  同じ便の1秒後(09:55:37)に出ている `homoglyph_body_fix` は**本文だけ**を直すもので、
  しかもこのゲートより**後**に走る= 話し手名は誰も直していなかった。

規律(docs/departments/00_common/skills/test-must-fail/SKILL.md):
  - 判定は本物のまま実行する(呼称ルール.json も本物を読む)。偽物にするのは台帳の置き場だけ。
  - 検査対象は毎回ソースから読み直して exec(.pyc の偽PASSを踏まない)。
  - 最後に must-fail= 実装を「動く別の実装」へ変異させ、この検査が落ちるか確かめる(C-053)。

実行: python -X utf8 scripts/llm/test_naming_gate_persona_homoglyph.py
"""
import io
import json
import os
import shutil
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
OG = os.path.join(HERE, "output_gates.py")

FAIL = []

# 事故の実物と同じ形= ククールが自室(hr-room)でデブライネを呼び捨てにする便。
# 呼称ルール.json の STO:「ククール→ケヴィン・デブライネ allowed=[デブライネ] yobisute=true」
# が当たれば**何も直さないのが正**。
BODY = "[ККール]\nデブライネ、DEF-hr-room-b5e833f5bd の件だ。\n"
GARBLED = "ККール"      # キリル К U+041A ×2 + カタカナ ール
CANON = "ククール"


def ok(cond, name, extra=""):
    print(("  OK   " if cond else "  FAIL ") + name + (("  " + str(extra)) if extra else ""))
    if not cond:
        FAIL.append(name)


def load(path, name):
    """毎回ソースから読み直す(.pyc の偽PASSを踏まない)。"""
    src = open(path, encoding="utf-8").read()
    mod = type(sys)(name)
    mod.__file__ = path
    mod.__dict__["__name__"] = name
    exec(compile(src, path, "exec"), mod.__dict__)
    return mod


def run_gate(og, persona, tmp, tag):
    """本物の apply_naming_gate_only を実行し、(本文, summary, 台帳の行) を返す。"""
    local = os.path.join(tmp, tag)
    os.makedirs(os.path.join(local, "llm"), exist_ok=True)
    og.NAMING_AUDIT = os.path.join(local, "llm", "naming_audit.jsonl")
    og.META_AUDIT = os.path.join(local, "llm", "meta_strip_audit.jsonl")
    out, summ = og.apply_naming_gate_only("hr-room", persona, BODY, source="test")
    rows = ([json.loads(l) for l in open(og.NAMING_AUDIT, encoding="utf-8")]
            if os.path.exists(og.NAMING_AUDIT) else [])
    return out, summ, rows


# ------------------------------------------------------------------ T1 純関数
def t1(og):
    print("T1 canon_persona= 一意に決まる時だけ寄せる")
    ok(og.canon_persona(GARBLED) == (CANON, GARBLED),
       "★化けた話し手名が正名へ寄る", og.canon_persona(GARBLED))
    ok(og.canon_persona("ккール") == (CANON, "ккール"), "小文字キリルでも寄る")
    ok(og.canon_persona(CANON) == (CANON, ""), "元から正しい名前は素通し(raw を立てない)")
    ok(og.canon_persona("ケヴィン・デブライネ") == ("ケヴィン・デブライネ", ""),
       "中黒入りの正名も素通し")
    ok(og.canon_persona("") == ("", ""), "空でも落ちない")
    ok(og.canon_persona("誰でもない人") == ("誰でもない人", ""),
       "名簿に居ない名前は触らない(勝手に誰かにしない)")
    # fail-open= 正本が読めない時も名前をそのまま返し、例外を外へ出さない
    saved = og._homoglyph
    try:
        og._homoglyph = None
        ok(og.canon_persona(GARBLED) == (GARBLED, ""),
           "★正本 homoglyph.py が無くても素通しで落ちない(fail-open)")
        class _Boom:
            def canonical_name(self, *a, **k):
                raise RuntimeError("boom")
        og._homoglyph = _Boom()
        ok(og.canon_persona(GARBLED) == (GARBLED, ""), "★中で例外が出ても便を止めない")
    finally:
        og._homoglyph = saved


# ------------------------------------------------- T2 判定が「別人扱い」にならない
def t2(og, tmp):
    print("T2 化けた名前でも、正名で来た時と**同じ判定**になる")
    out_g, sum_g, rows_g = run_gate(og, GARBLED, tmp, "garbled")
    out_c, sum_c, rows_c = run_gate(og, CANON, tmp, "canon")
    ok(out_g == out_c, "★本文の結果が正名の時と一致する", repr(out_g.split("\n")[1]))
    ok(out_g == BODY, "★ククール特例が効いて**何も書き換えない**(呼び捨てが正)")
    ok("デブライネさん" not in out_g,
       "★『デブライネさん』へ誤爆していない(壊れていた実物はここが書き換わった)")
    ok(sum_g.get("naming_fix", 0) == 0 and sum_c.get("naming_fix", 0) == 0,
       "直した件数は両方0", "%s / %s" % (sum_g.get("naming_fix"), sum_c.get("naming_fix")))
    ok(sum_g.get("naming_warn", 0) == sum_c.get("naming_warn", 0),
       "警告の件数も一致する")
    return rows_g


# --------------------------------------------------------- T3 化けた事実を消さない
def t3(rows):
    print("T3 寄せた事実を台帳に残す(『直したから何も無かった』に見せない)")
    homo = [r for r in rows if r.get("event") == "persona_homoglyph"]
    ok(len(homo) == 1, "persona_homoglyph の行が1本出る", "%d行" % len(homo))
    if homo:
        ok(homo[0].get("persona") == CANON, "persona は正名で残る", homo[0].get("persona"))
        ok(homo[0].get("persona_raw") == GARBLED, "★化けていた元の字も残る",
           homo[0].get("persona_raw"))
        ok(homo[0].get("dept") == "hr-room" and homo[0].get("source") == "test",
           "どの部屋のどの経路かも残る")
    # ドリフト判定(naming_drift_check.load_rows)は event=="naming" だけを数える=
    # この行が件数を水増ししないことを、本物の判定器で確かめる。
    counted = [r for r in rows if r.get("event") == "naming" and r.get("found")
               and r.get("target")]
    ok(all(r.get("event") != "persona_homoglyph" for r in counted),
       "★この行はドリフトの件数に混ざらない(event が naming ではない)")


# ------------------------------------------------------------- T4 壊れていた側の再現
def t4(tmp):
    print("T4 壊れていた実物の再現= 直す前のソースだと誤爆する(比較対象)")
    bak = os.path.join(HERE, "output_gates.py.bak_20260906_personahomo")
    if not os.path.exists(bak):
        ok(False, "退避した直す前のソースが在る", bak)
        return
    old = load(bak, "og_old")      # ★退避は scripts/llm/ の中= ルールのパスが本物のまま解ける
    out, summ, _ = run_gate(old, GARBLED, tmp, "old")
    ok(summ.get("naming_fix", 0) == 1 and "デブライネさん" in out,
       "★直す前は化けた名前で来た便を『デブライネさん』へ書き換えていた",
       "naming_fix=%s" % summ.get("naming_fix"))


# ------------------------------------------------------------------- must-fail
def must_fail(tmp):
    print("MUST-FAIL 実装を『動く別の実装』へ変異させて、この検査が落ちるか")
    src = open(OG, encoding="utf-8").read()
    muts = [
        # ①寄せない(化けた名前をそのまま規則へ渡す)= 元の壊れ方へ戻す
        ("①寄せない",
         "        canon, _why = _homoglyph.canonical_name(p)",
         "        canon, _why = \"\", \"disabled\""),
        # ②寄せるが、化けていた事実を捨てる(persona_raw を返さない)
        ("②化けた元を捨てる",
         "            return canon, p",
         "            return canon, \"\""),
        # ③候補が決まらなくても最初の1人へ寄せる= 取り違え(canonical_name の掛け金を外す)
        ("③曖昧でも寄せる",
         "        if canon and canon != p:",
         "        if canon is not None and canon != p:"),
    ]
    for i, (name, before, after) in enumerate(muts):
        if before not in src:
            ok(False, "変異%s= 目印が見つからない(実装が動いた?)" % name, before[:40])
            continue
        # ★変異体は**本物と同じ場所**へ置く(C-053)。output_gates.py は `__file__` から
        #   ROOT→呼称ルール.json のパスを組む= 別の場所へ置くと規則が読めず、
        #   「判定0件」で偽の緑になる(2026-09-06 実測でここを踏んだ)。
        p = os.path.join(HERE, "_mutant_phomo_%d.py" % i)
        open(p, "w", encoding="utf-8").write(src.replace(before, after, 1))
        try:
            m = load(p, "og_mut%d" % i)
            out, summ, rows = run_gate(m, GARBLED, tmp, "mut%d" % i)
        finally:
            for q in (p, p + "c"):
                if os.path.exists(q):
                    os.remove(q)
        homo = [r for r in rows if r.get("event") == "persona_homoglyph"]
        if i == 0:
            ok(summ.get("naming_fix", 0) == 1,
               "変異①(寄せない)= T2の『誤爆していない』が落ちる",
               "naming_fix=%s / 本文=%s" % (summ.get("naming_fix"),
                                            out.split("\n")[1][:20]))
        elif i == 1:
            ok(not homo or not homo[0].get("persona_raw"),
               "変異②(元を捨てる)= T3の『化けていた元も残る』が落ちる",
               "persona_homoglyph=%d行" % len(homo))
        else:
            # canonical_name は決まらない時 "" を返す= その "" を通してしまう変異。
            got = m.canon_persona("誰でもない人")
            ok(got == ("", "誰でもない人"),
               "変異③(曖昧でも寄せる)= T1の『名簿に居ない名前は触らない』が落ちる", got)


if __name__ == "__main__":
    og = load(OG, "og_new")
    tmp = tempfile.mkdtemp(prefix="phomo_")
    try:
        t1(og)
        rows = t2(og, tmp)
        t3(rows)
        t4(tmp)
        must_fail(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print()
    print("結果: " + ("PASS (失敗 0件)" if not FAIL else "FAIL %d件: %s" % (len(FAIL), FAIL)))
    sys.exit(1 if FAIL else 0)
