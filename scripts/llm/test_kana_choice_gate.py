#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""出力ゲートH(かな括弧の選択肢ラベル)の回帰テスト。2026-09-02 イージス研究室・HQ-0232。

なぜ要るか:
  Chamiが炎上+再発を同時に押した実物= msg 1544451166887350322
  「(あ)、(い)で選択肢やめてって前も言ったでしょ〜」(3回目)。1回目=規律への明文化、
  2回目= msg 1540768838533259315「1,2,3〜やA,B,C〜でお願い」。文章の規律だけでは止まらない。
  ★今回のカスミは**対話セッション=経路②(ミラー)**で出た。経路①(常駐)だけに入れると
  同じ穴が残る(2026-08-15 口調ドリフトが辿ったのと同じ形の事故)。だから**両経路を実行で通す**。

★「ソース文字列一致だけで固めるな。入力を差し替えて経路を実行で通せ」(HQ裁定 2026-08-14)。
  経路②は output_gates.apply_gates を隔離temp上で**本当に走らせる**(本番の監査を汚さない)。
  経路①は dept_daemon.audit_kana_choice を**本当に走らせ**、送信チェーン(handle)からの
  呼び出しはコンパイル結果(co_names)で見る= 常駐の1便を丸ごと再現するのは現実的でない。
★must-fail 変異を3つ同梱= この検査が「常に緑」でないことを毎回その場で示す。
  変異は**動く別の実装**へ差し替える(行を消して文法を壊すと偽の緑になる・C-053)。

