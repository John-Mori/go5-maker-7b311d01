#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""出力ゲートE(名乗りタグの残存)の回帰テスト。

実行:            python scripts/llm/test_persona_tag_gate.py
変異(must-fail): python scripts/llm/test_persona_tag_gate.py --mutate

★2026-09-01 新設。発注= 研究室HQ DISPATCH-aegis-gl-1788244228714。
  引き金= Chami「最初に書く必要ないこと書いてるよ あと一ノ瀬怜とか いらないし名乗り」
  (msg 1544228523886116915)。壊れた実物= 同日 06:02:25 platform-se の便で `[一ノ瀬怜]` が
  **非空4行目**に在り、前置き3行ごと Chami の画面へ出た。
★resolve は本物の名簿を使わずここで固定する(本番の名簿が育っても赤にならない)。
  _avatar_keys() も差し替える= ローカルの persona_avatars.json の中身に結果を依存させない。
"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dept_daemon as dd   # noqa: E402

results = []

# 単独人格部屋(platform-se)と同じ形の resolver= 閉じた名簿1人。
SOLO = dd.solo_tag_resolver({"persona": "一ノ瀬怜"})
OTHER = "ククール"          # 他部屋の人格(この部屋では引けない)

# 事故の実物(2026-09-01 06:02:25 platform-se)。前置き3行= 作業メモ2行+区切り線。
REAL = "\n".join([
    "codever機構(C-042)は閉包のハッシュ差分で拾うので、常駐の載せ替えは自動で走る。",
    "以下、部屋への返信(本文=返信そのもの)。",
    "---",
    "[一ノ瀬怜] ちゃみ、原因はgatewayの静かな死。受信が8時間止まってた。",
    "2行目の本文。",
])
REAL_WANT = "ちゃみ、原因はgatewayの静かな死。受信が8時間止まってた。\n2行目の本文。"


def check(name, cond):
    results.append((name, bool(cond)))
    print(f"  {'PASS' if cond else 'FAIL'}: {name}")


def run(text, resolve=SOLO, dept="platform-se", speaker="一ノ瀬怜"):
    """ゲートを通す。★外へ出る手(監査への書き込み)だけ偽物・判定と分岐は本物のまま。"""
    rec = []
    o_tag, o_pre, o_keys = dd._audit_tag, dd._audit_preamble, dd._avatar_keys
    dd._audit_tag = lambda dept, who, outcome, line: rec.append((outcome, who))
    dd._audit_preamble = lambda dept, who, dropped: rec.append(("preamble_dropped", who))
    dd._avatar_keys = lambda: frozenset({"一ノ瀬怜", OTHER, "ケヴィン・デブライネ"})
    try:
        return dd.persona_tag_leak_gate(text, resolve, dept=dept, speaker=speaker), rec
    finally:
        dd._audit_tag, dd._audit_preamble, dd._avatar_keys = o_tag, o_pre, o_keys


