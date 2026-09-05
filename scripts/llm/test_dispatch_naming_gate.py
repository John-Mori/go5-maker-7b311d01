# -*- coding: utf-8 -*-
"""投函経路(dispatch)の呼称ゲートCの回帰ガード。DEF-hr-room-b5e833f5bd。

規律(docs/departments/00_common/skills/test-must-fail/SKILL.md):
  - 偽物にするのは**外へ出る手**だけ= キュー(inbox.db)の置き場と persona_send。
    判定・分岐・本文の書き換えは**本物をそのまま実行**する。
  - 検査対象は毎回ソースから読み直して exec(.pyc の偽PASSを踏まない)。
  - 最後に must-fail= 実装を「動く別の実装」へ変異させ、この検査が落ちるか確かめる。

実行: python scripts/llm/test_dispatch_naming_gate.py
"""
import io
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
DISPATCH = os.path.join(HERE, "dispatch.py")
RULES_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "..", "00_AI-HQ", "departments", "hr", "personas",
    "呼称ルール.json")
RULES_PATH = os.path.normpath(RULES_PATH)

FAIL = []

# 事故便そのもの(2026-09-02T11:25 の実物・ククール→デブライネ)と、
# 同じ便に混ぜた地の文= 直してはいけない側。
BODY = ("[ククール]\n"
        "デブライネさん、DEF-hr-room-b5e833f5bd の件だ。\n"
        "これはデブライネさんへ回した案件で、呼称ルール.json は default=デブライネさん だ。\n")

# ★実測コーパスから採った「直してはいけない」実文(ククールの実便・hr 2026-07-30/08-05)。
FP_SAMPLES = [
    "- 実在人物モデル=さん付け(三笘さん/アロンソさん/モドリッチさん/デブライネさん)。",
    "呼称ルール.json(デブライネ default=デブライネさん / モドリッチ default=モドリッチさん)",
    "(a)デ・ブライネさん→デブライネさん 表記統一",
]


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


# ---------------------------------------------------------------- T1 純関数の側
def t1():
    print("T1 naming_corrections(vocative_only=) の意味(純関数)")
    sys.path.insert(0, HERE)
    import naming_gate as ng
    rules = ng.load_naming_rules(RULES_PATH)
    ok(bool(rules), "呼称ルールが読める", RULES_PATH)
    voc = "デブライネさん、頼む。"
    ji = "これはデブライネさんへ回した案件だ。"
    r = ng.naming_corrections("ククール", "", voc, rules, vocative_only=True)
    ok(r["fixed"] == "デブライネ、頼む。", "呼びかけ位置は直る(dept無しでも)", r["fixed"])
    r = ng.naming_corrections("ククール", "", ji, rules, vocative_only=True)
    ok(r["fixed"] == ji and r["remaining"], "地の文は直さず警告のみ", r["fixed"])
    # 上書きしなければ従来どおり dept で決まる= 既存の呼び出し側の挙動を変えていない
    r = ng.naming_corrections("ククール", "", ji, rules)
    ok(r["fixed"] != ji, "vocative_only 未指定なら従来どおり(dept依存)", r["fixed"])
    r = ng.naming_corrections("ククール", "hr-room", ji, rules)
    ok(r["fixed"] == ji, "hr-room は従来どおり呼びかけ位置だけ", r["fixed"])


# ---------------------------------------------------------------- T2 経路③(投函)
RUNNER = r'''
import io,sys,os,json
sys.stdout=io.TextIOWrapper(sys.stdout.buffer,encoding="utf-8",errors="replace")
sys.path.insert(0, r"{here}")
src=open(r"{disp}",encoding="utf-8").read()
m=type(sys)("dispatch_under_test"); m.__file__=r"{disp}"
exec(compile(src,r"{disp}","exec"), m.__dict__)
m.HERE=r"{here}"                       # 変異コピーからでも兄弟モジュールを見つける
m.QUEUE_DB=r"{qdb}"                    # ★外へ出る手その1= キューを temp へ
m.PERSONA_SEND=r"{fake}"               # ★外へ出る手その2= 表投稿を偽物へ
ok,mid=m.dispatch("aegis-gl","ククール(人事部門)",{body!r},False,False,
                  "呼称ゲートの実装",'ai',"hr-room")
print(json.dumps({{"ok":ok,"mid":mid}},ensure_ascii=False))
'''