実行= python scripts/llm/test_kana_choice_gate.py (全PASSで exit 0)。
"""
import importlib
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

_PASS = 0
_FAIL = 0


def _check(name, cond):
    global _PASS, _FAIL
    if cond:
        _PASS += 1
        print("PASS", name)
    else:
        _FAIL += 1
        print("FAIL", name)


def _rows(path):
    if not os.path.exists(path):
        return []
    return [json.loads(l) for l in io.open(path, encoding="utf-8") if l.strip()]


def _load_mutant(name, src_path, frm, to):
    """元ファイルの一部を**動く別の実装**へ差し替えた版を読み込む(文法は壊さない)。"""
    src = io.open(src_path, encoding="utf-8").read()
    assert frm in src, "変異の当たり所が無い: " + name
    tmp = tempfile.mkdtemp(prefix="kana_mutant_")
    path = os.path.join(tmp, name + ".py")
    with io.open(path, "w", encoding="utf-8") as f:
        f.write(src.replace(frm, to))
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _co_names(code, func_name):
    """コンパイル済みコードの中から関数/メソッドを名前で探し、その co_names を返す。"""
    for c in code.co_consts:
        if getattr(c, "co_name", None) == func_name:
            return set(c.co_names)
        if hasattr(c, "co_consts"):
            got = _co_names(c, func_name)
            if got is not None:
                return got
    return None


# 実物に一番近い形= 1行に2個。Chamiが3回止めろと言った書き方。
REAL = "どっちで行く? (あ)このまま合流点に足す (い)別モジュールに切る"
# 箇条書き形(実際の選択肢はこの形でも出る)。
LIST = "案は2つ。\n(あ) 合流点に足す\n(い) 別モジュールに切る\nどっち?"
# 単発= 相槌。捕まえてはいけない。
SINGLE = "(あ)、そういうことか。なるほどな。"


def main():
    global _FAIL
    import kana_choice_gate as k

    # --- A 正本(kana_choice_gate)の振る舞い ---------------------------------
    res = k.kana_choice_corrections(REAL)
    _check("A-1 実物の (あ)(い) を捕まえる", len(res["applied"]) == 2)
    _check("A-1 (あ)→(1) / (い)→(2) へ直る",
           res["fixed"] == "どっちで行く? (1)このまま合流点に足す (2)別モジュールに切る")
    _check("A-2 箇条書き形(行頭ラベルが2行)も捕まえる",
           k.kana_choice_corrections(LIST)["fixed"].count("(1)") == 1
           and "(あ)" not in k.kana_choice_corrections(LIST)["fixed"])
    _check("A-3 単発の (あ) は相槌=捕まえない",
           k.kana_choice_corrections(SINGLE)["fixed"] == SINGLE
           and not k.kana_choice_corrections(SINGLE)["applied"])
    _check("A-4 全角括弧 (あ)(い) も同じに直る",
           k.kana_choice_corrections("(あ)これ (い)それ")["fixed"] == "(1)これ (2)それ")
    same = k.kana_choice_corrections("(あ)Aか(い)Bか。もう一度言う、(あ)Aだ。")
    _check("A-5 同じラベルは本文の中で同じ数字",
           same["fixed"] == "(1)Aか(2)Bか。もう一度言う、(1)Aだ。")
    _check("A-6 かな以外((1)(注)(笑))は触らない",
           k.kana_choice_corrections("(1)これ (2)それ (笑)")["applied"] == [])

    # ★誤発火する安全網は無視される(規律§3)= 規律そのものを論じる本文を壊さない。
    code_body = "規律は `(あ)` と `(い)` を禁じている。"
    _check("A-7 インラインcodeの中は触らない",
           k.kana_choice_corrections(code_body)["fixed"] == code_body)
    quoted = "> (あ)これ (い)それ\nと書いてあった。"
    _check("A-7 引用行(>)の中は触らない",
           k.kana_choice_corrections(quoted)["fixed"] == quoted)
    fence = "```\n(あ)これ (い)それ\n```\n上のような書き方はやめる。"
    _check("A-7 コードブロックの中は触らない",
           k.kana_choice_corrections(fence)["fixed"] == fence)

    # 一意に決まらない時(10種以上)は**素通し**して記録だけ(受け入れ条件3)。
    many = " ".join("(%s)案" % c for c in "あいうえおかきくけこ")
    mres = k.kana_choice_corrections(many)
    _check("A-8 10種以上は素通し(記録だけ)",
           mres["fixed"] == many and len(mres["remaining"]) == 1 and not mres["applied"])

    # fail-open。
    _check("A-9 空/Noneで落ちない",
           k.kana_choice_corrections("")["fixed"] == ""
           and k.kana_choice_corrections(None)["fixed"] is None)

    # --- B 経路②(ミラー= output_gates)を実行で通す ---------------------------
    tmp = tempfile.mkdtemp(prefix="kana_gate_")
    os.environ["GO5_LOCAL_DIR"] = tmp
    os.environ.pop("GO5_MIRROR_GATE_FIX", None)     # ★既定(警告のみ)のままでもHは効くこと
    import output_gates
    importlib.reload(output_gates)                  # LOCAL/AUDIT を tmp で解決
    ta = os.path.join(tmp, "llm", "tone_audit.jsonl")

    fixed, summ = output_gates.apply_gates("hq", "シャビ・アロンソ", REAL, source="mirror",
                                           msg_id="TEST-1")
    _check("B-1 経路②の本文で (あ)(い) が捕まる", summ.get("kana_choice_fix") == 2)
    _check("B-1 経路②の本文が 1,2 へ直って返る", "(あ)" not in fixed and "(1)" in fixed)
    rows = [r for r in _rows(ta) if r.get("event", "").startswith("kana_choice")]
    _check("B-2 監査は既存の tone_audit.jsonl へ相乗り", len(rows) == 2)
    _check("B-2 経路は source=mirror で分かる",
           rows and all(r.get("source") == "mirror" for r in rows))
    _check("B-2 msg_id が残る", rows and all(r.get("msg_id") == "TEST-1" for r in rows))

    f2, s2 = output_gates.apply_gates("hq", "シャビ・アロンソ", SINGLE, source="mirror")
    _check("B-3 単発の (あ) は経路②でも捕まらない",
           f2 == SINGLE and s2.get("kana_choice_fix") == 0)

    # 例外時は素通し(fail-open)= ゲートが送信を殺さない。
    save = output_gates._kana_choice
    class _Boom(object):
        @staticmethod
        def apply_and_audit(*a, **kw):
            raise RuntimeError("boom")
    output_gates._kana_choice = _Boom
    f3, _ = output_gates.apply_gates("hq", "シャビ・アロンソ", REAL, source="mirror")
    output_gates._kana_choice = save
    _check("B-4 例外時は本文が素通しで返る(fail-open)", f3 == REAL)

    # --- C 経路①(常駐= dept_daemon)を実行で通す ------------------------------
    import dept_daemon as d
    d_audit = os.path.join(tmp, "llm", "tone_audit_daemon.jsonl")
    save_audit = d.TONE_AUDIT
    d.TONE_AUDIT = d_audit                          # 本番の監査を汚さない
    try:
        dfixed, dapp, dwarn = d.audit_kana_choice("hq", "シャビ・アロンソ", REAL,
                                                  {"msg_id": "TEST-2"})
    finally:
        d.TONE_AUDIT = save_audit
    _check("C-1 経路①の本文でも (あ)(い) が捕まる", len(dapp) == 2 and "(あ)" not in dfixed)
    drows = _rows(d_audit)
    _check("C-1 経路①は source=daemon で分かる",
           drows and all(r.get("source") == "daemon" for r in drows))
    _check("C-2 経路①でも単発は捕まらない",
           d.audit_kana_choice("hq", "シャビ・アロンソ", SINGLE)[0] == SINGLE)
    save_mod = d._kana_choice
    d._kana_choice = None                           # 正本が読めない状況を作る
    _check("C-3 正本が無い時は素通し(fail-open)",
           d.audit_kana_choice("hq", "シャビ・アロンソ", REAL)[0] == REAL)
    d._kana_choice = save_mod

    # 送信チェーン(handle)から**本当に呼ばれる形でコンパイルされている**こと。
    dsrc = io.open(os.path.join(_HERE, "dept_daemon.py"), encoding="utf-8").read()
    dcode = compile(dsrc, "dept_daemon.py", "exec")
    _check("C-4 常駐の送信チェーン(handle)がゲートHを呼ぶ",
           "audit_kana_choice" in (_co_names(dcode, "handle") or set()))

    # --- D must-fail 変異(この検査が本当に赤くなるかを毎回その場で示す) ---------
    # D-1 検出を「1行に3個以上」へ広げた版= 実物(2個)が抜ける。
    m1 = _load_mutant("kana_mut1", os.path.join(_HERE, "kana_choice_gate.py"),
                      "        if len(spans) >= 2:",
                      "        if len(spans) >= 3:   # 変異: 2個では捕まえない")
    _check("D-1 must-fail 閾値を3個にすると実物が抜ける(=A-1は本当に効いている)",
           m1.kana_choice_corrections(REAL)["applied"] == [])
    # D-2 行頭ラベルが1行だけでも拾う版= 相槌の (あ) を壊す。
    m2 = _load_mutant("kana_mut2", os.path.join(_HERE, "kana_choice_gate.py"),
                      "    if len({sp[3] for _, sp in head_lines}) >= 2:",
                      "    if len({sp[3] for _, sp in head_lines}) >= 1:   # 変異: 単発も拾う")
    _check("D-2 must-fail 単発も拾う版にすると相槌が壊れる(=A-3は本当に効いている)",
           m2.kana_choice_corrections(SINGLE)["fixed"] != SINGLE)
    _check("D-2 変異版でも実物は捕まる(変異が的外れでないことの確認)",
           m2.kana_choice_corrections(REAL)["applied"] != [])
    # D-3 経路②の配線を外した版= 経路②の本文が直らない(=B-1は配線を見ている)。
    m3src = io.open(os.path.join(_HERE, "output_gates.py"), encoding="utf-8").read()
    frm = ("            s2, _kfix, _kwarn = _kana_choice.apply_and_audit(\n"
           "                s, dept=dept, persona=str(persona or \"\"), source=source,\n"
           "                msg_id=str(msg_id or \"\"), audit_path=TONE_AUDIT)")
    if frm not in m3src:
        _check("D-3 must-fail 変異の当たり所がある", False)
    else:
        m3 = _load_mutant("kana_mut3", os.path.join(_HERE, "output_gates.py"), frm,
                          "            s2, _kfix, _kwarn = (s, [], [])   # 変異: ゲートHを通さない")
        _check("D-3 must-fail 経路②の配線を外すと (あ)(い) がそのまま出る",
               m3.apply_gates("hq", "シャビ・アロンソ", REAL, source="mirror")[0] == REAL)

    shutil.rmtree(tmp, ignore_errors=True)
    os.environ.pop("GO5_LOCAL_DIR", None)
    print("\n%d PASS / %d FAIL" % (_PASS, _FAIL))
    return 1 if _FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