def main():
    # ---- 1) 壊れている実物が直ること(0歩目の再現をそのまま検査にした) ----
    up = dd.strip_solo_persona_tag(REAL, SOLO, dept="platform-se")
    check("実物: 上流(窓3)では剥がせていない=この検査の前提が生きている",
          "[一ノ瀬怜]" in up)
    out, rec = run(up)
    check("実物: ゲートEでタグが消える", "[一ノ瀬怜]" not in out)
    check("実物: 前置き(作業メモ+区切り線)も一緒に消える", "codever機構" not in out)
    check("実物: 本文は1文字も欠けない", out == REAL_WANT)
    check("実物: 直したことを tag_gate_fixed で残す",
          ("tag_gate_fixed", "一ノ瀬怜") in rec)
    check("実物: 落とした前置きを preamble_dropped で残す",
          ("preamble_dropped", "一ノ瀬怜") in rec)

    # ---- 2) 上流が成功した便では空振り(既存19部屋の挙動を1ミリも変えない) ----
    for nm, src in (("ただの本文", "ちゃみ、直したよ。"),
                    ("タグが既に落ちた後", REAL_WANT),
                    ("解決できない[...]は本文", "[検証] の結果はこうだ。"),
                    ("空文字", ""),
                    ("空白だけ", "  \n  ")):
        out, rec = run(src)
        check(f"空振り: {nm}=1文字も触らない", out == src)
        check(f"空振り: {nm}=監査も鳴らない", rec == [])

    # ---- 3) 窓の幅(前置き何行まで直すか) ----
    #   実測(persona_render_audit.jsonl 965件)の最大が非空3行= 4 は「観測最大+1」。
    for n in range(0, dd._TAG_GATE_HEAD_LINES + 1):
        src = "\n".join(["前置き%d" % (i + 1) for i in range(n)] + ["[一ノ瀬怜] 本文だ。"])
        out, rec = run(src)
        check(f"窓の中: 前置き{n}行は直る", out == "本文だ。")
        check(f"窓の中: 前置き{n}行で late は鳴らさない",
              not [o for o, _ in rec if o == "tag_late_leak"])
    over = dd._TAG_GATE_HEAD_LINES + 1
    src = "\n".join(["前置き%d" % (i + 1) for i in range(over)] + ["[一ノ瀬怜] 本文だ。"])
    out, rec = run(src)
    check(f"窓の外: 前置き{over}行は**触らない**(本文中の引用を壊さない)", out == src)
    check(f"窓の外: 前置き{over}行を tag_late_leak で数える",
          [o for o, _ in rec] == ["tag_late_leak"])
    check("窓の数え方: 空行は幅に数えない",
          run("あ\n\n\nい\n\n[一ノ瀬怜] 本文だ。")[0] == "本文だ。")

    # ---- 4) 他部屋の人格名= 触らず数えるだけ(閉じた名簿の設計を崩さない) ----
    src = "報告だ。\n[%s] という便が来ていた。" % OTHER
    out, rec = run(src)
    check("他室の人格: 本文を触らない(引用を壊さない)", out == src)
    check("他室の人格: tag_foreign_leak で数える",
          [o for o, _ in rec] == ["tag_foreign_leak"])
    src2 = "報告だ。\n[まったく無い名前] という便が来ていた。"
    out, rec = run(src2)
    check("名簿にも人格表にも無いタグ: 触らない・鳴らない", out == src2 and rec == [])

    # ---- 5) fail-open(§3 可用性に関わる所は fail-open・最悪の事故は沈黙) ----
    check("fail-open: 落とすと空になる便は落とさない",
          run("前置き\n[一ノ瀬怜]")[0] == "前置き\n[一ノ瀬怜]")
    check("fail-open: resolve が無い(None)なら触らない",
          run(REAL, resolve=None)[0] == REAL)

    def boom(_nm):
        raise RuntimeError("resolver が壊れた")
    check("fail-open: resolve が例外を投げても元の本文を返す",
          run(REAL, resolve=boom)[0] == REAL)

    def boom_keys():
        raise RuntimeError("avatar 表が読めない")
    o_keys = dd._avatar_keys
    dd._avatar_keys = boom_keys
    try:
        check("fail-open: 人格表が読めなくても元の本文を返す",
              dd.persona_tag_leak_gate("報告。\n[%s] だ。" % OTHER, SOLO) == "報告。\n[%s] だ。" % OTHER)
    finally:
        dd._avatar_keys = o_keys

    # ---- 6) 多人格部屋(split 後の残り)でも同じ判定が効く ----
    room = ("ケヴィン・デブライネ", "アメス")

    def multi(nm):
        n = str(nm or "").strip()
        return n if n in room else None
    blocks = dd.split_persona_blocks("前置き\n[アメス] 本文よ。", multi, dept="aegis-gl")
    check("多人格: 上流で解決できた便はゲートの手前で既に綺麗",
          blocks == [("アメス", "本文よ。")])
    out, rec = run("[アメス] 本文よ。", resolve=multi, dept="aegis-gl", speaker="アメス")
    check("多人格: 万一残っても同じ resolve で落とせる", out == "本文よ。")

    # ---- 7) 配線(送信直前の合流点に、C/D の後ろで置かれているか) ----
    import inspect  # noqa: E402
    src = inspect.getsource(dd.Daemon.handle) if hasattr(dd, "Daemon") else ""
    if not src:
        for _n, _o in vars(dd).items():
            if inspect.isclass(_o) and hasattr(_o, "handle"):
                src = inspect.getsource(_o.handle)
                break
    check("配線: handle() から persona_tag_leak_gate を呼んでいる",
          "persona_tag_leak_gate(" in src)
    check("配線: 呼びは audit_tone(ゲートD)より後ろ=送信直前",
          src.find("persona_tag_leak_gate(") > src.find("audit_tone("))
    check("配線: 上流と同じ resolve を1本だけ組んで渡している",
          src.count("_tag_resolve = ") == 2 and "_tag_resolve, dept=self.dept" in src)
    check("配線: 分割/剥がしの呼び元でも同じ1本を使っている",
          "split_persona_blocks(\n                    reply, _tag_resolve" in src
          and "strip_solo_persona_tag(\n                    reply, _tag_resolve" in src)
    check("既存の窓 _SOLO_PREAMBLE_MAX_LINES は動かしていない",
          dd._SOLO_PREAMBLE_MAX_LINES == 3)

    ok = sum(1 for _, c in results if c)
    ng = len(results) - ok
    print(f"\n{ok} PASS / {ng} FAIL")
    return 0 if ng == 0 else 1


