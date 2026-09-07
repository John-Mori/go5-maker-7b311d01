#!/usr/bin/env python3
"""生成ノイズの孤立フィラー行スクラブの回帰検査(2026-09-05 イージス研究室)。

対象= DEF-codex-care-noise-line-20260905(QA起票・品質管理部門)。
  otacon-radio・2026-09-05 11:44〜11:47 の2便で、日本語本文の段落間に単独の "care" 行が
  計5本そのまま出た(msg 1545625670191943791=1本 / 1545626524974190654=4本)。
  生成側(gpt-5.5)のノイズ。モデルに「吐くな」は保証させられないので出口で剥がす。

★この検査は**実物の body** を通す(作り話で緑にしない)。
  実物は local/llm/send_audit.jsonl の当該 msg_id から引く(部屋の本文は repo へ置かない)。
  一度引けたら local/_work/def_care_real_bodies.json へ退避し、台帳が流れても実物で回せるようにする。
★must-fail を同梱= スクラブを外した**動く別実装**(C-053)を読み込み、赤くなることを毎回その場で示す。

実行: python scripts/discord/test_filler_line_scrub.py (全PASSで exit 0)
"""
import ast
import importlib.util
import io
import json
import os
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)

AUDIT = os.path.join(ROOT, "local", "llm", "send_audit.jsonl")
CACHE = os.path.join(ROOT, "local", "_work", "def_care_real_bodies.json")
REAL_IDS = {"1545625670191943791": 1, "1545626524974190654": 4}   # msg_id → 孤立care行の本数
P = F = 0


def ok(cond, name):
    global P, F
    if cond:
        P += 1
        print("PASS", name)
    else:
        F += 1
        print("FAIL", name)


def isolated(body, word="care"):
    """段落間の孤立行(前後が空行/端)で、中身がその語だけの行を数える。"""
    lines = str(body or "").split("\n")
    n = len(lines)
    return sum(1 for i, ln in enumerate(lines)
               if ln.strip() == word
               and (i == 0 or lines[i - 1].strip() == "")
               and (i == n - 1 or lines[i + 1].strip() == ""))


