# -*- coding: utf-8 -*-
"""ゲートI(部門参照)の回帰ガード。DEF-kaizen-analyst-9d9bd45e55。

規律(docs/departments/00_common/skills/test-must-fail/SKILL.md):
  - 偽物にするのは**外へ出る手**だけ= 台帳の書き込み先を temp へ寄せる。判定と分岐は本物を実行する。
  - `.pyc` の偽PASSを避けるため、検査対象は毎回**ソースから読み直して exec** する。
  - 最後に must-fail= 実装を「動く別の実装」へ変異させ、この検査が**落ちる**ことを確かめる。
    (落ちなければ、この検査は何も守っていない)

実行: python scripts/llm/test_dept_ref_gate.py
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
GATE = os.path.join(HERE, "dept_ref_gate.py")
DAEMON = os.path.join(HERE, "dept_daemon.py")

FAIL = []


def ok(cond, name, detail=""):
    print(("  OK   " if cond else "  FAIL ") + name + (("  " + detail) if detail else ""))
    if not cond:
        FAIL.append(name)


def load_gate(path=GATE, name="dept_ref_gate_under_test"):
    """★ソースから読んで exec= .pyc の偽PASSを踏まない。"""
    src = open(path, encoding="utf-8").read()
    mod = type(sys)(name)
    mod.__file__ = path
    exec(compile(src, path, "exec"), mod.__dict__)
    return mod


# ---------------------------------------------------------------- T1 判定と置換
CASES = [
    # (本文, 直るべきか, 期待する新しい本文の一部)
    ("dept_daemon.py の DEPT_CONF 案件=基盤なので人事の範囲外・怜へ回す。", True, "プラットフォームSEへ回す"),
    ("今、一ノ瀬怜へ回したよ。", True, "プラットフォームSEへ回したよ"),
    ("**十王星南へ渡してくれ**。", True, "商品候補選定部門へ渡してくれ"),
    ("プラットフォームSE(一ノ瀬怜)へ回す。", False, ""),      # 除外② 併記形
    ("platform-se(一ノ瀬怜)へ回す。", False, ""),             # 除外② 併記形(スラッグ)
    ("怜さんへ回す。", False, ""),                            # 除外① 敬称=人物への言及
    ("怜が言ってたぞ。", False, ""),                          # 人物言及=そもそも当たらない
    ("> 一ノ瀬怜へ回す", False, ""),                          # 引用行
    ("まだ「怜へ渡した」段階だ。", False, ""),                # 鉤括弧の中
    ("アメス/ヴィルシーナ/十王星南 の5人だ。", False, ""),    # 名簿の列挙(C_list不採用の実証)
    ("それは基盤側=一ノ瀬怜の持ち場だ。", False, ""),         # B_own= 検知のみ(本文は変えない)
]


def t1(gate):
    print("T1 判定と置換(ゲート単体)")
    for text, should_fix, want in CASES:
        out, hits = gate.apply(text)
        if should_fix:
            ok(out != text and want in out, "直す: %s" % text[:28], "→ %s" % out[:40])
        else:
            ok(out == text, "触らない: %s" % text[:28], "→ %s" % out[:40])
    # B_own は「検知はする(台帳に残る)が本文は変えない」= 素通しと無検知を混ぜない
    _, hits = gate.apply("それは基盤側=一ノ瀬怜の持ち場だ。")
    ok(any(h["rule"] == "B_own" for h in hits), "B_own は検知だけする(警告のみ)")
    # 写像の安全弁= 1人格が複数部門を持つ時は置換先が決まらないので対象外
    m = gate.dept_map()
    ok("アメス" not in m and "花海咲季" not in m, "複数部門を持つ人格は置換対象から外れている")
    ok("シャビ・アロンソ" not in m, "registry が実態と割れている人格(アロンソ)は明示除外")
    ok(m.get("一ノ瀬怜", ("", ""))[1] == "プラットフォームSE", "写像は org_registry の display_ja")


# ---------------------------------------------------------------- T2 経路②(ミラー)
def t2(tmp):
    print("T2 経路②(セッションのミラー= output_gates.apply_gates)")
    local = os.path.join(tmp, "local")
    os.makedirs(os.path.join(local, "llm"), exist_ok=True)
    env = dict(os.environ, GO5_LOCAL_DIR=local)     # ★外へ出る手(台帳の書き込み先)だけ temp へ
    code = (
        "import io,sys,os,json;sys.stdout=io.TextIOWrapper(sys.stdout.buffer,encoding='utf-8',errors='replace')\n"
        "sys.path.insert(0,r'%s')\n"
        "src=open(r'%s',encoding='utf-8').read()\n"
        "m=type(sys)('og');m.__file__=r'%s';exec(compile(src,r'%s','exec'),m.__dict__)\n"
        "t,s=m.apply_gates('hq','シャビ・アロンソ','[シャビ・アロンソ]\\nこれは基盤だ。怜へ回す。')\n"
        "print(json.dumps({'text':t,'sum':s},ensure_ascii=False))\n"
        % (HERE, os.path.join(HERE, "output_gates.py"), os.path.join(HERE, "output_gates.py"),
           os.path.join(HERE, "output_gates.py"))
    )
    p = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    line = [l for l in (p.stdout or "").splitlines() if l.startswith("{")]
    ok(bool(line), "apply_gates が実行できた", (p.stderr or "")[-200:])
    if not line:
        return
    got = json.loads(line[-1])
    ok("プラットフォームSEへ回す" in got["text"], "経路②で本文が直る", got["text"].replace("\n", "⏎"))
    ok(got["sum"].get("dept_ref_fix") == 1, "summary に件数が乗る", str(got["sum"].get("dept_ref_fix")))
    ok("[シャビ・アロンソ]" in got["text"], "1行目の名乗り札を壊していない")
    audit = os.path.join(local, "llm", "naming_audit.jsonl")
    rows = [json.loads(l) for l in open(audit, encoding="utf-8")] if os.path.exists(audit) else []
    hit = [r for r in rows if r.get("event") == "dept_ref_fix"]
    ok(bool(hit), "台帳へ event=dept_ref_fix が残る", str(len(rows)) + "行")
    if hit:
        ok(hit[0].get("source") == "mirror" and hit[0].get("target") == "platform-se",
           "台帳の source/target が正しい", json.dumps(hit[0], ensure_ascii=False)[:120])


# ---------------------------------------------------------------- T3 経路①(常駐)
def t3(tmp, gate):
    print("T3 経路①(常駐= dept_daemon.audit_dept_ref)")
    src = open(DAEMON, encoding="utf-8").read()
    tree = ast.parse(src)
    fn = next((n for n in tree.body
               if isinstance(n, ast.FunctionDef) and n.name == "audit_dept_ref"), None)
    ok(fn is not None, "dept_daemon に audit_dept_ref が在る")
    if fn is None:
        return
    audit = os.path.join(tmp, "daemon_naming_audit.jsonl")
    ns = {"os": os, "json": json, "time": __import__("time"),
          "NAMING_AUDIT": audit, "_dept_ref": gate}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), DAEMON, "exec"), ns)  # ★本体をそのまま実行
    text = "これは基盤だ。怜へ回す。"
    fixed, applied, remaining = ns["audit_dept_ref"]("hq", "シャビ・アロンソ", text,
                                                    {"msg_id": "T3"})
    ok("プラットフォームSEへ回す" in fixed, "経路①で本文が直る", fixed)
    ok(len(applied) == 1 and not remaining, "applied/remaining の仕分け")
    rows = [json.loads(l) for l in open(audit, encoding="utf-8")] if os.path.exists(audit) else []
    ok(any(r.get("event") == "dept_ref_fix" and r.get("source") == "daemon" for r in rows),
       "台帳へ source=daemon で残る", str(len(rows)) + "行")
    # fail-open= ゲートが転んでも配送を殺さない(本文をそのまま返す)
    class Boom:
        FIX_RULES = {"A_route"}

        def apply(self, *a, **k):
            raise RuntimeError("boom")
    ns2 = dict(ns)
    ns2["_dept_ref"] = Boom()
    exec(compile(ast.Module(body=[fn], type_ignores=[]), DAEMON, "exec"), ns2)
    f2, a2, r2 = ns2["audit_dept_ref"]("hq", "アロンソ", text, None)
    ok(f2 == text and a2 == [] and r2 == [], "fail-open= 例外でも元の本文を返す")
    # 呼び出し口の配線(ゲートHと同じ関数の中から呼ばれているか)
    called = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and any(
                isinstance(c, ast.Call) and getattr(c.func, "id", "") == "audit_kana_choice"
                for c in ast.walk(node)):
            for c in ast.walk(node):
                if isinstance(c, ast.Call) and getattr(c.func, "id", "") == "audit_dept_ref":
                    called.add(node.name)
    ok(bool(called), "ゲートHと同じ送信直前の経路から呼ばれている(AST)", "/".join(called))


# ---------------------------------------------------------------- must-fail
def must_fail(tmp):
    print("MUST-FAIL 実装を『動く別の実装』へ変異させて、この検査が落ちるか")
    mut = os.path.join(tmp, "dept_ref_gate_mutant.py")
    src = open(GATE, encoding="utf-8").read()
    # 変異= 置換先を display_ja ではなく**人格名そのもの**にする。動きはするが裁定に反する実装。
    src2 = src.replace('out[persona] = lst[0]', 'out[persona] = (lst[0][0], persona)')
    if src2 == src:
        print("  FAIL 変異点が見つからない(検査自体が古い)")
        FAIL.append("mutation-anchor")
        return
    open(mut, "w", encoding="utf-8").write(src2)
    gate = load_gate(mut, "mutant")
    out, _ = gate.apply("これは基盤だ。怜へ回す。")
    ok(out == "これは基盤だ。怜へ回す。" or "プラットフォームSE" not in out,
       "変異させると T1 の期待(プラットフォームSEへ回す)が満たせない", out)


if __name__ == "__main__":
    tmp = tempfile.mkdtemp(prefix="deptref_")
    try:
        g = load_gate()
        t1(g)
        t2(tmp)
        t3(tmp, g)
        must_fail(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n結果: %s (失敗 %d件)" % ("PASS" if not FAIL else "FAIL", len(FAIL)))
    for f in FAIL:
        print("  - " + f)
    sys.exit(1 if FAIL else 0)