# ---------------------------------------------------------------- 変異(C-053)
#   ★変異は「動く別の実装」へ戻す= 文法を壊した偽の赤にしない。
def _mut_noop(text, resolve, dept="", speaker=""):
    """変異1= ゲートを置かなかった世界(旧の挙動)。動くが実物を直せない。"""
    return str(text or "")


def _mut_keep_preamble(text, resolve, dept="", speaker=""):
    """変異2= タグだけ剥がし前置きは残す実装。動くが §4.8 の作業メモ露出が残る。"""
    t = str(text or "")
    lines = t.split("\n")
    for i, ln in enumerate(lines):
        m = dd._tag_match(ln)
        if m and callable(resolve) and resolve(m[0]):
            lines[i] = m[1]
            return "\n".join(lines).strip()
    return t


def _mut_unbounded(text, resolve, dept="", speaker=""):
    """変異3= 窓を無制限にした実装。動くが本文中の引用まで前置き扱いで消す。"""
    old = dd._TAG_GATE_HEAD_LINES
    dd._TAG_GATE_HEAD_LINES = 10 ** 6
    try:
        return _REAL_GATE(text, resolve, dept=dept, speaker=speaker)
    finally:
        dd._TAG_GATE_HEAD_LINES = old


_REAL_GATE = dd.persona_tag_leak_gate

MUTANTS = (
    ("変異1 ゲート無し(旧の挙動)", _mut_noop, "実物: ゲートEでタグが消える"),
    ("変異2 タグだけ剥がす", _mut_keep_preamble, "実物: 前置き(作業メモ+区切り線)も一緒に消える"),
    ("変異3 窓を無制限", _mut_unbounded, "窓の外: 前置き5行は**触らない**(本文中の引用を壊さない)"),
)


def mutate():
    bad = 0
    for name, fn, want_red in MUTANTS:
        del results[:]
        dd.persona_tag_leak_gate = fn
        try:
            print(f"\n=== {name} ===")
            try:
                main()
            except Exception as e:
                print("  (検査が例外で止まった: %s)" % e)
        finally:
            dd.persona_tag_leak_gate = _REAL_GATE
        red = [n for n, c in results if not c]
        hit = want_red in red
        print(f"  → 狙った1件が赤か: {'OK' if hit else 'NG'}  (赤={len(red)}件)")
        if not hit:
            bad += 1
    print(f"\n変異 {len(MUTANTS)}件中 {len(MUTANTS) - bad}件が狙いどおり赤")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(mutate() if "--mutate" in sys.argv else main())
