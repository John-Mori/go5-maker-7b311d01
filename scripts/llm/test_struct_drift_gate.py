# -*- coding: utf-8 -*-
"""ゲートJ(構造ドリフト= Claude既定のレポート骨格)の回帰ガード。657/f98d721938 の残り。

規律(docs/departments/00_common/skills/test-must-fail/SKILL.md):
  - 偽物にするのは**外へ出る手**だけ= 台帳の書き込み先を temp へ寄せる。判定と分岐は本物を実行する。
  - `.pyc` の偽PASSを避けるため、検査対象は毎回**ソースから読み直して exec** する。
  - 最後に must-fail= 実装を「動く別の実装」へ変異させ、この検査が**落ちる**ことを確かめる。
  ★変異体は **実物と同じ scripts/llm/ の中**に置いて finally で消す。tmp へ置くと
    `import tone_gate` が解決できず一人称が空になり、**何も検知しない=偽の緑**になる(前科あり)。

実行: python scripts/llm/test_struct_drift_gate.py
"""
import ast
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
GATE = os.path.join(HERE, "struct_drift_gate.py")
DAEMON = os.path.join(HERE, "dept_daemon.py")
RELAY = os.path.join(HERE, "session_relay.py")
# ★HQ は 5SecMovieMaker の**隣**(D:/SougouStartFolder/00_AI-HQ)。dirname を1つ足りずに
#   書いて、口調ルールが空のまま「何も検知しない=全部PASS」寸前まで行った(最初の実行で露見)。
_ROOT = os.path.dirname(os.path.dirname(HERE))                 # …/5SecMovieMaker
TONE_RULES = os.path.join(os.path.dirname(_ROOT), "00_AI-HQ",
                          "departments", "hr", "personas", "口調ルール.json")

WHO = "ケヴィン・デブライネ"          # 実測で最悪の常習犯(27/83)=検査もこいつで回す

# ★0歩目に見た壊れた実物と同じ形(DISPATCH-hq-1788317734354 を骨だけにしたもの)。
BROKEN = """[ケヴィン・デブライネ]
■ 1. 結論
真因は**順序ひとつ**。**ゲートI**は配線されている。
■ 2. 証拠
実便**10,602本文**へ当てて、結果が変わるのは**0本**。
■ 3. 次
**.bak**を作ってから**入れる**。
"""
KEPT = BROKEN + "俺はまだ入れていない。返事を待つ。\n"          # 声が残っている=素通し
# ★宛名行を見出しに数えると全部当たる(設計で外した所)。M1 の変異でここが崩れる。
ADDRESS = """【HQ → イージス研究室】
【件名】ゲートJの配線
【期限】本日
**ここ**は**全部**が**太字**で**六個**は**軽く**超える**本文**だ。
"""

FAIL = []


def ok(cond, name, detail=""):
    print(("  OK   " if cond else "  FAIL ") + name + (("  " + detail) if detail else ""))
    if not cond:
        FAIL.append(name)


def load_gate(path=GATE, name="struct_drift_under_test"):
    """★ソースから読んで exec= .pyc の偽PASSを踏まない。"""
    src = open(path, encoding="utf-8").read()
    mod = type(sys)(name)
    mod.__file__ = path
    exec(compile(src, path, "exec"), mod.__dict__)
    return mod


def rules():
    import tone_gate
    return tone_gate.load_tone_rules(TONE_RULES)