FAKE_SEND = r'''
import io,sys,os
sys.stdout=io.TextIOWrapper(sys.stdout.buffer,encoding="utf-8",errors="replace")
a=sys.argv
body=a[a.index("--body")+1] if "--body" in a else ""
open(os.environ["FAKE_SEND_OUT"],"w",encoding="utf-8").write(body)
print("msg=999999999")
'''


def run_dispatch(tmp, dispatch_path, tag):
    """本物の dispatch() を、外へ出る手だけ偽物にして**実行**する。"""
    local = os.path.join(tmp, tag, "local")
    os.makedirs(os.path.join(local, "llm"), exist_ok=True)
    os.makedirs(os.path.join(local, "queue"), exist_ok=True)
    qdb = os.path.join(local, "queue", "inbox.db")
    fake = os.path.join(tmp, tag + "_fake_send.py")
    sent = os.path.join(tmp, tag + "_sent.txt")
    open(fake, "w", encoding="utf-8").write(FAKE_SEND)
    code = RUNNER.format(here=HERE, disp=dispatch_path, qdb=qdb, fake=fake, body=BODY)
    env = dict(os.environ, GO5_LOCAL_DIR=local, FAKE_SEND_OUT=sent)
    p = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    rows = []
    if os.path.exists(qdb):
        try:
            con = sqlite3.connect(qdb)
            rows = [r[0] for r in con.execute("select body from queue order by id").fetchall()]
            con.close()
        except Exception as e:
            rows = ["<<db read error: %s>>" % e]
    audit = os.path.join(local, "llm", "naming_audit.jsonl")
    arows = ([json.loads(l) for l in open(audit, encoding="utf-8")]
             if os.path.exists(audit) else [])
    posted = open(sent, encoding="utf-8").read() if os.path.exists(sent) else ""
    return p, rows, arows, posted


def t2(tmp):
    print("T2 経路③(投函 dispatch)= キューへ入る本文と表投稿の本文")
    p, rows, arows, posted = run_dispatch(tmp, DISPATCH, "real")
    ok(bool(rows), "キューへ投函できた(本物の enqueue を実行)",
       (p.stdout or "")[-160:] + (p.stderr or "")[-160:])
    if not rows:
        return None
    rec = json.loads(rows[-1])
    content = rec.get("content", "")
    ok("デブライネさん、" not in content, "★呼びかけの『デブライネさん、』が消えている",
       content.split("\n")[1][:40] if "\n" in content else content[:40])
    ok("デブライネ、DEF-hr-room" in content, "呼び捨てへ直っている")
    ok("デブライネさんへ回した" in content, "地の文は**壊していない**(警告のみ)")
    ok("default=デブライネさん" in content, "設定値の記述も壊していない")
    ok(posted and "デブライネさん、" not in posted and "デブライネ、DEF" in posted,
       "表投稿(--work)の本文も直った版が出ている", posted[:60].replace("\n", "⏎"))
    hit = [r for r in arows if r.get("source") == "dispatch"]
    ok(bool(hit), "台帳へ source=dispatch で残る", "%d行" % len(arows))
    ok(any(r.get("event") == "naming_fix" for r in hit), "event=naming_fix が在る")
    ok(any(r.get("event") == "naming" for r in hit), "警告のみ(event=naming)も残る")
    return content


# ------------------------------------------------- T2b 二重記録(2026-09-06 追加)
RUNNER_GATED = RUNNER.replace(
    '"呼称ゲートの実装",\'ai\',"hr-room")',
    '"呼称ゲートの実装",\'ai\',"hr-room",already_gated=True)')


