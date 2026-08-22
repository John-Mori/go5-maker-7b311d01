#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""C-050 恒久・第2層= **返信を書いた側も宛先を宣言する**。その配線の検査。

なぜ要るか(2026-08-23 06:0x・プラットフォームSE→イージス研究室 DISPATCH-aegis-gl-1787432330178):
  第1層(commit a32602c)は「**入ってきた便**の差出人が宛先を宣言する」形だった。
  だが `audience=ai` と宣言された便への返信でも、**返信の中身**は「修理の報告」=
  Chami本人が読む物であり得る。入口の宣言は**出口の宛先を決めない**。
  Chami原文(msg 1540826605767630999)=「こうゆう内容は省略せんでほしい」。

  ★回送元が提案した「部屋を Chami読/AI専用 に分類する」は**採らなかった**。
    実測(inbox.db 3,046件)で **Chami本人が発言していない部屋は1つも無い**
    (hq 268件 / aegis-gl 100件 / gunji 17件…)。AI専用の部屋は実在しない=
    部屋で分けると許可リストが空になるか、名前当てを部屋名でやり直すだけになる。

  → 削ってよいのは**二重の宣言が揃った時だけ**=
    ①入ってきた便が `audience=ai`(第1層) ②返信を書いた側が `[表は要点]` の印を付けた
★must-fail 内蔵(印の無い返信が削れてしまう配線なら赤になる)。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts", "llm"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import dept_daemon as dd     # noqa: E402

fails = []


def check(name, got, want):
    ok = (got == want)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else f"  got={got!r} want={want!r}"))
    if not ok:
        fails.append(name)


AI = {"via": "dispatch", "audience": "ai"}          # ①を満たす便
CHAMI = {"via": "dispatch", "audience": "chami"}    # Chami向けの便
UNDECL = {"via": "dispatch", "author": "オタコン"}  # 宣言なし(8/23 05:42の実物と同じ形)
HUMAN = {"author": "chami_fusoh"}                   # Chami本人の発言
LONG = "あ" * 900
MARK = "[表は要点]\n" + LONG

# ── 1. 返信側の印(純粋関数) ──────────────────────────────────────
print("=== 1. 返信側の宣言(reply_wants_trim) ===")
check("印が無ければ False", dd.reply_wants_trim(LONG)[0], False)
check("印が無ければ本文は一字も触らない", dd.reply_wants_trim(LONG)[1], LONG)
check("印があれば True", dd.reply_wants_trim(MARK)[0], True)
check("★印は本文から取り除かれる", "[表は要点]" in dd.reply_wants_trim(MARK)[1], False)
check("印を取っても中身は残る", dd.reply_wants_trim(MARK)[1], LONG)
check("別名の印も効く(表要点)", dd.reply_wants_trim("[表要点]" + LONG)[0], True)
check("別名の印も効く(audience:ai)", dd.reply_wants_trim("[audience:ai]" + LONG)[0], True)
check("空でも落ちない", dd.reply_wants_trim("")[0], False)
check("Noneでも落ちない", dd.reply_wants_trim(None), (False, ""))
# ★似ているだけの語を印と取り違えない(勝手に削り始めないため)
check("印もどきは印ではない", dd.reply_wants_trim("表は要点だけでいい" + LONG)[0], False)

# ── 2. 二重の宣言(may_trim_reply) ────────────────────────────────
print("=== 2. 二重の宣言が揃った時だけ削れる ===")
check("★ai宣言 + 印あり= 削ってよい", dd.may_trim_reply(AI, MARK), True)
check("★ai宣言 + 印なし= 削らない(今回の苦情の形)", dd.may_trim_reply(AI, LONG), False)
check("chami宣言 + 印あり= 削らない", dd.may_trim_reply(CHAMI, MARK), False)
check("宣言なし + 印あり= 削らない", dd.may_trim_reply(UNDECL, MARK), False)
check("宣言なし + 印なし= 削らない", dd.may_trim_reply(UNDECL, LONG), False)
check("★Chami本人の発言への返信は何があっても削らない", dd.may_trim_reply(HUMAN, MARK), False)
# ★must-fail= 第1層だけ(印を見ない)なら、印の無い返信が削れてしまう
check("mustfail_第1層だけなら印なしでも削れる", dd.may_trim_front(AI), True)

# ── 3. 合流点の再現(本物の関数の並びをそのまま踏む) ────────────────
print("=== 3. 送信直前の合流点(印は必ず落ちる・削るのは二重宣言の時だけ) ===")


def outgoing(rec, text, dept="platform-se", mid="T-1", idx=0):
    """dept_daemon の送信直前と**同じ順番**で本文を作る(表に出る字を返す)。"""
    trim_ok = dd.may_trim_reply(rec, text)
    _, part = dd.reply_wants_trim(text)
    if trim_ok and len((part or "").strip()) > dd.REPLY_FRONT_LIMIT:
        full = dd.write_reply_full(dept, mid, idx, part)
        if full:
            part = dd.reply_front_digest(part, full)
    return part


o_ai_mark = outgoing(AI, MARK)
check("★二重宣言なら表は要点まで縮む", len(o_ai_mark) < len(LONG), True)
check("★縮めた時は必ず裏の在りかが書いてある", "全文=" in o_ai_mark, True)
check("★どの経路でも印は表へ出ない", any("[表は要点]" in outgoing(r, MARK)
                                          for r in (AI, CHAMI, UNDECL, HUMAN)), False)
for label, rec in (("ai宣言だが印なし", AI), ("chami宣言", CHAMI),
                   ("宣言なし", UNDECL), ("Chami本人", HUMAN)):
    src = LONG if rec is AI else MARK
    out = outgoing(rec, src)
    check(f"★削られない: {label}", out.strip(), LONG.strip())

# ★must-fail= 裏へ書けなければ削らない(fail-open)。書けない場所を渡して確かめる
_orig_dir = dd.REPLY_THREAD_DIR
try:
    dd.REPLY_THREAD_DIR = os.path.join(ROOT, "local", "llm", "thread", "\0bad")
    check("mustfail_裏へ書けない時は削らず全文が出る", outgoing(AI, MARK).strip(), LONG.strip())
finally:
    dd.REPLY_THREAD_DIR = _orig_dir

# ── 4. 部屋で分けないこと(回送元の案を採らなかった理由を固定する) ──────
print("=== 4. 部屋による分類を持ち込んでいない ===")
src = open(os.path.join(ROOT, "scripts", "llm", "dept_daemon.py"),
           encoding="utf-8", errors="replace").read()
for bad in ("CHAMI_READ_ROOMS", "AI_ONLY_ROOMS", "FRONT_TRIM_ROOMS"):
    check(f"部屋の許可リストを作っていない: {bad}", bad in src, False)
check("may_trim_reply は部屋(dept)を引数に取らない",
      "def may_trim_reply(rec, text)" in src, True)

if __name__ == "__main__":
    print(f"\nFAIL — {len(fails)}件: {fails}" if fails else "\nALL PASS")
    sys.exit(1 if fails else 0)