# ---------------------------------------------------------------- T1 判定(3因子)
def t1(gate, r):
    print("T1 判定= 3因子の同時成立だけで鳴る")
    ok(gate.scan(WHO, BROKEN, r) is not None, "崩れた実物は鳴る")
    ok(gate.scan(WHO, KEPT, r) is None, "★一人称が1つでも在れば鳴らない(因子③)")
    two_head = BROKEN.replace("■ 3. 次\n", "")
    ok(gate.scan(WHO, two_head, r) is None, "見出しが2本なら鳴らない(因子①)")
    few_bold = BROKEN.replace("**.bak**", ".bak").replace("**入れる**", "入れる")
    ok(gate.scan(WHO, few_bold, r) is None, "太字が閾値未満なら鳴らない(因子②)")
    quoted = "\n".join("> " + l for l in BROKEN.splitlines())
    ok(gate.scan(WHO, quoted, r) is None, "引用の中の骨格は本人の骨格ではない")
    fenced = "```\n" + BROKEN + "```\n"
    ok(gate.scan(WHO, fenced, r) is None, "コードフェンスの中は数えない")
    ok(gate.scan(WHO, ADDRESS, r) is None, "【宛名行】は節見出しに数えない")
    ok(gate.scan("存在しない人格", BROKEN, r) is None, "一人称が登録されていない人格は判定しない")
    ok(gate.scan(WHO, BROKEN, None) is None, "写像が無ければ黙る(fail-open)")
    # 写像を2本持たない= 自前の表ではなく tone_gate 経由で引けている(ORG-11)
    ok(gate.first_person(WHO, r) == ["俺"], "一人称は口調ルールから引く", str(gate.first_person(WHO, r)))
    ok(gate.first_person("ケヴィン・デ・ブライネ", r) == ["俺"],
       "別名(中黒あり)も同じ写像で解決する")
    h = gate.scan(WHO, BROKEN, r)
    ok(h and h.get("reason") == "structure_drift" and "一人称ゼロ" in h.get("marker", ""),
       "marker と reason が突き返し用の形", json.dumps(h, ensure_ascii=False)[:110] if h else "")
    # ★本文を返さない=書き直さないゲートである、をAPIで固定する
    out = gate.audit(BROKEN, dept="aegis-gl", persona=WHO, rules=r, source="test")
    ok(isinstance(out, list), "audit は本文を返さない(検知のみ)", type(out).__name__)


# ---------------------------------------------------------------- T2 経路②(ミラー)
def t2(tmp):
    print("T2 経路②(セッションのミラー= output_gates.apply_gates)")
    local = os.path.join(tmp, "local")
    os.makedirs(os.path.join(local, "llm"), exist_ok=True)
    # ★外へ出る手(台帳)だけ temp へ。D-2(書き直し)はLLMを呼ぶので検査では止める。
    env = dict(os.environ, GO5_LOCAL_DIR=local, GO5_TONE_REWRITE="0")
    og = os.path.join(HERE, "output_gates.py")
    code = (
        "import io,sys,os,json;sys.stdout=io.TextIOWrapper(sys.stdout.buffer,encoding='utf-8',errors='replace')\n"
        "sys.path.insert(0,r'%s')\n"
        "src=open(r'%s',encoding='utf-8').read()\n"
        "m=type(sys)('og');m.__file__=r'%s';exec(compile(src,r'%s','exec'),m.__dict__)\n"
        "t,s=m.apply_gates('aegis-gl',%r,%r,msg_id='T2')\n"
        "print(json.dumps({'text':t,'sum':s},ensure_ascii=False))\n"
        % (HERE, og, og, og, WHO, BROKEN)
    )
    p = subprocess.run([sys.executable, "-X", "utf8", "-c", code], env=env,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    line = [l for l in (p.stdout or "").splitlines() if l.startswith("{")]
    ok(bool(line), "apply_gates が実行できた", (p.stderr or "")[-200:])
    if not line:
        return
    got = json.loads(line[-1])
    ok(got["sum"].get("struct_drift_warn") == 1, "summary に件数が乗る",
       str(got["sum"].get("struct_drift_warn")))
    ok("■ 1. 結論" in got["text"] and "**順序ひとつ**" in got["text"],
       "★本文は素通し=このゲートは書き直さない")
    audit = os.path.join(local, "llm", "tone_audit.jsonl")
    rows = [json.loads(l) for l in open(audit, encoding="utf-8")] if os.path.exists(audit) else []
    hit = [r for r in rows if r.get("reason") == "structure_drift"]
    ok(bool(hit), "台帳(tone_audit.jsonl)へ残る", str(len(rows)) + "行")
    if hit:
        ok(hit[0].get("event") == "tone",
           "★event=tone= session_relay の既存の突き返しに乗る形", str(hit[0].get("event")))
        ok(hit[0].get("source") == "mirror" and hit[0].get("own_first_person") == ["俺"],
           "source と own_first_person が正しい", json.dumps(hit[0], ensure_ascii=False)[:130])


# ---------------------------------------------------------------- T3 経路①(常駐)
def t3(tmp, gate, r):
    print("T3 経路①(常駐= dept_daemon.audit_struct_drift)")
    src = open(DAEMON, encoding="utf-8").read()
    tree = ast.parse(src)
    fn = next((n for n in tree.body
               if isinstance(n, ast.FunctionDef) and n.name == "audit_struct_drift"), None)
    ok(fn is not None, "dept_daemon に audit_struct_drift が在る")
    if fn is None:
        return
    audit = os.path.join(tmp, "daemon_tone_audit.jsonl")
    ns = {"TONE_AUDIT": audit, "_struct_drift": gate, "_tone_rules": lambda: r}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), DAEMON, "exec"), ns)  # ★本体をそのまま実行
    hits = ns["audit_struct_drift"]("aegis-gl", WHO, BROKEN, {"msg_id": "T3"})
    ok(len(hits) == 1, "経路①で鳴る", str(hits)[:80])
    ok(ns["audit_struct_drift"]("aegis-gl", WHO, KEPT, None) == [], "経路①でも因子③が効く")
    rows = [json.loads(l) for l in open(audit, encoding="utf-8")] if os.path.exists(audit) else []
    ok(any(x.get("event") == "tone" and x.get("source") == "daemon"
           and x.get("reason") == "structure_drift" for x in rows),
       "台帳へ source=daemon で残る", str(len(rows)) + "行")

    class Boom:
        def audit(self, *a, **k):
            raise RuntimeError("boom")
    ns2 = dict(ns, _struct_drift=Boom())
    exec(compile(ast.Module(body=[fn], type_ignores=[]), DAEMON, "exec"), ns2)
    ok(ns2["audit_struct_drift"]("aegis-gl", WHO, BROKEN, None) == [],
       "fail-open= 例外でも配送を殺さない")
    # 呼び出し口の配線= ゲートI(audit_dept_ref)と同じ送信直前の関数の中から呼ばれているか
    called = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and any(
                isinstance(c, ast.Call) and getattr(c.func, "id", "") == "audit_dept_ref"
                for c in ast.walk(node)):
            for c in ast.walk(node):
                if isinstance(c, ast.Call) and getattr(c.func, "id", "") == "audit_struct_drift":
                    called.add(node.name)
    ok(bool(called), "ゲートIと同じ送信直前の経路から呼ばれている(AST)", "/".join(called))