def run_dispatch_gated(tmp, tag, dispatch_path=None):
    """already_gated=True で本物の dispatch() を実行する(外へ出る手だけ偽物)。"""
    DISPATCH = dispatch_path or globals()["DISPATCH"]
    local = os.path.join(tmp, tag, "local")
    os.makedirs(os.path.join(local, "llm"), exist_ok=True)
    os.makedirs(os.path.join(local, "queue"), exist_ok=True)
    qdb = os.path.join(local, "queue", "inbox.db")
    fake = os.path.join(tmp, tag + "_fake_send.py")
    open(fake, "w", encoding="utf-8").write(FAKE_SEND)
    code = RUNNER_GATED.format(here=HERE, disp=DISPATCH, qdb=qdb, fake=fake, body=BODY)
    env = dict(os.environ, GO5_LOCAL_DIR=local, FAKE_SEND_OUT=os.path.join(tmp, tag + "_s.txt"))
    subprocess.run([sys.executable, "-c", code], env=env, capture_output=True,
                   text=True, encoding="utf-8", errors="replace")
    rows = []
    if os.path.exists(qdb):
        con = sqlite3.connect(qdb)
        rows = [r[0] for r in con.execute("select body from queue order by id").fetchall()]
        con.close()
    audit = os.path.join(local, "llm", "naming_audit.jsonl")
    arows = ([json.loads(l) for l in open(audit, encoding="utf-8")]
             if os.path.exists(audit) else [])
    return rows, arows


def t2b(tmp, arows_ungated):
    """★同じ違反が台帳へ2行入っていた所のガード(実測 2026-09-06・イージス研究室)。

    壊れていた実物= main() が投函前に1回、dispatch() が部門ごとにもう1回
    naming_gate_pass を通す。ゲートCの大半は**警告のみ**で本文を書き換えないので、
    2回目が同じ違反をもう一度見つけて naming_audit.jsonl へ**同じ行**を書いていた。
    窓14日の実測= source="dispatch" の判定行433のうち207が重複(source!=dispatch は0)。
    """
    print("T2b 二重記録= main() が通した便を dispatch() がもう一度台帳へ書かない")
    rows, arows = run_dispatch_gated(tmp, "gated")
    ok(bool(rows), "already_gated=True でも便は届く(投函そのものは止めない)")
    ok(len(arows) == 0, "already_gated=True では台帳へ1行も書かない",
       "実測%d行" % len(arows))
    if rows:
        rec = json.loads(rows[-1])
        ok("デブライネさん、" in rec.get("content", ""),
           "★本文も当てない= 直すのは1回目の関門の仕事(ここは素通し)")
    n1 = len([r for r in arows_ungated or [] if r.get("event") in ("naming", "naming_fix")])
    ok(n1 > 0 and len(arows) == 0,
       "同じ便= 関門1回なら%d行 / 2回目は0行(旧実装ならここが2倍)" % n1)
    src = open(DISPATCH, encoding="utf-8").read()
    ok("already_gated=True)" in src,
       "main() の投函ループが already_gated=True を渡している(配線の実物)")


# ---------------------------------------------------------------- T3 誤爆ガード
def t3(tmp):
    print("T3 誤爆ガード= ククールの実便から採った『直してはいけない』文")
    sys.path.insert(0, HERE)
    import output_gates as og
    og.NAMING_AUDIT = os.path.join(tmp, "t3_naming_audit.jsonl")  # 本番の台帳を汚さない
    for s in FP_SAMPLES:
        out, summ = og.apply_naming_gate_only("hr-room", "ククール", s, source="test")
        ok(out == s, "触らない: " + s[:34], "→ " + out[:34])


# ---------------------------------------------------------------- T4 fail-open
def t4():
    print("T4 fail-open= ゲートが転んでも便は止めない")
    mod = load(DISPATCH, "dispatch_failopen")
    mod.HERE = HERE
    boom = type(sys)("output_gates")

    def _raise(*a, **k):
        raise RuntimeError("boom")
    boom.apply_naming_gate_only = _raise
    sys.modules["output_gates"] = boom
    try:
        out, nfix, nwarn = mod.naming_gate_pass("ククール(人事部門)", "hr-room", BODY)
    finally:
        sys.modules.pop("output_gates", None)
    ok(out == BODY and nfix == 0 and nwarn == 0, "例外でも元の本文をそのまま返す")