def real_bodies():
    """実物2便の body を台帳から引く。無ければ退避から。両方無ければ空。"""
    got = {}
    if os.path.exists(AUDIT):
        for ln in io.open(AUDIT, encoding="utf-8", errors="replace"):
            try:
                o = json.loads(ln)
            except Exception:
                continue
            if str(o.get("msg_id")) in REAL_IDS and o.get("body"):
                got[str(o["msg_id"])] = o["body"]
    if len(got) == len(REAL_IDS):
        try:                                    # 台帳が流れても実物で回せるよう退避(C-003の趣旨)
            os.makedirs(os.path.dirname(CACHE), exist_ok=True)
            json.dump(got, io.open(CACHE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        except OSError:
            pass
        return got
    if os.path.exists(CACHE):
        try:
            return json.load(io.open(CACHE, encoding="utf-8"))
        except Exception:
            pass
    return got


import enjoh  # noqa: E402

# --- A 実物2便(QAのclose条件そのもの) -------------------------------------------------
REAL = real_bodies()
ok(len(REAL) == len(REAL_IDS),
   f"A-0 実物2便の body を引けた(台帳 {os.path.relpath(AUDIT, ROOT)} または退避)")
for mid, want in REAL_IDS.items():
    body = REAL.get(mid)
    if body is None:
        ok(False, f"A-1 msg {mid} の実物が無い= 検査不能(台帳を復元してから回す)")
        continue
    ok(isolated(body) == want, f"A-1 msg {mid} の実物には孤立care行が {want}本ある(前提の確認)")
    out = enjoh.enjoh_backstop(body, tag="test")
    ok(isolated(out) == 0, f"A-2 msg {mid} をスクラブに通すと孤立care行が 0 になる")
    for para in [p for p in body.split("\n\n") if p.strip() and p.strip() != "care"]:
        if para.strip() not in out:
            ok(False, f"A-3 msg {mid} 本文の段落が壊れた: {para.strip()[:24]}…")
            break
    else:
        ok(True, f"A-3 msg {mid} 日本語の段落は1字も欠けていない")
    ok("\n\n\n" not in out, f"A-4 msg {mid} 段落の区切りは空行1本のまま(空行が余らない)")

# --- B 触らない側(誤爆で情報を消さない) ------------------------------------------------
keep = "了解、直すね。\n\nOK\n\n次の便で出すよ。ここは日本語の本文だ。"
ok(enjoh.enjoh_backstop(keep, tag="test") == keep, "B-1 OK など単独で意味を持つ語は落とさない")

fenced = "実装はこうだ。説明を続けるね、ここは日本語の本文。\n\n```\n\ncare\n\n```\n\n以上。"
ok(enjoh.enjoh_backstop(fenced, tag="test") == fenced, "B-2 コードブロックの中は触らない")

eng = "The build failed.\n\ncare\n\nPlease retry the job later."
ok(enjoh.enjoh_backstop(eng, tag="test") == eng, "B-3 日本語本文でない便は触らない(英語の1語行を消さない)")

inline = "この語について話すね、日本語の本文の中の話だ。\n\n`care`\n\nという語を見せたい。"
ok(enjoh.enjoh_backstop(inline, tag="test") == inline, "B-4 インラインcodeで見せている語は落とさない")

bullet = "手当ての一覧を書くね。日本語の本文が続いている。\n\n- care\n\n以上だ。"
ok(enjoh.enjoh_backstop(bullet, tag="test") == bullet, "B-5 箇条書き(記号付き)は落とさない")

inword = "care について説明するね。ここは日本語の本文で、行の中に語が在る。\n\n次の段落だよ。"
ok(enjoh.enjoh_backstop(inword, tag="test") == inword, "B-6 文中の語は触らない(孤立行だけが対象)")

nonisolated = "説明を書くね、ここは日本語の本文。\ncare\n次の行だ。"
ok(enjoh.enjoh_backstop(nonisolated, tag="test") == nonisolated,
   "B-7 前後が空行でない1語行は触らない")

long_ = "説明を書くね、ここは日本語の本文だ。\n\nsupercalifragilistic\n\n次の段落。"
ok(enjoh.enjoh_backstop(long_, tag="test") == long_, "B-8 13字以上の1語行は触らない(文の可能性)")

ok(enjoh.enjoh_backstop("", tag="test") == "" and enjoh.enjoh_backstop(None, tag="test") is None,
   "B-9 空文字/Noneは例外を出さず不変(fail-open)")

FIRE, ENJOH = "\U0001F525", "<:enjoh:1541126866981752883>"
ok(enjoh.enjoh_backstop(FIRE + "炎上 9件が残っている", tag="test") == ENJOH + "恒久 9件が残っている",
   "B-10 既存の炎上表記ゲートは1ミリも壊れていない")

# --- C 配線(外へ撃つ5口すべてが同じ合流点を呼ぶ= C-064) ------------------------------
WIRES = [("discord/persona_send.py", "main"), ("discord/bot_send.py", "main"),
         ("behop/behop.py", "dc_send"), ("codex/codex_run.py", "dc_send"),
         ("imagegen/generate.py", "discord_upload")]
def _calls_of(node):
    return {c.func.id for c in ast.walk(node) if isinstance(c, ast.Call)
            and isinstance(c.func, ast.Name)}


def reaches_gate(path, fn, depth=4):
    """fn() から `enjoh_backstop` へ**同じファイル内の関数を辿って**到達できるか。

    ★2026-09-07(イージス研究室)= 直接呼びだけを見ていたが、codex_run は
      dc_send → dc_send_result → dc_send_chunks / prepare_discord_chunks() と分かれており、
      ゲートは prepare_discord_chunks の中に在る。**配線は生きているのに赤**になっていた
      (=偽の赤。赤が定位置になった検査は、本物の穴が来ても誰も見ない)。
      緩めたのではなく**辿るようにした**= 途中の関数がゲートを落とせば今も赤になる。
    """
    tree = ast.parse(io.open(path, encoding="utf-8").read(), path)
    funcs = {x.name: x for x in ast.walk(tree) if isinstance(x, ast.FunctionDef)}
    seen, frontier = set(), [fn]
    for _ in range(depth):
        nxt = []
        for name in frontier:
            if name in seen or name not in funcs:
                continue
            seen.add(name)
            names = _calls_of(funcs[name])
            if "enjoh_backstop" in names:
                return True
            nxt.extend(names)
        frontier = nxt
    return False


for rel, fn in WIRES:
    path = os.path.join(ROOT, "scripts", *rel.split("/"))
    ok(reaches_gate(path, fn), f"C-1 {rel}:{fn}() が合流点ゲートを呼ぶ")
ok("filler_line_scrub" in enjoh.enjoh_backstop.__code__.co_names,
   "C-2 enjoh_backstop() が filler_line_scrub を呼ぶ(5口へ同時に入っている)")

# --- D must-fail(スクラブを外すと赤くなることを毎回その場で示す・C-053) ----------------
src = io.open(os.path.join(HERE, "enjoh.py"), encoding="utf-8").read()
CALL = "    body = filler_line_scrub(body, tag=tag)"
assert CALL in src, "must-fail の当たり所が無い= 検査の前提が崩れている"
tmp = tempfile.mkdtemp(prefix="filler_mutant_")
mpath = os.path.join(tmp, "enjoh_mutant.py")
io.open(mpath, "w", encoding="utf-8").write(
    src.replace(CALL, "    body = body  # 変異: スクラブを通さない(2026-09-05以前の実装)"))
spec = importlib.util.spec_from_file_location("enjoh_mutant", mpath)
mut = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mut)
mut_body = REAL.get("1545626524974190654") or "本文だよ、ここは日本語。\n\ncare\n\n次の段落。"
ok(isolated(mut.enjoh_backstop(mut_body, tag="mutant")) > 0,
   "D-1 must-fail スクラブを外すと孤立care行が残る(=A-2は本当に効いている)")
ok(mut.enjoh_backstop(FIRE + "炎上 9件が残っている") == ENJOH + "恒久 9件が残っている",
   "D-2 must-fail 変異は文法も炎上ゲートも壊していない(偽の赤でない)")

print(f"\n合計 PASS={P} FAIL={F}")
sys.exit(0 if F == 0 else 1)