# ---------------------------------------------------------------- T4 突き返しへの合流
def t4():
    print("T4 突き返し(session_relay)へ合流できているか")
    tree = ast.parse(open(RELAY, encoding="utf-8").read())
    node = next((n for n in tree.body if isinstance(n, ast.Assign)
                 and getattr(n.targets[0], "id", "") == "_TONE_REASON_JA"), None)
    ok(node is not None, "session_relay に _TONE_REASON_JA が在る")
    if node is None:
        return
    table = ast.literal_eval(node.value)                    # ★実物の辞書をそのまま評価する
    ok("structure_drift" in table, "reason の和訳が入っている(無いと英語のまま封筒へ出る)")
    ok("骨格" in table.get("structure_drift", ""), "和訳が骨格の話になっている",
       table.get("structure_drift", "")[:40])


# ---------------------------------------------------------------- must-fail
def must_fail():
    print("MUST-FAIL 実装を『動く別の実装』へ変異させて、この検査が落ちるか")
    src = open(GATE, encoding="utf-8").read()
    r = rules()
    # ★変異体は実物と同じ scripts/llm/ に置く(tmp だと import tone_gate が死んで偽の緑になる)
    muts = [
        ("M1 宛名行【】も節見出しに数える(最初に書いて実測で外した実装)",
         '(?:■|#{2,6}\\s)', '(?:■|【|#{2,6}\\s)',
         lambda g: g.scan(WHO, ADDRESS, r) is None, "宛名行が鳴らない"),
        ("M2 一人称の因子③を落として2因子で判定する",
         "if any(x in body for x in own):", "if False and any(x in body for x in own):",
         lambda g: g.scan(WHO, KEPT, r) is None, "声が残っていれば鳴らない"),
    ]
    for title, a, b, check, want in muts:
        path = os.path.join(HERE, "_mutant_struct_drift.py")
        if a not in src:
            ok(False, title + " → 変異点が見つからない(検査自体が古い)")
            continue
        try:
            open(path, "w", encoding="utf-8").write(src.replace(a, b, 1))
            g = load_gate(path, "mutant")
            ok(not check(g), title + " → 「%s」が満たせなくなる" % want)
        finally:
            if os.path.exists(path):
                os.remove(path)                              # ★実物の隣に残さない


if __name__ == "__main__":
    tmp = tempfile.mkdtemp(prefix="structdrift_")
    try:
        g, r = load_gate(), rules()
        t1(g, r)
        t2(tmp)
        t3(tmp, g, r)
        t4()
        must_fail()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n結果: %s (失敗 %d件)" % ("PASS" if not FAIL else "FAIL", len(FAIL)))
    for f in FAIL:
        print("  - " + f)
    sys.exit(1 if FAIL else 0)