# ---------------------------------------------------------------- must-fail
def must_fail(tmp):
    """★変異体は **scripts/llm の中**へ置く(finally で消す)。

    最初 temp フォルダへ置いたら2本とも「落ちない」= 偽の合格に見えた。理由は変異ではなく
    置き場だった: dispatch は `ROOT`/`CHANNELS` を、output_gates は `_HERE`/`HQ`/
    `NAMING_RULES_PATH` を **自分の __file__ から**組み立てる。temp に居る変異体は台帳も
    呼称ルールも見つけられず、変異の有無に関係なく早期 return していた。
    変異体は本物と**同じ場所**に居ないと、本物の経路を走らない。
    """
    print("MUST-FAIL 実装を『動く別の実装』へ変異させて、この検査が落ちるか")
    src = open(DISPATCH, encoding="utf-8").read()
    # 変異①= 合流点のゲート呼び出しを外す(=変異前の実装そのもの・動きはする)
    anchor = "        body, _nfix, _nwarn = naming_gate_pass(sender, from_dept, body)"
    ogsrc = open(os.path.join(HERE, "output_gates.py"), encoding="utf-8").read()
    a2 = "                                              vocative_only=vocative_only) or {}"
    if anchor not in src or a2 not in ogsrc:
        ok(False, "変異点が見つからない(検査が古い)")
        return
    mut = os.path.join(HERE, "_mutant_dispatch_tmp.py")
    mut2 = os.path.join(HERE, "_mutant_output_gates_tmp.py")
    try:
        open(mut, "w", encoding="utf-8").write(
            src.replace(anchor, "        body, _nfix, _nwarn = body, 0, 0"))
        _, rows, _, _ = run_dispatch(tmp, mut, "mut1")
        content = json.loads(rows[-1]).get("content", "") if rows else ""
        ok("デブライネさん、" in content,
           "変異①(ゲートを外す)= T2の期待が満たせなくなる", content[:40].replace("\n", "⏎"))
        # 変異②= 呼びかけ位置の限定を外す(地の文まで直す実装)。T3の誤爆ガードが落ちるはず。
        open(mut2, "w", encoding="utf-8").write(ogsrc.replace(
            a2, "                                              vocative_only=False) or {}"))
        og2 = load(mut2, "og_mutant")
        og2.NAMING_AUDIT = os.path.join(tmp, "mut2_naming_audit.jsonl")
        broke = [s for s in FP_SAMPLES
                 if og2.apply_naming_gate_only("hr-room", "ククール", s, source="test")[0] != s]
        ok(bool(broke), "変異②(地の文まで直す)= T3の誤爆ガードが落ちる",
           "%d/%d件が書き換わる" % (len(broke), len(FP_SAMPLES)))
        # 変異③= already_gated を無視して**必ず**関門を通す(=2026-09-06以前の実装)。
        a3 = "    if not already_gated:"
        if a3 not in src:
            ok(False, "変異③の変異点が見つからない(検査が古い)")
        else:
            mut3 = os.path.join(HERE, "_mutant_dispatch_dup_tmp.py")
            try:
                open(mut3, "w", encoding="utf-8").write(src.replace(a3, "    if True:", 1))
                _r, arows3 = run_dispatch_gated(tmp, "mut3", mut3)
                ok(len(arows3) > 0, "変異③(already_gated を無視)= T2bの二重記録ガードが落ちる",
                   "台帳へ%d行書かれる" % len(arows3))
            finally:
                try:
                    os.remove(mut3)
                except OSError:
                    pass
    finally:
        for p in (mut, mut2):
            try:
                os.remove(p)
            except OSError:
                pass


if __name__ == "__main__":
    tmp = tempfile.mkdtemp(prefix="dispgate_")
    try:
        t1()
        t2(tmp)
        # run_dispatch() は (p, rows, arows, posted) を返す= 台帳は**3番目**
        _, _, _arows_ungated, _ = run_dispatch(tmp, DISPATCH, "ungated")
        t2b(tmp, _arows_ungated)
        t3(tmp)
        t4()
        must_fail(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n結果: %s (失敗 %d件)" % ("PASS" if not FAIL else "FAIL", len(FAIL)))
    for f in FAIL:
        print("  - " + f)
    sys.exit(1 if FAIL else 0)
